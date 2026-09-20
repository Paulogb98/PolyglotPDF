; Windows installer for PolyglotPDF (Inno Setup 6).
;
; It packages the folder PyInstaller produces (dist\PolyglotPDF) into a single setup
; executable. Build it with:
;
;     uv run python scripts/build_installer.py
;
; which compiles the interface, freezes the app and then calls ISCC with the defines
; below. Compiling this file by hand works too, as long as dist\PolyglotPDF exists:
;
;     ISCC installer\polyglotpdf.iss /DAppVersion=0.3.0

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\PolyglotPDF"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "PolyglotPDF"
#define AppPublisher "Paulo Gois"
#define AppUrl "https://github.com/Paulogb98/PolyglotPDF"
#define AppExe "PolyglotPDF.exe"

[Setup]
; Keep this GUID: it is what lets a new version replace the previous install.
AppId={{8F2C6C4E-5B3A-4E27-9E2E-4D6F5A1B7C90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; A per-user install needs no administrator; the dialog still offers "for everyone".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\src\polyglotpdf\app\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
#if FileExists(AddBackslash(SourcePath) + "..\LICENSE")
LicenseFile=..\LICENSE
#endif
MinVersion=10.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The frozen app writes nothing here, but PyInstaller's folder may keep caches.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
