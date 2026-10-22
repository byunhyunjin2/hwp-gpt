# AGENTS.md — 이 레포에서 작업하는 AI용 규칙

## 작업 전
1. `docs/NOTES.md`, `docs/MISTAKES.md`를 읽는다
2. `docs/design.md`와 진행 중인 계획(`docs/plans/`)을 확인한다

## 작업 후 (반드시)
- 무엇이 바뀌었으면 → `CHANGELOG.md` 맨 위에 날짜와 함께 추가
- 새로 확인된 사실·결정 → `docs/NOTES.md` 갱신 (틀린 내용은 고치기)
- 실수했거나 되돌린 일 → `docs/MISTAKES.md`에 M-번호로 추가
- 기록 갱신까지 한 커밋에 포함

## 배포 (공개 레포 — 다른 PC가 자동으로 업데이트 알림을 받음)
- **시험 → 사용자 승인 → 배포.** 승인 없이 `release.py publish`·푸시·GitHub 릴리스 하지 않는다
- `python packaging/release.py build --notes notes.md --codex <Codex 폴더>` → 이 PC에서 설치·실행 확인 → 무엇을 시험했는지 보고하고 승인 요청 → 승인 후 `python packaging/release.py publish`
- 시험에서 문제가 나오면 `git checkout -- .`로 build가 바꾼 버전·README·CHANGELOG를 되돌리고 고친 뒤 다시 build

## 지켜야 할 것
- 실제 업무 문서(.hwp/.hwpx, 학생 이름·학번 포함) 커밋 금지. 테스트 문서는 코드로 생성
- **실제 개인정보(이름·학번·연락처 등)는 테스트·예시·문서·커밋 메시지·외부 AI 시험 입력 어디에도 쓰지 않는다.** 가짜 값만(홍길동 / 202699001 / 010-0000-0000). 커밋 전 확인 (MISTAKES M-005)
- **레포를 공개할 때는 이 레포를 공개하지 말고 새 레포를 만들어 현재 이력만 올린다** (GitHub에 정리 전 커밋이 해시로 남아 있음)
- 문서 파일 저장(`Save`/`SaveAs`) 코드 금지 — 저장은 사용자가 직접
- 한글 보안 경고창 우회 금지
- API 키 사용 금지 — ChatGPT 로그인(Codex)만
- 사용자의 `~/.codex` 설정 수정 금지 — 전용 `CODEX_HOME` 사용
- 응답·문서는 한국어
