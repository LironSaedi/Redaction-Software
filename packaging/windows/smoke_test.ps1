<#
End-to-end check of a built Windows installer, the way a user goes through it:

  install for this user (no administrator) -> open Obscura from the Start menu -> setup assistant (case files in a
  folder with an accented and a Chinese name) -> analyze and export a PDF with a text page and a scanned page ->
  uninstall from Settings > Apps while Obscura runs, keeping the case files -> reinstall (finds them again) ->
  uninstall from inside Obscura, deleting the case files.

Used by the installers workflow; also works on a spare Windows 10/11 PC or VM:

    powershell -ExecutionPolicy Bypass -File packaging\windows\smoke_test.ps1 -Installer dist\Obscura-1.0.0-Windows.exe

It installs and removes Obscura like a user would, including %LOCALAPPDATA%\Obscura at the end, so never run it on a
computer whose Obscura case files you want to keep. Logs go to -LogDir.
Not covered (needs a person at the screen): the installer and uninstaller wizards themselves, the "delete case
files?" question in an interactive uninstall, and the folder picker.
#>
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$LogDir = (Join-Path $env:TEMP "obscura-smoke")
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Installer = (Resolve-Path $Installer).Path
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3C2B71-4E5A-4C1E-9B7D-0B1A6F2E9C44}_is1"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$AppHome = Join-Path $env:LOCALAPPDATA "Obscura"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Obscura"
# "Obscura Jos<e-acute> <Chinese for data>" is built from code points, so this file stays ASCII (Windows PowerShell
# reads scripts without a byte-order mark as ANSI)
$DataDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) ("Obscura Jos" + [char]0x00E9 + " " + [char]0x6570 + [char]0x636E)
New-Item -ItemType Directory -Force $LogDir | Out-Null
$script:Base = ""
$script:Auth = @{}
$script:App = ""

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Check($ok, [string]$what) {
    if (-not $ok) { throw "FAILED: $what" }
    Write-Host "  ok  $what"
}
function Wait-Until([scriptblock]$cond, [int]$seconds, [string]$what) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $seconds) {
        if (& $cond) { Write-Host ("  ok  {0} ({1:N0} s)" -f $what, $sw.Elapsed.TotalSeconds); return }
        Start-Sleep -Milliseconds 500
    }
    throw "FAILED: $what (waited $seconds s)"
}
function Obscura-Processes([string]$app) {
    # everything running from the program folder except the uninstaller itself
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith("$app\", "OrdinalIgnoreCase") -and $_.Name -notlike "unins*" })
}
function Api([string]$method, [string]$path, $body = $null) {
    $req = @{ Method = $method; Uri = "$($script:Base)$path"; Headers = $script:Auth; UseBasicParsing = $true; TimeoutSec = 120 }
    if ($null -ne $body) {
        # bytes, so Windows PowerShell does not re-encode non-ASCII text as ISO-8859-1
        $req.Body = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 5 -Compress))
        $req.ContentType = "application/json; charset=utf-8"
    }
    Invoke-RestMethod @req
}
function Wait-ObscuraJob([int]$id, [string]$what) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Seconds 1
        $j = Api GET "/api/jobs/$id"
    } while ($j.status -notin "done", "failed", "cancelled" -and $sw.Elapsed.TotalSeconds -lt 900)
    Check ($j.status -eq "done") ("{0} finished: {1} {2} ({3:N0} s)" -f $what, $j.status, $j.message, $sw.Elapsed.TotalSeconds)
    $j
}
function Save-Logs([string]$tag) {
    foreach ($f in "$AppHome\launcher.log", "$AppHome\data\logs\server.log", "$DataDir\logs\server.log") {
        if (Test-Path $f) { Copy-Item $f (Join-Path $LogDir ("$tag-" + (Split-Path $f -Leaf))) -Force }
    }
    Get-ChildItem $env:TEMP -Filter "Setup Log*.txt" -ErrorAction SilentlyContinue | Copy-Item -Destination $LogDir -Force
    if (Test-Path "$env:TEMP\Obscura-uninstall.log") { Copy-Item "$env:TEMP\Obscura-uninstall.log" $LogDir -Force }
}

function Install-Obscura([int]$n) {
    Step "install #$n for this user"
    $p = Start-Process $Installer -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
        "/LOG=`"$LogDir\install-$n.log`"" -Wait -PassThru
    Check ($p.ExitCode -eq 0) "installer finished (exit code $($p.ExitCode))"
    $key = Get-ItemProperty $UninstallKey -ErrorAction SilentlyContinue
    Check ($key -and $key.DisplayName -eq "Obscura Redaction Studio") "listed in Settings > Apps as Obscura Redaction Studio"
    $script:App = $key.InstallLocation.TrimEnd("\")
    Check ($script:App -like "$env:LOCALAPPDATA\Programs\*") "installed without administrator rights: $($script:App)"
    foreach ($f in "runtime\pythonw.exe", "runtime\python.exe", "runtime\msvcp140.dll", "app\obscura_launch.pyw",
                   "app\frontend\index.html", "tesseract\tesseract.exe", "tesseract\tessdata\eng.traineddata",
                   "obscura.ico", "unins000.exe") {
        Check (Test-Path (Join-Path $script:App $f)) "contains $f"
    }
    Check (@(Get-ChildItem "$($script:App)\licenses").Count -gt 20) "third-party licence texts included"
    Check (Test-Path "$StartMenu\Obscura.lnk") "Start menu shortcut"
}

function Start-Obscura {
    Step "open Obscura from the Start menu"
    Remove-Item "$AppHome\running.json" -Force -ErrorAction SilentlyContinue
    Start-Process "$StartMenu\Obscura.lnk"   # the same as clicking the shortcut
    Wait-Until { Test-Path "$AppHome\running.json" } 120 "launcher started the server"
    $port = (Get-Content -Raw "$AppHome\running.json" | ConvertFrom-Json).port
    $script:Base = "http://127.0.0.1:$port"
    $script:Auth = @{}
    Wait-Until { try { (Invoke-RestMethod -UseBasicParsing "$($script:Base)/api/health" -TimeoutSec 3).ok } catch { $false } } 600 "Obscura answers on port $port"
    $procs = Obscura-Processes $script:App
    Check (@($procs | Where-Object Name -eq "pythonw.exe").Count -ge 1) "control window is running (pythonw.exe)"
    Check (@($procs | Where-Object Name -eq "python.exe").Count -ge 1) "server is running (python.exe, hidden console)"
}

function Sign-In {
    # retried: on a new database the browser that Obscura opens signs in at the same moment, and the server's
    # first-time creation of the built-in account can then fail one of the two requests
    for ($i = 1; ; $i++) {
        try { $script:Auth = @{ Authorization = "Bearer " + (Api POST "/api/auth/local" @{}).token }; return }
        catch { if ($i -ge 3) { throw }; Write-Host "  (sign-in attempt $i failed: $($_.Exception.Message); retrying)"; Start-Sleep -Seconds 2 }
    }
}

$failed = $true
try {
    Check ([Environment]::Is64BitOperatingSystem) "64-bit Windows $([Environment]::OSVersion.Version)"
    if (Test-Path $UninstallKey) { throw "Obscura is already installed on this computer; uninstall it first" }

    Install-Obscura 1
    Start-Obscura

    Step "setup assistant"
    $st = Api GET "/api/setup/state"
    Check $st.needed "setup assistant opens on the first start"
    Check ($st.platform -like "Windows*") "platform: $($st.platform)"
    Check $st.ocr "OCR engine found (bundled Tesseract)"
    Check $st.spacy_model "spaCy language model found"
    Check $st.autostart_available "start at login available"
    $boot = (Api GET "/api/health").boot
    $r = Api POST "/api/setup/complete" @{ mode = "single"; data_dir = $DataDir }
    Check ($r.ok -and -not $r.require_login) "setup completed (this computer only, no sign-in)"
    if ($r.restart) {
        Wait-Until { try { $h = Invoke-RestMethod -UseBasicParsing "$($script:Base)/api/health" -TimeoutSec 3; $h.ok -and $h.boot -ne $boot } catch { $false } } 600 "Obscura restarted with the new case folder"
    }
    Check (-not (Api GET "/api/setup/state").needed) "setup assistant is done"

    Step "system settings"
    Sign-In
    Check (Test-Path (Join-Path $DataDir "obscura.db")) "case database is in the chosen folder"
    $info = Api GET "/api/system/app"
    Check ($info.installed -and $info.uninstall_available) "System page offers Uninstall"
    Check ($info.install_dir.TrimEnd("\") -eq $script:App) "install folder: $($info.install_dir)"
    Api PATCH "/api/system/app" @{ autostart = $true } | Out-Null
    $run = (Get-ItemProperty $RunKey -Name Obscura -ErrorAction SilentlyContinue).Obscura
    Check ($run -like "*pythonw.exe*obscura_launch.pyw*--background") "start at login registered: $run"

    Step "analyze and export a PDF (text page + scanned page)"
    $makePdf = Join-Path $LogDir "make_pdf.py"
    Set-Content -Encoding ascii $makePdf @'
import sys, fitz
d = fitz.open()
p = d.new_page()
p.insert_text((72, 96), "Patient: Maria Delgado\nSSN: 523-71-9921\nPhone: (512) 555-0187", fontsize=13)
pix = p.get_pixmap(dpi=200)   # a picture of the page, which only OCR can read (taken first: new_page invalidates p)
scan = d.new_page()
scan.insert_image(scan.rect, pixmap=pix)
d.save(sys.argv[1])
'@
    $pdf = Join-Path $LogDir "smoke.pdf"
    & "$($script:App)\runtime\python.exe" $makePdf $pdf
    Check ($LASTEXITCODE -eq 0 -and (Test-Path $pdf)) "test PDF made with the installed PyMuPDF"
    $case = Api POST "/api/cases" @{ name = "Windows smoke test" }
    $up = & curl.exe -sS -f -H "Authorization: $($script:Auth.Authorization)" -F "files=@$pdf;type=application/pdf" "$($script:Base)/api/cases/$($case.id)/files" | ConvertFrom-Json
    Check (@($up.files).Count -eq 1 -and @($up.errors).Count -eq 0) "PDF uploaded"
    $fid = $up.files[0].id
    # the program-only installer has no AI models until the setup assistant imports or downloads them, so analyze with
    # the rules, OCR and the spaCy second opinion only; the full installer uses everything
    $useMl = Test-Path "$($script:App)\models\gliner"
    $analyze = if ($useMl) { @{} } else { @{ use_ml = $false; visual_on_pages = $false; classify_images = $false } }
    $job = Api POST "/api/files/$fid/analyze" $analyze
    $j = Wait-ObscuraJob $job.job_id "analysis (AI models: $useMl)"
    Check ($j.result.ocr_pages -ge 1) "scanned page was read with OCR ($($j.result.ocr_pages) page)"
    $ssn = @((Api GET "/api/files/$fid/detections").detections | Where-Object entity -eq "SSN")
    Check (@($ssn | Where-Object page -eq 0).Count -ge 1) "SSN found on the text page"
    Check (@($ssn | Where-Object page -eq 1).Count -ge 1) "SSN found on the scanned page"
    $job = Api POST "/api/files/$fid/export" @{}
    $j = Wait-ObscuraJob $job.job_id "export"
    Check $j.result.verified "export passed Obscura's own verification"
    $out = Join-Path $LogDir "smoke-redacted.pdf"
    Invoke-WebRequest -UseBasicParsing -Headers $script:Auth "$($script:Base)/api/exports/$($j.result.export_id)/download" -OutFile $out
    $checkPdf = Join-Path $LogDir "check_pdf.py"
    Set-Content -Encoding ascii $checkPdf @'
import os, subprocess, sys, tempfile, fitz
tess = os.path.join(sys.argv[2], "tesseract.exe")
env = dict(os.environ, TESSDATA_PREFIX=os.path.join(sys.argv[2], "tessdata"))
leaks = []
for i, page in enumerate(fitz.open(sys.argv[1])):
    png = os.path.join(tempfile.gettempdir(), "obscura-smoke-%d.png" % i)
    page.get_pixmap(dpi=200).save(png)
    ocr = subprocess.run([tess, png, "stdout"], capture_output=True, text=True, env=env).stdout
    if "523-71-9921" in page.get_text() + ocr:
        leaks.append(i + 1)
print("pages with the SSN still readable:", leaks)
sys.exit(1 if leaks else 0)
'@
    & "$($script:App)\runtime\python.exe" $checkPdf $out "$($script:App)\tesseract"
    Check ($LASTEXITCODE -eq 0) "SSN is gone from both pages of the export (text and OCR)"

    Save-Logs "run1"
    Step "uninstall from Settings > Apps while Obscura runs (keeps the case files)"
    $uninst = (Get-ItemProperty $UninstallKey).UninstallString.Trim('"')
    Start-Process $uninst -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$LogDir\uninstall-1.log`"" -Wait
    Wait-Until { -not (Test-Path $UninstallKey) } 300 "removed from Settings > Apps"
    Wait-Until { (Obscura-Processes $script:App).Count -eq 0 } 60 "Obscura was stopped"
    Wait-Until { -not (Test-Path "$($script:App)\runtime") } 120 "program files removed"
    Check (-not (Test-Path "$StartMenu\Obscura.lnk")) "Start menu shortcut removed"
    Check (-not (Get-ItemProperty $RunKey -Name Obscura -ErrorAction SilentlyContinue)) "start at login removed"
    Check (Test-Path "$AppHome\config.json") "settings kept"
    Check (Test-Path (Join-Path $DataDir "obscura.db")) "case database kept"
    Check (Test-Path (Join-Path $DataDir "keys")) "encryption keys kept"

    Install-Obscura 2
    Start-Obscura
    Check (-not (Api GET "/api/setup/state").needed) "reinstall reuses the settings (no setup assistant)"
    Sign-In
    $cases = Api GET "/api/cases"
    Check (@($cases | ForEach-Object { $_ } | Where-Object name -eq "Windows smoke test").Count -eq 1) "reinstall finds the case files again"

    Save-Logs "run2"
    Step "uninstall from inside Obscura (System > Uninstall), deleting the case files"
    $r = Api POST "/api/system/uninstall" @{ confirm = "UNINSTALL"; remove_data = $true }
    Check $r.ok "uninstall started by Obscura"
    Wait-Until { -not (Test-Path $UninstallKey) } 300 "removed from Settings > Apps"
    Wait-Until { (Obscura-Processes $script:App).Count -eq 0 } 60 "Obscura stopped"
    Wait-Until { -not (Test-Path "$($script:App)\runtime") } 120 "program files removed"
    Wait-Until { -not (Test-Path $DataDir) } 60 "case files deleted (folder with an accented and a Chinese name)"
    Check (-not (Test-Path $AppHome)) "settings folder deleted"
    $failed = $false
    Step "all checks passed"
} finally {
    if ($failed) {
        Save-Logs "failed"
        Write-Host "`nLogs: $LogDir" -ForegroundColor Yellow
        Get-ChildItem $LogDir -Filter "*launcher.log" | ForEach-Object { Write-Host "--- $($_.Name)"; Get-Content $_.FullName -Tail 40 }
        Get-ChildItem $LogDir -Filter "*server.log" | ForEach-Object { Write-Host "--- $($_.Name)"; Get-Content $_.FullName -Tail 60 }
        if (Test-Path "$LogDir\Obscura-uninstall.log") {
            Write-Host "--- Obscura-uninstall.log (Obscura lines)"
            Get-Content "$LogDir\Obscura-uninstall.log" | Where-Object { $_ -match "Obscura|case folder|Deleting|DelTree|Error|error" } | Select-Object -Last 40 | Write-Host
        }
        Write-Host "--- settings folder still there: $(Test-Path $AppHome)"
        if (Test-Path -LiteralPath $DataDir) {
            Write-Host "--- still in the case folder:"
            Get-ChildItem -LiteralPath $DataDir -Recurse -Force | ForEach-Object { Write-Host ("  {0,-22} {1}" -f $_.Attributes, $_.FullName.Substring($DataDir.Length)) }
        }
        # leave the machine clean
        if (Test-Path $UninstallKey) {
            $u = (Get-ItemProperty $UninstallKey).UninstallString.Trim('"')
            Start-Process $u -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/REMOVEDATA=1" -Wait
        }
    }
}
