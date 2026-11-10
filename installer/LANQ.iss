#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

[Setup]
AppId=LANQ.ClassroomQuizConsole
AppName=LANQ
AppVersion={#AppVersion}
AppPublisher=LANQ
DefaultDirName={commonappdata}\LANQ\app
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=LANQ
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
CloseApplicationsFilter=LANQ.exe
RestartApplications=no
UninstallDisplayIcon={app}\LANQ.exe
OutputDir=..\dist\installer
OutputBaseFilename=LANQ-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Dirs]
Name: "{commonappdata}\LANQ\data"; Flags: uninsneveruninstall

[Files]
Source: "..\dist\LANQ.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\LANQ"; Filename: "{app}\LANQ.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\LANQ.exe"; Description: "Launch LANQ"; Flags: postinstall nowait skipifsilent unchecked

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LANQ.ClassroomQuizConsole_is1';

var
  AccountPage: TInputQueryWizardPage;
  ImportDatabasePage: TInputFileWizardPage;
  UseSelectedImport: Boolean;
  RemoveDataOnUninstall: Boolean;

function DataDirectory: String;
begin
  Result := ExpandConstant('{commonappdata}\LANQ\data');
end;

function DatabasePath: String;
begin
  Result := DataDirectory + '\lanq.db';
end;

function SelectedImportPath: String;
begin
  Result := Trim(ImportDatabasePage.Values[0]);
end;

function DataAccount: String;
begin
  Result := Trim(AccountPage.Values[0]);
end;

function IsBroadDataAccount(const Value: String): Boolean;
var
  Normalized: String;
begin
  Normalized := LowerCase(Trim(Value));
  Result := (Normalized = 'everyone') or
    (Normalized = 'users') or
    (Normalized = 'builtin\users') or
    (Normalized = 'authenticated users') or
    (Normalized = 'nt authority\authenticated users') or
    (Normalized = 'administrators') or
    (Normalized = 'builtin\administrators') or
    (Normalized = 'admins') or
    (Normalized = 'guests') or
    (Normalized = 'creator owner') or
    (Normalized = 'system') or
    (Normalized = 'nt authority\system') or
    (Normalized = 'local service') or
    (Normalized = 'network service');
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if RegKeyExists(HKLM, UninstallKey) then
    Result := MsgBox(
      'A LANQ installation was found. Update that installation and keep its data?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDYES;
end;

procedure InitializeWizard;
begin
  AccountPage := CreateInputQueryPage(
    wpWelcome,
    'LANQ data access',
    'Choose the Windows account that can access LANQ data.',
    'Administrators and SYSTEM will also retain full access. For a domain account, enter DOMAIN\account.');
  AccountPage.Add('&Windows account:', False);
  AccountPage.Values[0] := ExpandConstant('{username}');

  ImportDatabasePage := CreateInputFilePage(
    AccountPage.ID,
    'Import an existing database',
    'Optionally select a database from an older standalone LANQ executable.',
    'Leave this blank for a new installation. LANQ must be closed before importing its database.');
  ImportDatabasePage.Add(
    '&Existing lanq.db (optional):',
    'LANQ database (*.db)|*.db|All files (*.*)|*.*',
    'db');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  SelectedPath: String;
  ExistingPath: String;
  Choice: Integer;
begin
  Result := True;

  if CurPageID = AccountPage.ID then begin
    if (DataAccount = '') or (Pos('"', DataAccount) > 0) or
       (Pos(#13, DataAccount) > 0) or (Pos(#10, DataAccount) > 0) or
       IsBroadDataAccount(DataAccount) then begin
      MsgBox('Enter an individual Windows user account, not a group, for LANQ data access.', mbError, MB_OK);
      Result := False;
    end;
  end;

  if (CurPageID = ImportDatabasePage.ID) and Result then begin
    SelectedPath := SelectedImportPath;
    ExistingPath := DatabasePath;
    UseSelectedImport := SelectedPath <> '';

    if UseSelectedImport and not FileExists(SelectedPath) then begin
      MsgBox('The selected database file no longer exists.', mbError, MB_OK);
      Result := False;
    end else if UseSelectedImport and FileExists(ExistingPath) and
        (CompareText(SelectedPath, ExistingPath) <> 0) then begin
      Choice := MsgBox(
        'A LANQ database already exists in ProgramData.' + #13#10 + #13#10 +
        'Yes: keep the ProgramData database.' + #13#10 +
        'No: back it up, then replace it with the selected database.' + #13#10 +
        'Cancel: stop setup.',
        mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON1);
      if Choice = IDYES then
        UseSelectedImport := False
      else if Choice = IDNO then
        UseSelectedImport := True
      else
        Result := False;
    end;
  end;
end;

function RunIcacls(const Parameters: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(
    ExpandConstant('{sys}\icacls.exe'), Parameters, '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function SetDataPermissions: Boolean;
var
  DirectoryArgument: String;
  GrantArguments: String;
begin
  DirectoryArgument := AddQuotes(DataDirectory);
  Result := RunIcacls(DirectoryArgument + ' /reset /T');
  if not Result then
    Exit;

  GrantArguments := DirectoryArgument + ' /grant:r ' +
    AddQuotes(DataAccount + ':(OI)(CI)M') + ' ' +
    AddQuotes('*S-1-5-18:(OI)(CI)F') + ' ' +
    AddQuotes('*S-1-5-32-544:(OI)(CI)F') + ' /T';
  Result := RunIcacls(GrantArguments);
  if not Result then
    Exit;

  Result := RunIcacls(DirectoryArgument + ' /inheritance:r /T');
end;

function UniqueBackupPath(const ExistingDatabase: String): String;
var
  Suffix: String;
  Counter: Integer;
begin
  Suffix := GetDateTimeString('yyyymmddhhnnss', '', '');
  Result := ExistingDatabase + '.' + Suffix + '.bak';
  Counter := 1;
  while FileExists(Result) do begin
    Result := ExistingDatabase + '.' + Suffix + '-' + IntToStr(Counter) + '.bak';
    Counter := Counter + 1;
  end;
end;

procedure PrepareDataFiles;
var
  ExistingDatabase: String;
  BackupDatabase: String;
begin
  if not ForceDirectories(DataDirectory) then
    RaiseException('LANQ could not create its ProgramData data directory.');

  if not SetDataPermissions then
    RaiseException('LANQ could not secure the data directory for the selected Windows account.');

  ExistingDatabase := DatabasePath;
  if FileExists(ExistingDatabase) then begin
    BackupDatabase := UniqueBackupPath(ExistingDatabase);
    if not CopyFile(ExistingDatabase, BackupDatabase, True) then
      RaiseException('LANQ could not back up its existing database. The update was stopped.');
  end;

  if UseSelectedImport and
      not CopyFile(SelectedImportPath, ExistingDatabase, False) then
    RaiseException('LANQ could not import the selected database. The original file was left unchanged.');

  if UseSelectedImport and not SetDataPermissions then
    RaiseException('LANQ imported the database but could not secure its permissions. Do not launch LANQ until this is fixed.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    PrepareDataFiles;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  RemoveDataOnUninstall := False;
  if DirExists(DataDirectory) then
    RemoveDataOnUninstall := MsgBox(
      'Also delete the LANQ database and its backups? Choose No to keep them.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveDataOnUninstall then
    if not DelTree(DataDirectory, True, True, True) then
      MsgBox('LANQ was uninstalled, but some application data could not be removed.', mbError, MB_OK);
end;