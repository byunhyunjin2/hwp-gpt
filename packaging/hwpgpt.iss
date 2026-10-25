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
SetupIconFile=..\src\hwpgpt\assets\hwpgpt.ico
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

[Code]
{ 이미 설치된 PC에서 새 설치 파일을 직접 실행하면 '업데이트'로: 묻고, 같은 폴더에 덮어쓰고, 끝나면 패널을 다시 띄운다.
  설정·기억한 규칙(%APPDATA%\HWP_GPT)은 건드리지 않는다. 패널의 [업데이트](/SILENT)는 묻지 않는다. }
var
  Installed: String;

function InstalledVersion(): String;
begin
  if not RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F1C2B7E-4A0D-4C3B-9E51-2D8A7F3C9B10}_is1',
                             'DisplayVersion', Result) then
    Result := '';
end;

{ '1.0.3'과 '1.0.5' 비교: 앞이 작으면 음수, 같으면 0, 크면 양수 }
function CompareVersion(A, B: String): Integer;
var
  X, Y, I: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do
  begin
    I := Pos('.', A); if I = 0 then I := Length(A) + 1;
    X := StrToIntDef(Copy(A, 1, I - 1), 0); Delete(A, 1, I);
    I := Pos('.', B); if I = 0 then I := Length(B) + 1;
    Y := StrToIntDef(Copy(B, 1, I - 1), 0); Delete(B, 1, I);
    Result := X - Y;
  end;
end;

function InitializeSetup(): Boolean;
var
  C: Integer;
begin
  Result := True;
  Installed := InstalledVersion();
  if (Installed = '') or WizardSilent() then
    exit;
  C := CompareVersion(Installed, '{#AppVersion}');
  if C < 0 then
    Result := MsgBox('HWP_GPT ' + Installed + ' 버전이 설치되어 있습니다.' #13#10 +
                     '{#AppVersion} 버전으로 업데이트할까요?' #13#10#13#10 +
                     '설정과 기억한 규칙은 그대로 유지됩니다. 열려 있는 패널은 닫혔다가 다시 열립니다.',
                     mbConfirmation, MB_YESNO) = IDYES
  else if C = 0 then
    Result := MsgBox('HWP_GPT {#AppVersion} 버전이 이미 설치되어 있습니다. 다시 설치할까요?',
                     mbConfirmation, MB_YESNO) = IDYES
  else
    Result := MsgBox('더 새 버전(' + Installed + ')이 설치되어 있습니다.' #13#10 +
                     '예전 버전({#AppVersion})으로 바꿀까요?', mbError, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure InitializeWizard();
begin
  if Installed = '' then
    exit;
  if CompareVersion(Installed, '{#AppVersion}') = 0 then
    WizardForm.Caption := 'HWP_GPT {#AppVersion} 다시 설치'
  else
    WizardForm.Caption := 'HWP_GPT 업데이트 (' + Installed + ' → {#AppVersion})';
end;

{ 업데이트는 처음 물을 때 이미 '예'를 받았으니 '설치 준비 완료' 화면을 건너뛰고 바로 진행 }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (Installed <> '') and (PageID = wpReady);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if Installed = '' then
    exit;
  if CurPageID = wpInstalling then
  begin
    WizardForm.PageNameLabel.Caption := '업데이트하는 중';
    WizardForm.PageDescriptionLabel.Caption := 'HWP_GPT를 {#AppVersion} 버전으로 바꾸고 있습니다.';
  end
  else if CurPageID = wpFinished then
  begin
    WizardForm.FinishedHeadingLabel.Caption := '업데이트를 마쳤습니다';
    WizardForm.FinishedLabel.Caption := 'HWP_GPT ' + Installed + ' → {#AppVersion} 업데이트가 끝났습니다.';
  end;
end;
