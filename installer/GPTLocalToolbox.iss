#define MyAppName "GPT 本地工具箱"
#define MyAppVersion "1.0.0"
#define MyAppExeName "GPTLocalToolbox.exe"

[Setup]
AppId={{8A37DE0D-0B7D-4B4F-9B0B-7E51B53E54BC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\GPTLocalToolbox
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=GPTLocalToolbox_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\GPTLocalToolbox.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsVCRedist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "正在安装 Microsoft Visual C++ 运行库..."; Check: NeedsVCRedist and VCRedistInstallerExists
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsVCRedist: Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Result := Installed <> 1;
end;

function VCRedistInstallerExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\VC_redist.x64.exe'));
end;
