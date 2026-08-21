; 视频下载器 - Inno Setup 安装脚本
; 用法: 先 PyInstaller 打出 dist\VideoDownloader\, 再用 Inno Setup 编译本文件:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; 产物: installer_output\VideoDownloader-Setup-1.0.0.exe (单文件安装包)
;
; per-user 安装 (PrivilegesRequired=lowest): 同事不需要管理员权限就能装 ——
; 公司电脑多半没有本地管理员, 这条很关键。
; 配置/历史/日志写在 %APPDATA%\VideoDownloader, 与安装目录无关, 卸载不会误删。

#define MyAppName "视频下载器"
#define MyAppVersion "1.0.1"
#define MyAppExeName "VideoDownloader.exe"

[Setup]
; AppId 与主线 CCC Live Studio 不同 —— 两个程序可以在同一台机器上并存
AppId={{9F3C7D51-8A2E-4B6F-A1D4-5E7C90B2F846}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\VideoDownloader
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=VideoDownloader-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 整个 PyInstaller onedir 输出 (exe + _internal: PyQt6 / ffmpeg / deno / 样式图标)
Source: "dist\VideoDownloader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
