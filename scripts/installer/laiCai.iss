; 来财 (LaiCai) — Windows 原生安装包脚本 (Inno Setup)
; 安装后自动生成 config/ths.json 并检测同花顺路径

#define MyAppName "来财 (LaiCai)"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Btnalit"
#define MyAppURL "https://github.com/btnalit/Attract-wealth"
#define MyAppExeName "laiCai.exe"
#define MyAppAssocName "LaiCai"
#define MyAppAssocExt ".lc"

[Setup]
AppId={{F7A8B2C1-4D6E-4F8A-9B1C-2E3D4A5F6B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\LaiCai
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist\installer
OutputBaseFilename=laiCai-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
Source: "..\..\dist\laiCai\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\laiCai\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// 同花顺路径检测函数
function DetectTHSInstallPath(): String;
var
  RegPath: String;
  ResultStr: String;
  I: Integer;
  CommonPaths: array of String;
begin
  Result := '';

  // 1. 尝试从注册表读取
  if RegValueExists(HKCU, 'Software\THS', 'installpath') then begin
    RegQueryStringValue(HKCU, 'Software\THS', 'installpath', ResultStr);
    if DirExists(ResultStr) and FileExists(ResultStr + '\xiadan.exe') then begin
      Result := ResultStr;
      Exit;
    end;
  end;

  // 2. 扫描常见安装路径
  SetArrayLength(CommonPaths, 5);
  CommonPaths[0] := 'C:\同花顺软件\同花顺';
  CommonPaths[1] := 'D:\同花顺软件\同花顺';
  CommonPaths[2] := 'C:\Program Files (x86)\同花顺软件\同花顺';
  CommonPaths[3] := 'C:\Program Files\同花顺软件\同花顺';
  CommonPaths[4] := 'D:\ths';

  for I := 0 to GetArrayLength(CommonPaths) - 1 do begin
    if DirExists(CommonPaths[I]) and FileExists(CommonPaths[I] + '\xiadan.exe') then begin
      Result := CommonPaths[I];
      Exit;
    end;
  end;
end;

// 安装后生成 THS 配置文件
procedure CreateTHSConfig();
var
  THSPath: String;
  ConfigContent: String;
  ConfigDir: String;
begin
  THSPath := DetectTHSInstallPath();
  ConfigDir := ExpandConstant('{app}\config');

  if not DirExists(ConfigDir, False) then
    CreateDir(ConfigDir);

  ConfigContent := '{' + #13#10 +
    '  "manual_path": "' + THSPath + '",' + #13#10 +
    '  "exe_path": "' + THSPath + '\xiadan.exe",' + #13#10 +
    '  "auto_detect": true,' + #13#10 +
    '  "last_updated": ' + IntToStr(GetUnixTime()) + #13#10 +
    '}';

  SaveStringToFile(ConfigDir + '\ths.json', ConfigContent, False);
end;

// 安装完成后调用
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    CreateTHSConfig();
  end;
end;

// 安装向导页面：显示检测到的 THS 路径
var
  THSPathPage: TWizardPage;
  THSPathLabel: TNewStaticText;
  THSPathValue: TEdit;

procedure InitializeWizard();
begin
  THSPath := DetectTHSInstallPath();

  THSPathPage := CreateCustomPage(wpSelectDir, '同花顺检测', '检测到同花顺安装路径，如需修改请手动编辑。');
  THSPathLabel := TNewStaticText.Create(THSPathPage);
  THSPathLabel.Parent := THSPathPage.Surface;
  THSPathLabel.Caption := '检测到同花顺安装路径:';
  THSPathLabel.Top := 10;
  THSPathLabel.Left := 0;
  THSPathLabel.Width := 400;

  THSPathValue := TEdit.Create(THSPathPage);
  THSPathValue.Parent := THSPathPage.Surface;
  THSPathValue.Text := THSPath;
  THSPathValue.Top := 30;
  THSPathValue.Left := 0;
  THSPathValue.Width := 400;
  THSPathValue.Enabled := True;
end;
