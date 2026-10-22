# 인계 메모 (2026-10-22 → 다음 세션)

시작 전에 `AGENTS.md`, `docs/NOTES.md`, `docs/MISTAKES.md`, `CHANGELOG.md` 맨 위 몇 항목을 읽는다.

## 지금 상태
- **공개 레포 `byunhyunjin2/hwp-gpt`가 본 레포** (2026-10-22부터). 로컬 폴더 `C:\Users\user\claudework\hwp-gpt`, 브랜치 `main`
  - 예전 비공개 레포 `HWP_GPT`(폴더 `C:\Users\user\claudework\HWP_GPT`, 브랜치 `feat/core`)는 보관용. 정리 전 이력이 있어 **절대 공개 레포로 푸시하지 않는다**
  - 개발용 `.venv`와 공식 Codex(`spike\bin`)는 아직 예전 폴더에 있음 → 테스트·배포 때 `--python`, `--codex`로 그 경로를 넘긴다
- 설치형 패널 v1.0.1 공개 배포: Inno Setup 설치 파일(약 110MB) + 패널 시작 시·[업데이트] 버튼으로 새 버전 확인·설치
- 테스트: `.venv\Scripts\python -m pytest -q`, 한글 필요 테스트 `-m hwp`

## 배포 (새 버전 낼 때)
1. 바뀐 것을 커밋 (CHANGELOG·NOTES·MISTAKES 포함)
2. 사용자에게 보일 짧은 변경 목록을 `notes.md`(레포 밖 임시 파일)에 쓰기
3. `python packaging\release.py --notes notes.md --codex C:\Users\user\claudework\HWP_GPT\spike\bin --python C:\Users\user\claudework\HWP_GPT\.venv\Scripts\python.exe`
   - 버전 자동 증가(1.0.9 → 1.1.0), 테스트, 설치 파일, latest.json, README·CHANGELOG, 태그·푸시, GitHub 릴리스
4. **공개 레포라 푸시 전 개인정보 검사 필수** (실제 문서의 이름·학번·금액·문장 — M-005, M-008, M-009)

## 실행
- 개발판: `start_hwp_gpt.bat` 더블클릭. **사용자 환경 확인은 탐색기로 실행**: `Start-Process explorer.exe start_hwp_gpt.bat` (Claude 앱 안은 `%APPDATA%`가 가상화됨, M-006)
- 설치본과 개발판을 동시에 띄우면 패널이 두 개 붙는다 — 하나만 실행

## 열린 문제
1. 패널 [ChatGPT로 로그인] 버튼 실패 원인 미확인 (`%APPDATA%\HWP_GPT\login.log`로 확인)
2. 한글 안 모드에서 패널 왼쪽이 가려지는 현상 (원인 미확인)
3. 코드 서명 없음 → SmartScreen 경고. 사용자 늘면 인증서 검토
4. 새 PC·학교 PC 설치 확인, 한컴 2022 외 버전 확인
5. 미루어 둔 것: 한글 다중 프로세스 시 도킹 창과 ROT 대상 불일치 가능 / Codex 오류 분류가 낱말 기준 / 표 합계 점검은 줄 단위 추정

## 꼭 지킬 것
- **개인정보·실제 문서 내용**: 이름·학번뿐 아니라 실제 문서의 금액·문장·행사명도 레포·커밋·테스트·문서에 넣지 않는다. 예시는 가짜 값(홍길동 / 202699001 / OO구 평생학습축제)
- 사용자가 시험용으로 지정한 실제 문서(Downloads의 앵커사업 운영계획서)는 수정해도 되지만 내용은 레포에 저장 금지
- 자동 시험은 가짜 데이터 문서(`scripts/make_sample.py`, `--long`)로. 열린 문서 경로가 시험 문서가 아니면 중단
- 매 커밋에 CHANGELOG / NOTES / MISTAKES 갱신 포함 (`AGENTS.md`)
