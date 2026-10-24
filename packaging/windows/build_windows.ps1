<#
Build the Obscura installer for Windows 10/11 (x64): Obscura-<version>-Windows.exe (Inno Setup wizard).

    powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1              # program only
    powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1 -WithModels  # complete offline installer

Needs (on the build machine only): uv, Node.js (to build the web interface), Inno Setup 6 (ISCC.exe) and internet
access for the Python packages and the Tesseract OCR installer. 7-Zip is used to unpack Tesseract when present
(otherwise its installer runs silently into the staging folder). The finished installer needs no internet.
Optional: -TesseractInstaller C:\path\tesseract-ocr-w64-setup-5.x.exe to use an installer you already have,
          -SignTool "signtool sign /fd sha256 /a /tr http://timestamp.digicert.com /td sha256" to sign the output.
Check the result on a test PC (or in the installers workflow) with packaging\windows\smoke_test.ps1.
#>
param(
    [switch]$WithModels,
    [string]$TesseractInstaller = "",
    [string]$TesseractUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe",
    [string]$SignTool = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Windows PowerShell downloads many times slower with the progress bar
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Build = Join-Path $Root "build\windows"
$Stage = Join-Path $Build "stage"
$Dist = Join-Path $Root "dist"
# (Select-String, not Get-Content -match: a one-line file makes -match return True instead of the line)
$Version = (Select-String -Path "$Root\backend\obscura\__init__.py" -Pattern '^__version__\s*=\s*"([^"]+)"').Matches |
    Select-Object -First 1 | ForEach-Object { $_.Groups[1].Value }
if (-not $Version) { throw "no __version__ in backend\obscura\__init__.py" }
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Robo($src, $dst, [string[]]$extra) {
    robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $src -> $dst" }
    $global:LASTEXITCODE = 0
}

Step "Obscura $Version for Windows (models included: $WithModels)"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force $Stage, $Dist | Out-Null

# ---- 1. Python runtime (relocatable CPython from python-build-standalone, via uv) ---------------------------------
Step "Python runtime"
uv python install 3.12
if ($LASTEXITCODE) { throw "uv python install failed" }
$py = (uv python find --managed-python 3.12).Trim()
$pyHome = Split-Path $py
if (-not (Test-Path "$pyHome\python312.dll") -or -not (Test-Path "$pyHome\pythonw.exe")) {
    throw "need a python-build-standalone 3.12 (uv python install 3.12), found $py"
}
Robo $pyHome "$Stage\runtime" @()
Remove-Item -Force "$Stage\runtime\Lib\EXTERNALLY-MANAGED" -ErrorAction SilentlyContinue
# (written without a byte-order mark, which Windows PowerShell's Set-Content -Encoding utf8 would add)
$req = Get-Content -Encoding UTF8 "$Root\backend\requirements.txt" | Where-Object { $_ -notmatch '^(pytest|faker)==' }
[IO.File]::WriteAllLines("$Build\requirements-runtime.txt", [string[]]$req)
Copy-Item "$Root\backend\requirements-exclude.txt" "$Build\requirements-exclude.txt"
Step "Python packages"
# (uv splits an --excludes path at spaces, so it is passed relative to the build folder)
Push-Location $Build
uv pip install --python "$Stage\runtime\python.exe" --compile-bytecode -r requirements-runtime.txt --excludes requirements-exclude.txt
if ($LASTEXITCODE) { throw "package install failed" }
uv pip install --python "$Stage\runtime\python.exe" "https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl"
if ($LASTEXITCODE) { throw "spaCy model install failed" }
Pop-Location
& "$Stage\runtime\python.exe" -c "import fastapi, torch, spacy, gliner, fitz, presidio_analyzer, en_core_web_trf, tkinter"
if ($LASTEXITCODE) { throw "runtime is incomplete" }
foreach ($d in "Lib\test", "Lib\idlelib") { Remove-Item -Recurse -Force "$Stage\runtime\$d" -ErrorAction SilentlyContinue }

# PyTorch and other packages need the Microsoft C++ runtime (msvcp140.dll ...), which a fresh Windows does not always
# have. Ship it next to python.exe (app-local deployment), so no administrator has to install the VC++ Redistributable.
Step "Microsoft C++ runtime"
$crt = $null
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -products * -property installationPath
    if ($vs) {
        $crt = Get-ChildItem "$vs\VC\Redist\MSVC\*\x64\Microsoft.VC14*.CRT" -Directory -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
    }
}
if ($crt) {
    Write-Host "  from $($crt.FullName)"
    Robo $crt.FullName "$Stage\runtime" @("/XO")
} else {
    Write-Warning "Visual Studio's redistributable folder was not found; copying the C++ runtime installed in System32"
    foreach ($dll in "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll") {
        if (-not (Test-Path "$Stage\runtime\$dll") -and (Test-Path "$env:SystemRoot\System32\$dll")) {
            Copy-Item "$env:SystemRoot\System32\$dll" "$Stage\runtime\"
        }
    }
}
if (-not (Test-Path "$Stage\runtime\msvcp140.dll")) { throw "msvcp140.dll is missing from the runtime" }

# ---- 2. Obscura -----------------------------------------------------------------------------------------------------
Step "application files"
Robo "$Root\backend\obscura" "$Stage\app\obscura" @("/XD", "__pycache__", "/XF", "*.pyc")
New-Item -ItemType Directory -Force "$Stage\app\scripts" | Out-Null
Copy-Item "$Root\backend\scripts\download_models.py", "$Root\backend\scripts\make_cert.sh" "$Stage\app\scripts\"
Copy-Item "$Root\backend\obscura_launch.pyw" "$Stage\app\"
if (-not (Test-Path "$Root\frontend\dist\index.html")) {
    Push-Location "$Root\frontend"
    npm ci
    if ($LASTEXITCODE) { throw "npm ci failed" }
    npm run build
    if ($LASTEXITCODE) { throw "web interface build failed" }
    Pop-Location
}
Robo "$Root\frontend\dist" "$Stage\app\frontend" @()
& "$Stage\runtime\python.exe" -m compileall -q "$Stage\app\obscura"
if ($LASTEXITCODE) { throw "compileall failed" }

Step "OCR engine (Tesseract)"
if (-not $TesseractInstaller) {
    $TesseractInstaller = Join-Path $Build "tesseract-setup.exe"
    if (-not (Test-Path $TesseractInstaller)) { Invoke-WebRequest -UseBasicParsing -Uri $TesseractUrl -OutFile $TesseractInstaller }
}
$sig = Get-AuthenticodeSignature $TesseractInstaller
Write-Host "  Tesseract installer: $(Split-Path $TesseractInstaller -Leaf)  sha256 $((Get-FileHash $TesseractInstaller).Hash)  signature: $($sig.Status)"
$sevenZip = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($sevenZip) {
    # unpack the NSIS installer without running it: nothing is installed or registered on the build machine
    & $sevenZip x -y "-o$Stage\tesseract" $TesseractInstaller | Out-Null
    if ($LASTEXITCODE -ge 2) { throw "Tesseract extraction failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
} else {
    # NSIS silent install into the staging folder (asks for administrator rights and registers an uninstall entry)
    $p = Start-Process -FilePath $TesseractInstaller -ArgumentList "/S", "/D=$Stage\tesseract" -Wait -PassThru
    if ($p.ExitCode) { throw "Tesseract extraction failed ($($p.ExitCode))" }
}
# keep the OCR engine with its English and script-detection data; drop the training tools, the Java viewer and the
# installer's own files
Remove-Item -Recurse -Force (Join-Path $Stage 'tesseract\$PLUGINSDIR') -ErrorAction SilentlyContinue
Get-ChildItem "$Stage\tesseract\*.exe" | Where-Object { $_.Name -ne "tesseract.exe" } | Remove-Item -Force
Get-ChildItem "$Stage\tesseract" -Recurse -Include "*.html", "*.jar" | Remove-Item -Force
Get-ChildItem "$Stage\tesseract\tessdata\*.traineddata" | Where-Object { $_.Name -notin "eng.traineddata", "osd.traineddata" } | Remove-Item
& "$Stage\tesseract\tesseract.exe" --version | Select-Object -First 1
if ($LASTEXITCODE) { throw "the bundled tesseract.exe does not run" }

if ($WithModels) {
    Step "AI models"
    foreach ($part in "gliner\nvidia-gliner-pii", "vision", "whisper\medium.en", "whisper\small.en", "whisper\small", "translate\m2m100_418m", "speaker") {
        if (-not (Test-Path "$Root\backend\models\$part")) { throw "missing model $part - run backend\scripts\download_models.py" }
        Robo "$Root\backend\models\$part" "$Stage\models\$part" @()
    }
}

Step "licences and icon"
New-Item -ItemType Directory -Force "$Stage\licenses" | Out-Null
Get-ChildItem "$Stage\runtime\Lib\site-packages\*.dist-info" -Directory | ForEach-Object {
    $pkg = $_.Name -replace '\.dist-info$', ''
    Get-ChildItem $_.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICEN[CS]E|COPYING|NOTICE)' -or $_.DirectoryName -match 'licenses$' } |
        ForEach-Object { Copy-Item $_.FullName "$Stage\licenses\$pkg-$($_.Name)" }
}
Copy-Item "$Stage\runtime\LICENSE.txt" "$Stage\licenses\Python-LICENSE.txt" -ErrorAction SilentlyContinue
Copy-Item "$Stage\tesseract\doc\LICENSE" "$Stage\licenses\Tesseract-LICENSE.txt" -ErrorAction SilentlyContinue
& "$Stage\runtime\python.exe" "$Root\packaging\common\make_icons.py" "$Build\icons" | Out-Null
if ($LASTEXITCODE) { throw "icon generation failed" }
Copy-Item "$Build\icons\obscura.ico" "$Stage\obscura.ico"

# ---- 3. installer ---------------------------------------------------------------------------------------------------
Step "installer"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
$suffix = if ($WithModels) { "-full" } else { "" }
$span = if ($WithModels) { "yes" } else { "no" }   # the full installer is larger than one file can hold
$base = "Obscura-$Version-Windows$suffix"
$isOut = { Get-ChildItem $Dist -File | Where-Object { $_.Name -eq "$base.exe" -or $_.Name -like "$base-*.bin" } }
& $isOut | Remove-Item -Force   # parts of an older build must not mix with this one
& $iscc /Qp "/DAppVersion=$Version" "/DStage=$Stage" "/DSuffix=$suffix" "/DSpanning=$span" "/DOutDir=$Dist" "$PSScriptRoot\obscura.iss"
if ($LASTEXITCODE) { throw "Inno Setup failed" }
$out = & $isOut | Sort-Object Name
if ($SignTool) { foreach ($f in $out | Where-Object Extension -eq ".exe") { Invoke-Expression "$SignTool `"$($f.FullName)`"" } }
Step "done"
$out | ForEach-Object { "{0}  {1:N0} MB  sha256 {2}" -f $_.Name, ($_.Length / 1MB), (Get-FileHash $_.FullName).Hash }
