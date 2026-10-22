# HWP_GPT

한컴 한글 창 옆에 **ChatGPT 패널**을 붙여, 문서를 띄워 둔 채 말로 고치는 Windows 프로그램.
작년 공문·계획서를 열고 "올해 걸로 바꿔줘"라고 하면 바로 고치고, 고친 곳(노랑)과 확인할 곳(빨강)을 형광펜으로 표시합니다.

> 한글과컴퓨터의 공식 제품이 아니며, 한컴과 관련이 없는 개인 프로젝트입니다. "HWP"는 문서 형식 이름으로 사용합니다.

<!-- latest -->
현재 버전: **v1.0.1** — [설치 파일 받기](https://github.com/byunhyunjin2/hwp-gpt/releases/latest)

- 첫 공개 버전
- 한글 옆 ChatGPT 패널: 연도·날짜·금액·문장을 말로 고치고 형광펜으로 표시
- 옛 연도가 남은 곳, 표 합계·계산식이 안 맞는 곳을 확인 필요로 표시
- 패널에서 새 버전 확인·설치 ([업데이트] 버튼)
<!-- /latest -->

## 필요한 것

- Windows 10/11, 한컴오피스 한글 (2022에서 확인)
- **ChatGPT 유료 구독** — API 키 없음, 추가 비용 없음 (요금제의 Codex 사용 한도 안에서 동작)

## 설치

1. [릴리스 페이지](https://github.com/byunhyunjin2/hwp-gpt/releases/latest)에서 `HWP_GPT-Setup-<버전>.exe`를 받아 실행합니다 (약 110MB, 관리자 권한 불필요).
   - "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요 (코드 서명 전이라 뜹니다).
2. 설치가 끝나면 받은 Setup 파일은 지워도 됩니다.
3. 바탕화면의 **HWP_GPT** 실행 → 처음 한 번 **[ChatGPT로 로그인]** (브라우저에서 평소 ChatGPT 계정으로).
4. 한글에서 문서를 열면 패널이 오른쪽에 붙습니다.

**업데이트**: 패널을 켤 때 새 버전이 있으면 알려 줍니다. [업데이트]를 누르면 받아서 설치하고 다시 켜집니다. 상단의 [업데이트] 버튼으로 직접 확인할 수도 있습니다.
**제거**: Windows 설정 → 앱 → HWP_GPT → 제거 (기억·로그인 정보는 `%APPDATA%\HWP_GPT`에 남음)

## 쓰는 법

- "2027학년도로 바꿔줘", "예산을 500,000원으로 올려줘", "추진 배경 문단 새로 써줘"
- 바뀐 연도가 남은 곳, 표의 합계·계산식이 안 맞는 곳, 날짜는 빨강으로 **확인 필요** 표시를 합니다. 목록의 항목을 누르면 그 위치로 갑니다.
- 학번·이름·연락처 등 개인정보와 문서 형식·표 모양은 바꾸지 않습니다.
- **제출 전 [표시 모두 지우기]** → 한글에서 직접 **다른 이름으로 저장** (HWP_GPT는 저장하지 않습니다).
- 상단에서 GPT 모델, 밝은/어두운 화면, 한글 안/옆 배치를 고를 수 있습니다.

## 개인정보 안내

- 고칠 때 **문서 내용이 내 ChatGPT 계정으로 OpenAI에 전송**됩니다. 학생 정보가 든 문서는 학교의 개인정보 지침을 먼저 확인하세요.
- 로그인·기억한 규칙·대화 기록은 이 PC의 `%APPDATA%\HWP_GPT`에만 저장됩니다. 개발자에게 전송되는 정보는 없습니다 (업데이트 확인은 GitHub에서 버전 정보만 받음).

## 개발

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python -m pytest            # 한글 없이 도는 테스트
.\.venv\Scripts\python -m pytest -m hwp     # 한글 필요(시험 전용 인스턴스 사용)
python run.pyw                              # 패널 실행 (Codex: spike\bin 또는 HWPGPT_CODEX)
```

**배포** (Inno Setup 6 필요): 변경 목록을 `notes.md`에 짧게 쓰고

```powershell
.\.venv\Scripts\python packaging\release.py --notes notes.md --codex <공식 Codex 폴더>
```

버전을 올리고(자리마다 0~9: 1.0.9 다음 1.1.0) 테스트 → 설치 파일 → README·CHANGELOG 갱신 → 태그 → GitHub 릴리스까지 한 번에 합니다. 설치된 패널은 릴리스의 `latest.json`을 보고 업데이트를 알립니다.

## 문서

| 파일 | 내용 |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | 수정사항 (날짜순) |
| [docs/design.md](docs/design.md) | 무엇을 왜 만드는지, 정한 것, 구성 |
| [docs/NOTES.md](docs/NOTES.md) | 중요한 내용·기억해야 할 사실 |
| [docs/MISTAKES.md](docs/MISTAKES.md) | 실수와 재발 방지책 |
| [AGENTS.md](AGENTS.md) | 이 레포에서 작업하는 AI용 규칙 |
| [packaging/THIRD_PARTY_NOTICES.md](packaging/THIRD_PARTY_NOTICES.md) | 오픈소스 고지 |
