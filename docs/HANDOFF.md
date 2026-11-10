# 인계 메모 (2026-11-11 → 다음 세션)

시작 전에 `AGENTS.md`, `docs/NOTES.md`, `docs/MISTAKES.md`, `CHANGELOG.md` 맨 위 몇 항목을 읽는다.

## 지금 상태
- 공개 레포 `byunhyunjin2/hwp-gpt`, 로컬 `C:\Users\user\claudework\hwp-gpt`, 브랜치 `main`. 배포된 최신 v1.0.8
- 2026-11-11: 워드 편집처럼 서식·표·넣기·검토 도구 7개 추가 + 점검 버그 수정 + 남은 한계 해결 (CHANGELOG). **아직 배포 안 함**
- 공식 Codex `rust-v0.167.0`을 `spike\bin`(git 제외)에 준비·검증해 둠 → 빌드 때 `--codex spike\bin`
- 예전 비공개 레포 폴더 `HWP_GPT`는 2026-10-26 정리로 지워짐. 개발 `.venv`는 이 레포 안(`python -m venv .venv` + requirements)
- 테스트: `.venv\Scripts\python -m pytest -q`, 한글 필요 테스트 `-m hwp` (시험 전용 인스턴스, 한글을 모두 닫고)

## 배포 (새 버전 낼 때)
1. 바뀐 것을 커밋 (CHANGELOG·NOTES·MISTAKES 포함)
2. 사용자에게 보일 짧은 변경 목록을 `notes.md`(레포 밖 임시 파일)에 쓰기
3. 공식 Codex: `spike\bin`에 0.167.0 있음. 새 버전으로 바꿀 땐 openai/codex 릴리스 zip을 받아 SHA256·서명 확인 (NOTES 'Codex')
4. `.venv\Scripts\python packaging\release.py build --notes notes.md --codex spike\bin`
   - 설치 파일을 탐색기로 실행해 이 PC에서 설치·실행 확인 → **사용자에게 보고하고 승인받기** (승인 없이 배포 금지)
   - 승인 후 `.venv\Scripts\python packaging\release.py publish`
5. **공개 레포라 푸시 전 개인정보 검사 필수** (M-005, M-008, M-009)

## 실행
- 개발판: `start_hwp_gpt.bat`. Codex는 `HWPGPT_CODEX` → `spike\bin` → Codex 앱 설치 폴더 순으로 찾음. **사용자 환경 확인은 탐색기로 실행** (M-006)
- 설치본과 개발판을 동시에 띄우면 패널이 두 개 붙는다 — 하나만 실행

## 열린 문제
1. 코드 서명 없음 → SmartScreen 경고 (인증서 구매가 필요해 사용자 결정)
2. 새 PC·학교 PC, 한컴 2022 외 버전 확인 (그 PC가 있어야 함)
3. 한글 안 모드 패널 가림은 재현 안 됨 — 맨 위로 되돌리는 처리를 넣음. 다시 보이면 그 PC의 배율·한글 버전 확인
4. 미루어 둔 것: 한글 다중 프로세스 시 도킹 창과 ROT 대상 불일치 / 표 합계 점검은 줄 단위 추정 / 칸 합치기·열·문단 지우기·쪽 나누기·그림 바꾸기는 패널 ↶ 없음(한글 Ctrl+Z) / 메모는 문단 단위(앞에 대상 글 표시)

## 꼭 지킬 것
- **개인정보·실제 문서 내용**: 이름·학번뿐 아니라 실제 문서의 금액·문장·행사명도 레포·커밋·테스트·문서에 넣지 않는다. 예시는 가짜 값(홍길동 / 202699001 / OO구 평생학습축제)
- 자동 시험은 시험 전용 인스턴스의 경로 없는 새 문서에서만. 경로 있는 문서가 보이면 중단 (M-004)
- 매 커밋에 CHANGELOG / NOTES / MISTAKES 갱신 포함 (`AGENTS.md`)
