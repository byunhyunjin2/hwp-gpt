; HWP_GPT 설치 파일 (Inno Setup 6). build.ps1이 ISCC로 만든다: dist\HWP_GPT-Setup-<버전>.exe
; 관리자 권한 없이 사용자 폴더에 설치, 설치 후 Setup 파일은 지워도 된다. 업데이트는 같은 AppId로 덮어쓰기.
#define AppVersion GetEnv("HWPGPT_VERSION")

[Setup]
AppId={{6F1C2B7E-4A0D-4C3B-9E51-2D8A7F3C9B10}
AppName=HWP_GPT
AppVersion={#AppVersion}
AppVerName=HWP_GPT {#AppVersion}
AppPublisher=byunhyunjin2
AppPublisherURL=https://github.com/byunhyunjin2/hwp-gpt
DefaultDirName={localappdata}\HWP_GPT\app
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=HWP_GPT-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=force
RestartApplications=no
UninstallDisplayName=HWP_GPT
UninstallDisplayIcon={app}\HWP_GPT.exe
WizardStyle=modern

[Languages]
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[InstallDelete]
; 업데이트 때 예전 버전의 라이브러리·Codex가 섞이지 않게
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\codex"

[Files]
Source: "..\dist\HWP_GPT\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userdesktop}\HWP_GPT"; Filename: "{app}\HWP_GPT.exe"; Comment: "한글 옆 ChatGPT 패널"
Name: "{userprograms}\HWP_GPT"; Filename: "{app}\HWP_GPT.exe"; Comment: "한글 옆 ChatGPT 패널"

[Run]
; 직접 설치: 마지막 화면의 '실행' 체크. 패널의 [업데이트](조용히 설치): 끝나면 바로 다시 실행
Filename: "{app}\HWP_GPT.exe"; Description: "HWP_GPT 실행"; Flags: nowait postinstall

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
