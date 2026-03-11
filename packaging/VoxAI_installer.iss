#ifndef SourceDir
  #define SourceDir "..\\dist\\windows\\VoxAI_IDE"
#endif
#ifndef OutputDir
  #define OutputDir "..\\dist\\installer"
#endif
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif

[Setup]
AppId={{BA4FD2D3-2777-498B-8D2F-37A3FA8F7391}
AppName=VoxAI IDE
AppVersion={#AppVersion}
AppPublisher=Batty251
DefaultDirName={autopf}\VoxAI IDE
DefaultGroupName=VoxAI IDE
UninstallDisplayIcon={app}\VoxAI_IDE.exe
OutputDir={#OutputDir}
OutputBaseFilename=VoxAI-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VoxAI IDE"; Filename: "{app}\VoxAI_IDE.exe"
Name: "{autodesktop}\VoxAI IDE"; Filename: "{app}\VoxAI_IDE.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VoxAI_IDE.exe"; Description: "Launch VoxAI IDE"; Flags: nowait postinstall skipifsilent