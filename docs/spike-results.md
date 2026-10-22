# 확인 시험 결과 (Task 1)

2026-10-22 · 사용자 PC (Windows 11, 한컴오피스 2022, ChatGPT 로그인)
1차는 사용자 PC에 설치된 Codex(`0.163.0-alpha.10.2`), 마지막 확인은 **공식 릴리스 Codex + 전용 CODEX_HOME**으로 함 (아래 "공식 Codex" 절).

**Task 1 완료** — 모든 항목 확인, 남은 미확인 없음.

## 공식 Codex + 전용 CODEX_HOME (사용자 결정: 방식 a)
- 릴리스 `rust-v0.163.0` (2026-10-15) `codex-x86_64-pc-windows-msvc.exe.zip` 159MB
  - SHA256 `dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3` = 릴리스 게시값 일치
  - 실행 파일 Authenticode 서명 Valid, 서명자 `OpenAI OpCo, LLC`
  - 압축 해제 구성: `codex-x86_64-pc-windows-msvc.exe`(325MB), `codex-command-runner.exe`, `codex-windows-sandbox-setup.exe`, `codex-code-mode-host.exe`, `codex-resources/`, `codex-path/`, `bin/`, `codex-package.json` → **설치본에 폴더째 동봉** (설치본 300MB 이상 예상)
- `CODEX_HOME=%APPDATA%\HWP_GPT\codex`로 `codex login` → 브라우저 ChatGPT 로그인 → `auth.json` 생성, `login status` = "Logged in using ChatGPT"
- 전용 폴더에는 config.toml이 없으므로 `--ignore-user-config` 불필요. 사용자 `~/.codex/config.toml`은 수정되지 않음(수정 시각 확인)
- 작업 폴더 `%APPDATA%\HWP_GPT\work`에서 같은 한글 수정 시험 → 제목·행사명·날짜(요일) 변경, 학번·전년도 실적 유지, 입력 약 6.7만 토큰(캐시 6.1만)

| # | 항목 | 결과 |
|---|---|---|
| 1 | Python / pywebview | **OK** — Python 3.14.7 + pywebview(edgechromium) 창 표시, JS→Python 호출 왕복 |
| 2 | Codex ChatGPT 로그인만으로 응답 | **OK** — `OPENAI_API_KEY` 없는 환경에서 `codex exec` 응답 |
| 3 | Codex → 우리 MCP 도구 호출 | **OK** (승인 설정 필요, 아래) |
| 3+ | Codex → MCP → COM으로 실제 한글 수정 | **OK** — "2027학년도로 바꿔줘" → 제목·행사명·날짜(요일 포함) 변경, 학번·전년도 실적 유지 |
| 4 | 대화 이어가기 | **OK** — `codex exec resume <thread_id> "방금 바꾼 날짜를 하루 앞당겨"` → 맥락 유지 |
| 5 | API 키 무시 | **OK, 단 필수 처리** — 환경에 `OPENAI_API_KEY`가 있으면 Codex는 **로그인 대신 API 키를 사용**(가짜 키로 401 확인). 실행 전 키 제거하면 정상 |
| 6 | 한글 본문 읽기 | **OK** — `UNICODE`·`HWPML2X` 모두 표 셀 텍스트 포함, HWPML2X는 `<TABLE` 구조 포함(약 50만 자로 큼) |
| 7 | 표시 방식 | **확정: 한글 형광펜 (`MARK_MODE = "markpen"`)** — 시험 전용 인스턴스의 새 문서에서 재시험 |

### 7. 형광펜 상세 (재시험, 시험 전용 한글 인스턴스·경로 없는 새 문서)
- 표시: 찾기(`RepeatFind`)로 선택 → `HAction.GetDefault("MarkPenShape", HParameterSet.HMarkpenShape.HSet)` → `HMarkpenShape.Color = h.RGBColor(r,g,b)` → `Execute` → True
- 검증: 시험 문서를 스크래치에 hwpx로 저장해 보니 `<hp:markpenBegin color="#FFF000"/>`(노랑), `#FF7878`(빨강) 생성
- 표시 앞에 사용자가 글자를 넣어도 표시 유지
- 지우기: `SelectAll` → `HAction.Run("MarkPenDelete")` → 형광펜 0개. **단 사용자가 원래 칠해 둔 형광펜까지 지워짐** → 제품은 패널이 표시한 범위만 다시 찾아 그 선택에만 `MarkPenDelete` (전체 지우기는 쓰지 않음)
- `GetTextFile("HWPML2X")`에는 형광펜이 나오지 않음 → 표시 여부는 패널이 자체 목록으로 관리
- 변경 추적: 바이너리에 `TrackChange`·`TrackChangeDlg` 문자열은 있으나 `HAction.Run("TrackChange")` 등은 False → **사용하지 않음**
- `HCharShape.ShadeColor`(글자 음영)는 다시 읽어도 기본값이라 확인 불가 → 사용하지 않음

⚠ 2차 시험 첫 시도는 사용자의 실제 문서 위에서 실행됨 (MISTAKES M-004). 위 7번 결과는 안전장치(경로 있는 문서가 있으면 중단)를 넣은 재시험 결과

## 확정된 Codex 실행 방법

```
codex exec --skip-git-repo-check --ignore-user-config --sandbox read-only --json
  -c mcp_servers.hwpgpt.command="<python 또는 도구서버.exe>"
  -c mcp_servers.hwpgpt.args=["<tools_server.py>"]
  -c mcp_servers.hwpgpt.default_tools_approval_mode="approve"
  -c mcp_servers.hwpgpt.env={PYTHONIOENCODING="utf-8"}
  "<요청>"  < (빈 stdin)
이어서:  codex exec <같은 옵션> resume <thread_id> "<후속 요청>"
```

- stdin을 비워 주지 않으면 `Reading additional input from stdin...`에서 기다림 → 반드시 빈 stdin
- `default_tools_approval_mode="approve"` 없으면 `MCP tool call requires approval, but approval policy is never`로 실패
- `--sandbox read-only`에서 AI가 셸 명령을 시도하면 정책으로 차단됨(좋음). 다만 요청이 모호하면 AI가 도구 대신 셸을 먼저 시도함 → 지침에 "셸 금지, 도구만" 명시 필요
- `--ignore-user-config`: 사용자 `config.toml`(플러그인 등)은 무시하고 **로그인 정보는 그대로 사용** → 전용 CODEX_HOME 없이도 격리 가능할 수 있음 (결정 필요, NOTES 참고)
- `--json` 이벤트: `thread.started{thread_id}`, `item.completed{agent_message|mcp_tool_call}`, `turn.completed{usage}`
- 토큰: 간단한 질문도 입력 약 2만 토큰(Codex 기본 지침), 한글 수정 1회 약 5~7만(대부분 캐시) → 사용 한도에 영향

## 한글 COM 연결 — 계획 수정 필요

- `GetActiveObject("HWPFrame.HwpObject")`는 **사용자가 직접 연 한글에도 실패**
- 한글은 ROT에 `!HwpObject.120.1` 이름으로 등록됨 → ROT를 열거해 `!HwpObject`로 시작하는 항목에 붙으면 **새 창 없이 사용자 창에 연결됨** (검증)
- `Dispatch`로 띄운 한글은 **띄운 프로세스가 끝나면 같이 닫힘**, 그리고 숨은 새 인스턴스를 만들 수 있음 → 사용 금지
