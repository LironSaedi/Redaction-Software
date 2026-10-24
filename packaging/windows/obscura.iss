; Obscura Redaction Studio — Windows installer (Inno Setup 6). Built by build_windows.ps1, which passes:
;   /DAppVersion=1.0.0  /DStage=<staged files>  /DSuffix=""|"-full"  /DSpanning=no|yes  /DOutDir=<dist folder>
;
; Installs for the current user by default (no administrator password; %LOCALAPPDATA%\Programs\Obscura) or, if the
; user chooses, for everyone (Program Files). Registers "Obscura Redaction Studio" in Settings › Apps for uninstall.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Stage
  #define Stage "..\..\build\windows\stage"
#endif
#ifndef Suffix
  #define Suffix ""
#endif
#ifndef Spanning
  #define Spanning "no"
#endif
#ifndef OutDir
  #define OutDir "..\..\dist"
#endif
#define AppName "Obscura Redaction Studio"

[Setup]
AppId={{8F3C2B71-4E5A-4C1E-9B7D-0B1A6F2E9C44}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Obscura
DefaultDirName={autopf}\Obscura
DefaultGroupName=Obscura
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
WizardSizePercent=110
SetupIconFile={#Stage}\obscura.ico
UninstallDisplayIcon={app}\obscura.ico
UninstallDisplayName={#AppName}
LicenseFile=license.txt
InfoBeforeFile=welcome.txt
OutputDir={#OutDir}
OutputBaseFilename=Obscura-{#AppVersion}-Windows{#Suffix}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
; compress in a separate 64-bit process: several GB of input is more than the 32-bit compiler can hold in memory
LZMAUseSeparateProcess=yes
DiskSpanning={#Spanning}
DiskSliceSize=max
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; start at login is offered by the setup assistant in the browser (as on macOS), which also owns the Run entry
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[InstallDelete]
; an update replaces the program completely, so no module from the previous version is left behind
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\tesseract"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Obscura"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\obscura_launch.pyw"""; WorkingDir: "{app}\app"; IconFilename: "{app}\obscura.ico"; AppUserModelID: "Obscura.RedactionStudio"
Name: "{group}\Uninstall Obscura"; Filename: "{uninstallexe}"; IconFilename: "{app}\obscura.ico"
Name: "{autodesktop}\Obscura"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\obscura_launch.pyw"""; WorkingDir: "{app}\app"; IconFilename: "{app}\obscura.ico"; AppUserModelID: "Obscura.RedactionStudio"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\app\obscura_launch.pyw"""; WorkingDir: "{app}\app"; Description: "Open Obscura now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; byte-code caches and logs written next to the program
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"

[Code]
function AppHome(): String;
begin
  Result := ExpandConstant('{localappdata}\Obscura');
end;

{ the text of the JSON string that starts at S[1] (just after its opening quote), with \\, \" and \uXXXX decoded;
  '' if the string does not end on this line or holds a character above U+00FF, which Pascal Script's Chr() cannot
  make (it keeps 8 bits: \u6570 would come out as "p") }
function JsonText(S: String): String;
var
  I, Code: Integer;
  C: Char;
begin
  Result := '';
  I := 1;
  while I <= Length(S) do
  begin
    C := S[I];
    if C = '"' then
      Exit;
    if (C = '\') and (I < Length(S)) then
    begin
      I := I + 1;
      C := S[I];
      if (C = 'u') and (I + 4 <= Length(S)) then
      begin
        Code := StrToIntDef('$' + Copy(S, I + 1, 4), -1);
        if (Code < 0) or (Code > 255) then
          Break;
        C := Chr(Code);
        I := I + 4;
      end;
    end;
    Result := Result + C;
    I := I + 1;
  end;
  Result := '';
end;

function PsQuote(S: String): String;
begin
  StringChangeEx(S, '''', '''''', True);
  Result := '''' + S + '''';
end;

{ data_dir from %LOCALAPPDATA%\Obscura\config.json. Python writes letters outside ASCII as \uXXXX (user names, folder
  names in any language), so PowerShell's JSON reader decodes it. Without PowerShell only names up to U+00FF are
  understood; anything else counts as unknown, and then the folder is not deleted. }
function DataDir(): String;
var
  Lines: TArrayOfString;
  Cfg, Tmp: String;
  I, P, Code: Integer;
begin
  Result := AppHome() + '\data';
  Cfg := AppHome() + '\config.json';
  if not FileExists(Cfg) then
    Exit;
  Tmp := ExpandConstant('{tmp}\obscura-data-dir.txt');
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$c = Get-Content -Raw -Encoding UTF8 -LiteralPath ' +
          PsQuote(Cfg) + ' | ConvertFrom-Json; [IO.File]::WriteAllText(' + PsQuote(Tmp) +
          ', [string]$c.data_dir, (New-Object System.Text.UTF8Encoding $true))"', '', SW_HIDE, ewWaitUntilTerminated, Code)
     and (Code = 0) and LoadStringsFromFile(Tmp, Lines) then
  begin
    if (GetArrayLength(Lines) > 0) and (Trim(Lines[0]) <> '') then
      Result := Trim(Lines[0]);
    Exit;
  end;
  if LoadStringsFromFile(Cfg, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      P := Pos('"data_dir": "', Lines[I]);
      if P > 0 then
        Result := JsonText(Copy(Lines[I], P + 13, Length(Lines[I])));   { '' when unreadable: never guess }
    end;
end;

{ S if it is a process id (digits only), otherwise '' }
function PidText(S: String): String;
var
  I: Integer;
begin
  Result := S;
  for I := 1 to Length(S) do
    if (S[I] < '0') or (S[I] > '9') then
    begin
      Result := '';
      Exit;
    end;
end;

{ fallback when PowerShell is unavailable: the launcher and server ids recorded in running.json. Only Python processes
  are ended, because a file left behind by a crash may hold ids that Windows has since given to other programs. }
procedure StopFromPidFile();
var
  Lines: TArrayOfString;
  I, P, Code: Integer;
  S, Pid: String;
begin
  if not LoadStringsFromFile(AppHome() + '\running.json', Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    S := Lines[I];
    P := Pos('_pid": ', S);
    while P > 0 do
    begin
      S := Copy(S, P + 7, Length(S));
      Pid := '';
      while (Length(S) > 0) and (S[1] >= '0') and (S[1] <= '9') do
      begin
        Pid := Pid + S[1];
        S := Copy(S, 2, Length(S));
      end;
      if Pid <> '' then
      begin
        Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM pythonw.exe /FI "PID eq ' + Pid + '"', '', SW_HIDE,
             ewWaitUntilTerminated, Code);
        Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM python.exe /FI "PID eq ' + Pid + '"', '', SW_HIDE,
             ewWaitUntilTerminated, Code);
      end;
      P := Pos('_pid": ', S);
    end;
  end;
end;

{ Stop Obscura before its files are replaced or removed. When the app started this uninstall (/WAITPID=<launcher>),
  give it up to 30 s to quit by itself; then end every process still running from the program's runtime and OCR
  folders (launcher, server, transcription worker, ffmpeg, tesseract). This never ends the uninstaller, which runs
  from %TEMP% and may be a child of the server, so no process-tree kill is used. }
function StopScript(AppDir, WaitPid: String): String;
begin
  StringChangeEx(AppDir, '''', '''''', True);
  Result := '$ErrorActionPreference = ''SilentlyContinue''; ';
  if PidText(WaitPid) <> '' then
    Result := Result + 'Wait-Process -Id ' + WaitPid + ' -Timeout 30; ';
  Result := Result + '$r = ''' + AppDir + '\''; ' +
    'Get-CimInstance Win32_Process | Where-Object { $p = $_.ExecutablePath; $p -and (' +
    '$p.StartsWith($r + ''runtime\'', ''OrdinalIgnoreCase'') -or ' +
    '$p.StartsWith($r + ''tesseract\'', ''OrdinalIgnoreCase'')) } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force }';
end;

procedure StopObscura();
var
  Code: Integer;
begin
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
              StopScript(ExpandConstant('{app}'), ExpandConstant('{param:WAITPID|}')) + '"', '', SW_HIDE,
              ewWaitUntilTerminated, Code) or (Code <> 0) then
    StopFromPidFile();
  DeleteFile(AppHome() + '\running.json');
end;

function LooksLikeObscuraData(Dir: String): Boolean;
begin
  Result := (Length(Dir) > 3) and (FileExists(Dir + '\obscura.db') or DirExists(Dir + '\keys') or DirExists(Dir + '\blobs'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopObscura();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RemoveData: Boolean;
  Data: String;
begin
  { usUninstall comes after the "remove Obscura?" confirmation and before any file is removed }
  if CurUninstallStep = usUninstall then
    StopObscura();
  if CurUninstallStep <> usPostUninstall then Exit;
  RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Obscura');
  Data := DataDir();
  { /REMOVEDATA=1 comes from the app's own Uninstall button (it already asked) }
  if ExpandConstant('{param:REMOVEDATA|ask}') = '1' then
    RemoveData := True
  else if ExpandConstant('{param:REMOVEDATA|ask}') = '0' then
    RemoveData := False
  else
    RemoveData := (not UninstallSilent()) and
      (MsgBox('Also permanently delete all Obscura case files, exports, the audit log and settings?' + #13#10 + #13#10 +
              Data + #13#10 + #13#10 + 'Choose No to keep them (a reinstall will find them again).',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES);
  Log('Obscura case folder: ' + Data + '; delete it: ' + IntToStr(Ord(RemoveData)));
  if RemoveData then
  begin
    if LooksLikeObscuraData(Data) then
    begin
      DelTree(Data + '\keys', True, True, True);   { keys first: anything left can no longer be decrypted }
      if not DelTree(Data, True, True, True) then
      begin
        Log('Case folder not fully deleted, trying again in 3 s');
        Sleep(3000);
        DelTree(Data, True, True, True);
      end;
      if DirExists(Data) then
        Log('Case folder could not be deleted completely: ' + Data);
    end
    else
      Log('Not deleted: no obscura.db, keys or blobs in ' + Data);
    DelTree(AppHome(), True, True, True);
  end
  else
    DelTree(AppHome() + '\models', True, True, True);   { downloaded models go with the program }
end;
