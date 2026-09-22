; installer.iss - Inno Setup script for iPhone Companion
;
; Compile:  python build.py --installer
;      or:  open this file in the Inno Setup IDE and hit Build
;
; Installs per-user into %LOCALAPPDATA%\Programs so no admin prompt appears.
; Bluetooth access does not need elevation.

#define MyAppName "iPhone Companion"
#define MyAppShortName "iPhoneCompanion"
; MyAppVersion is normally injected by build.py (/DMyAppVersion=...) from
; paths.APP_VERSION, which is the single source of truth. The #define below
; is only a fallback for compiling this script directly in the Inno IDE, so
; if the two ever disagree, paths.py is right.
#ifndef MyAppVersion
  #define MyAppVersion "2.1.0"
#endif
#define MyAppPublisher "Arjun"
#define MyAppExeName "iPhoneCompanion.exe"

[Setup]
AppId={{8B2F41C7-6D3A-4E59-9C11-ANCS00000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppShortName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename={#MyAppShortName}-{#MyAppVersion}-setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start automatically when I sign in"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\iPhoneCompanion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; The same Run value the in-app "Start with Windows" switch manages, so the
; two never disagree.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "ANCSNotifier"; \
    ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start {#MyAppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; clears cached artwork, lyrics, config and logs
Type: filesandordirs; Name: "{localappdata}\ANCSNotifier"

[Messages]
WelcomeLabel2=This installs {#MyAppName}, which mirrors iPhone notifications, calls and media to your desktop over Bluetooth.%n%nBefore first run:%n  1. Pair the iPhone with this PC once via Windows Bluetooth settings.%n  2. Disable Phone Link's autostart - it holds the Bluetooth link and starves this app.%n%nThe app lives in the system tray; click it to open the dashboard.
