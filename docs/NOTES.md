# 중요한 내용 · 기억해야 할 것

확인된 사실과 결정만 적는다. 추측은 "미확인"으로 표시. 바뀌면 고치고 CHANGELOG에 남긴다.

## 사용자·범위
- 대상: ChatGPT **유료** 사용자 다수, 앱 사용자 + 웹만 쓰는 사용자 혼재. Claude는 무료 → **Claude 제외**
- 주 업무: 대학 앵커사업 계획서·공문·참석자 명단을 해마다 연도 갱신
- 사용자 결정: 먼저 고치고 표시 / 기억은 묻고 저장 / 직접 수정도 학습 / 저장은 사용자가 직접 '다른 이름으로 저장'

## 한글 COM (2026-10-21 검증, 한컴오피스 2022)
- ProgID `HWPFrame.HwpObject` 등록됨, pywin32로 연결 OK
- **연결은 ROT 열거로**: 한글은 ROT에 `!HwpObject.120.1`로 등록. `GetActiveObject("HWPFrame.HwpObject")`는 사용자가 연 한글에도 실패함 (2026-10-22 검증, `docs/spike-results.md`)
- `Dispatch`는 숨은 새 한글을 띄울 수 있고, 띄운 프로세스가 끝나면 그 한글도 닫힘 → 패널·도구 서버에서 사용 금지
- hwp-mcp(jkf87)의 `security_module/FilePathCheckerModuleExample.dll`은 **120바이트 깨진 스텁** → `register_security_module=False`. 한글 파일 접근 확인창은 우회하지 않는다
- **수정 표시는 한글 형광펜**: `MarkPenShape`(HMarkpenShape.Color) 표시, `MarkPenDelete` 지우기. 변경 추적·글자 음영은 COM으로 안 됨 (2026-10-22 검증)
- 저장 감지: `XHwpDocuments.Active_XHwpDocument.Modified`가 True→False
- 시험 중 관찰: `SelectAll`+`Delete`가 문서를 다 지우지 못하는 경우가 있음(이전 시험 문장이 남음) — 시험 문서 초기화엔 새 문서를 쓰는 편이 확실
- 형광펜은 `GetTextFile("HWPML2X")`에 안 나옴 → 표시 목록은 패널이 직접 관리
- **시험은 반드시 시험 전용 인스턴스(`Dispatch`)의 경로 없는 새 문서에서**, 경로 있는 문서가 보이면 중단 (M-004). 제품은 ROT로 사용자 한글에 붙되 대상 문서를 확인
- hwp-mcp 코드 검토: 네트워크·subprocess·eval 없음 (`ast.literal_eval`만)
- 저장된 결과는 hwp-cli(`hwp cat`)로 교차 검증 가능

## 문서 처리 규칙 (`src/hwpgpt/rules.py`로 구현, 2026-10-22)
- **수정 범위 (사용자 결정, 2026-10-22):** 지킬 것은 문서 형식·틀·표 모양과 개인정보뿐. 그 밖의 내용(금액 포함)은 고칠 수 있다 → 금액 보호(이유에 '예산' 필요) 규칙 삭제
- 식별번호 = 구분자 없는 숫자 7자리 이상. 걸치는 수정은 거부
- 금액 점검(코드): 산출내역 계산식 `A×B = C`(`check_math`), 표 '합계'와 위 금액 칸의 합(`check_table_sums`), 물품 목록은 수량×단가인 칸의 합, '합계'와 '사업 예산'(`check_budget`)
- 한글 표 칸의 '1,234,560원' 같은 금액은 한글 찾기로 통째로 안 찾아지는 경우가 있음(숫자만은 찾아짐, 2026-10-22 사용자 문서에서 확인) → 금액은 숫자만 찾기·표시, 실패 시 '원'을 떼고 다시(`strip_unit`)
- 개인정보 문단 = 전화·이메일·주민번호 패턴 또는 키워드(담당자·성명·연락처·전화·휴대전화·이메일·주소)
- 요일 검사는 수정 후 문자열(`replace`) 안의 모든 날짜에 대해 수행
- 개인정보(담당자·성명·연락처·전화·이메일·주소) 문단 보호
- 식별번호 안의 연도(`202699001`) 치환 금지
- 날짜는 전체 문자열로 교체, 원래 표기(점·띄어쓰기·괄호) 유지, 요일은 달력으로 **코드가** 계산
- 전년도 실적·서명일·경력 날짜는 바꾸지 않고 확인 표시
- **연도 누락 점검은 코드가 한다** (사용자 요청, 2026-10-22): 적용된 수정에서 옛 연도를 알아내 문서에 남은 곳을 `leftover`로 AI에 돌려주고, 요청 끝에 패널이 한 번 더 빨간 표시. AI 지침만으로는 "2026년 9월 1일" 같은 표기를 놓쳤음
- **연도를 바꾼 날짜는 바꾸되 빨간 '확인 필요'** (사용자 결정, 2026-10-22): 요일은 코드가 달력으로, 실제 일정 여부는 사용자가 확인
- **AI가 주는 문구는 띄어쓰기가 줄어 있음**(`find_lines`가 공백을 한 칸으로 압축) → 표시·수정·이동 전에 `resolve_text`로 문서의 실제 문구로 되돌린다
- 확인 목록은 요청 끝 최종 문서 기준으로 정리 (도구를 여러 번 부르면 중간 상태의 항목이 남기 때문)
- 예산 합계 점검: 표마다 소계 '합계'가 있어 가장 큰 합계 하나만 사업 예산과 비교
- 추천 답변: AI 답변 끝 `[[선택: 문장]]` → 패널 버튼 (지침 `assets/AGENTS.md`)
- 작성일·신청일·서명일: 바꾸지 않지만 **확인 표시는 함** (전에는 표시도 안 함 → 사용자가 놓친 것으로 봄)

## Codex
- 사용자 PC Codex 경로는 해시 폴더: `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` — **업데이트 시 바뀜, 하드코딩 금지**. 배포본은 Codex를 번들
- `codex login status` → "Logged in using ChatGPT" 이면 구독으로 동작
- **API 키 없이 ChatGPT 로그인만으로 대화·MCP 도구 호출·한글 수정·대화 이어가기 모두 동작 확인** (2026-10-22). 실행 옵션은 `docs/spike-results.md`
- **로그인 방식 결정 (사용자, 2026-10-22): (a) 전용 `CODEX_HOME=%APPDATA%\HWP_GPT\codex`에 패널에서 1회 로그인.** 공식 Codex로 로그인·한글 수정까지 검증. (`--ignore-user-config`로 기존 로그인을 빌리는 방식 b는 채택 안 함)
- 배포용 Codex: openai/codex 릴리스의 `codex-x86_64-pc-windows-msvc.exe.zip`, **SHA256을 릴리스 digest와 대조 + OpenAI 서명 확인 후** 동봉 (spike-results)
- 1회 요청 토큰: 절감 전 약 9.4만 → **절감 후 약 3.2만** (긴판 시험 문서 기준, 2026-10-22). 대부분은 모델 호출마다 붙는 고정 부분(도구 정의·지침)
- 토큰 절감 설정 (`codex_runner.build_command`): `-c model_instructions_file=<assets/AGENTS.md>`(Codex 코딩용 기본 지침 대체), `-c web_search="disabled"`, `--disable <기능>` ×17 (`DISABLED_FEATURES`). 기능 목록은 `codex features list`로 확인 — Codex 업데이트 시 이름이 바뀔 수 있으니 다시 확인
- 지침을 줄일 때 행동 규칙이 빠지면 품질이 바로 떨어짐 (예: 합계 동시 수정). 지침 변경 후엔 연도 갱신 + 예산 변경 두 가지를 다시 시험
- 도구 서버 실행: `python -m hwpgpt.tools_server`, env `PYTHONPATH=<repo>/src`, `HWPGPT_SESSION=<세션 jsonl>`, `PYTHONIOENCODING=utf-8`. Codex `-c mcp_servers.hwpgpt.env={...}`로 전달 (2026-10-22 검증)
- 도구 설명(docstring)이 AI 행동을 좌우함 — "날짜는 요일 포함 전체 문자열", "금액은 숫자만" 문구를 도구 설명에 넣어 둠
- 사용자 기존 `~/.codex/config.toml`에는 hwpx 관련 플러그인(airmang/hwpx-plugins, hj-hwpx-codex)이 있음 → 전용 `CODEX_HOME`으로 격리

## 한컴 공식 서비스 (2026-10-22 조사)
- **한애드온즈** (addons.hancom.com): 한글 **안에** 외부 AI 기능을 넣는 한컴 공식 확장 플랫폼. 입점 사례: 카피킬러, 다글로, 업스테이지 에디트업, 틀루토, 앨리비, 애셋 스튜디오. **한컴오피스 2024(13.0.0.3379 이상)부터**. 공개 SDK·개발 문서 없음 → 입점은 한컴 제휴 문의(hancom.com 고객센터 제휴 항목). 장기적으로 "한글 안 패널"의 공식 경로 후보
- **한컴독스** (hancomdocs.com): 구독형 한컴오피스 + **한컴독스 AI**(초안 작성·문장 생성·맞춤법). 개인 연간 월 4,084원 / 월간 6,900원. 공개 API 없음
- **한컴독스 AI 리버스엔지니어링은 하지 않음**: 유료 서비스의 비공개 API를 무단으로 쓰는 것은 이용약관 위반·법적 위험. 대안은 공식 경로(사용자가 한컴독스 구독 / 한애드온즈 제휴)

## 배포·업데이트 (2026-10-22)
- 공개 레포 `byunhyunjin2/hwp-gpt` (예전 비공개 `HWP_GPT`는 정리 전 이력 때문에 공개하지 않고, 현재 파일만 새 이력으로)
- 설치: Inno Setup 6 (`winget install JRSoftware.InnoSetup`, 사용자 범위 설치), `packaging/hwpgpt.iss`. `lzma2/ultra64`는 ISCC 메모리 부족 → `LZMAUseSeparateProcess=yes`
- 설치 위치 `%LOCALAPPDATA%\HWP_GPT\app`, AppId 고정(업데이트는 같은 AppId로 덮어쓰기). 업데이트 때 `_internal`·`codex` 폴더는 지우고 새로 (예전 파일 섞임 방지)
- 업데이트 확인은 `https://github.com/byunhyunjin2/hwp-gpt/releases/latest/download/latest.json` (API 아님, 시간당 60회 제한 회피). 설치 파일 SHA256을 `latest.json`과 대조. 조용히 설치(`/VERYSILENT`) 후 `[Run]`으로 패널 재실행
- 패널 안 업데이트 실제 확인 (2026-10-22): 1.0.0 → [업데이트] → 1.0.1 설치·재실행. 받은 설치 파일은 다음 실행 때 `updater.cleanup`이 지움
- Codex 동봉 파일: 본체 + `codex-code-mode-host.exe`(필수, MCP 도구 호출) + `codex-resources\*.exe` + `codex-path\rg.exe` + `codex-package.json`. `voice` 폴더·최상위 중복 사본은 불필요 (2026-10-22 시험)
- **배포는 시험 → 사용자 승인 → `release.py publish`** (사용자 결정 2026-10-22). 오류신고 버튼은 만들지 않음 (사용자 결정)
- 아이콘: `src/hwpgpt/assets/hwpgpt.ico` ← `packaging/make_icon.py` (Pillow, 개발 PC에서만). pywebview(WinForms)는 `webview.start(icon=)`가 없으면 실행 파일의 아이콘을 창에 씀
- 첨부: 그림은 Codex `--image`(exec·resume 둘 다 지원, 0.163.0 확인), 문서는 글만 뽑아 프롬프트에 (`attachments.py`, 파일당 15,000자). hwp는 `olefile`, 나머지는 표준 라이브러리. 첨부도 OpenAI로 전송됨을 README에 안내
- 끌어다 놓기 파일 경로: pywebview(EdgeChromium)는 Python으로 등록한 drop 처리기(`window.dom.document.events.drop`)가 있을 때만 `pywebviewFullPath`를 채움. JS만으로는 경로를 알 수 없음
- PowerShell 5에 한글 인자를 넘기면 깨짐 → 릴리스 노트는 `release.py`가 UTF-8로 직접 씀
- 커밋 이메일은 GitHub noreply

## 패널 설정 (2026-10-22)
- `%APPDATA%\HWP_GPT\settings.json`: `theme`(dark|light), `model`(빈 값 = Codex 기본)
- 모델 목록은 `%APPDATA%\HWP_GPT\codex\models_cache.json`(Codex가 받아 둠)의 `visibility == "list"`. 2026-10-22 기준 GPT-6.1-Sol, GPT-6-Astra, GPT-6-Sol, GPT-6-Luna, GPT-5.6-Sol/Terra/Luna. 고른 모델로 실제 요청한 확인은 아직
- 투명도 기능은 사용자 요청으로 삭제 (다크/라이트 버튼으로 대체)

## Claude 앱 안에서 개발할 때 주의 (2026-10-22)
- Claude 데스크톱 앱(MSIX 패키지) 안에서 띄운 프로세스는 `%APPDATA%` 쓰기가 `C:\Users\user\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\`으로 **가상화**됨 → 거기서 한 Codex 로그인·세션은 일반 실행(탐색기·바탕화면 아이콘)에서 안 보임
- 사용자처럼 시험하려면 탐색기로 실행: `Start-Process explorer.exe start_hwp_gpt.bat`
- 실제 `AppData`에도 로그인 완료 (2026-10-22 11:21, `spike/login_diag.py`로 확인)

## pywebview
- `js_api` 객체의 **공개 속성은 전부 JS로 노출하려고 재귀 탐색**함 → 창·COM 객체를 공개 속성으로 두면 재귀 깊이 초과·UI 스레드 오류. 내부 상태는 반드시 `_` 접두사
- **패널 창을 다른 스레드에서 건드릴 때 `win32gui.SetWindowLong` 금지** — 대상 창 스레드 응답을 기다리는 동안 GIL을 쥐어 화면 스레드와 교착 (2026-10-22 시험). `SetWindowPos`·`MoveWindow`·`ShowWindow`·`SetParent`는 GIL을 풂. 스타일 변경은 `dock.set_window_long`(ctypes)
- 진행률은 Codex `--json` 이벤트 기준 단계값(10·25·45·60·85·95%) — 실제 남은 시간 예측이 아님
- AI 지침 이번 변경(연도 표기·leftover·작성일) 후 **Codex 실제 재시험은 아직** — 시험 문서로 연도 갱신 + 예산 변경 확인 필요
- 패널 멈춤 진단: `py-spy dump --pid <pythonw PID>` (pip로 임시 폴더에 설치해서)
- 창 위치는 **보이는 테두리 기준**으로 맞춘다: Win10/11 창은 `GetWindowRect`에 투명 크기조절 테두리(약 7px)가 포함돼 틈이 생김 → `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`로 보정
- 한글 안 모드에서 패널 왼쪽이 한글 문서 화면에 가려져 잘려 보이는 경우가 사용자 화면에서 관찰됨 (2026-10-22, 원인 미확인)
- 패널 창 핸들은 `win32gui.FindWindow(None, "HWP_GPT")`로 찾음 (창 제목 = TITLE)
- 화면 미리보기: `src/hwpgpt/ui`에서 `python -m http.server` 후 `index.html?mock` (file://은 미리보기 창에서 정적 사본이라 ?mock이 안 먹음)

## 관련 자원
- hwp-cli v1.3.1 (`hwp.exe`): 한컴 없이 HWP/HWPX 읽기·변환·렌더 — 검증·테스트 보조용
- hj-hwpx-codex (byunhyunjin2): 같은 사용자층 대상 Codex 플러그인, 규칙·검증 로직 참고처
- 이름: HANCOM_GPT → **HWP_GPT** (2026-10-21, 한컴 상표 오해 방지). 한컴 공식 제품이 아님을 README에 명시. 로컬 폴더·레포·`%APPDATA%\HWP_GPT` 모두 새 이름
