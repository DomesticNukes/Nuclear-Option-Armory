; Inno Setup script — produces a proper Setup Wizard installer for people who don't have Python
; and don't want to think about where to put a loose .exe. Installs per-user (no admin/UAC prompt),
; adds a Start Menu entry (+ optional Desktop shortcut), and registers a real uninstaller in
; "Apps & Features". Run `python build.py` first — this packages dist\Nuclear Option Mod Manager.exe.
;
; Compile with: ISCC.exe installer.iss   (or just `python build.py`, which does this automatically
; if Inno Setup's ISCC.exe is found on the machine).

#define MyAppName "Nuclear Option Mod Manager"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "DomesticNukes"
#define MyAppExeName "Nuclear Option Mod Manager.exe"
#define MyAppURL "https://github.com/DomesticNukes/Nuclear-Option-Mod-Manager"

[Setup]
AppId={{8BD061DC-67FF-4726-A1EC-6AE5B21EE6EC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install — no admin rights / UAC prompt needed, the friendliest path for someone who
; doesn't want to think about permissions.
PrivilegesRequired=lowest
OutputDir=dist_installer
OutputBaseFilename=Nuclear Option Mod Manager Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\Nuclear Option Mod Manager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
