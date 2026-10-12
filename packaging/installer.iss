; Inno Setup script: builds DrDeconstruct-Setup-<version>.exe, a per-user installer
; (no administrator rights needed). Build with:
;   iscc /DAppVersion=0.1.0 packaging\installer.iss
; The PyInstaller output dist\DrDeconstruct.exe must exist first.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1F4B5E-7D0B-4C0E-9B53-4D5A7E1A0C21}
AppName=DrDeconstruct
AppVersion={#AppVersion}
AppPublisher=VjAlbert
AppPublisherURL=https://github.com/VjAlbert/autopsy
AppSupportURL=https://github.com/VjAlbert/autopsy/issues
DefaultDirName={autopf}\DrDeconstruct
DefaultGroupName=DrDeconstruct
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=DrDeconstruct-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\DrDeconstruct.exe
LicenseFile=..\LICENSE
SetupIconFile=drdeconstruct.ico

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\DrDeconstruct.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\DrDeconstruct"; Filename: "{app}\DrDeconstruct.exe"
Name: "{autodesktop}\DrDeconstruct"; Filename: "{app}\DrDeconstruct.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DrDeconstruct.exe"; Description: "{cm:LaunchProgram,DrDeconstruct}"; Flags: nowait postinstall skipifsilent
