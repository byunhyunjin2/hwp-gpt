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
- **수정은 기본이 '문서 전체 같은 문구'** → 특정 곳은 `lines`(줄 번호)로 그 번째만. 짧은 숫자("6", "4.0")는 위치 없이 거부 (2026-10-22 사용자 사례)
- **그림 첨부 = 고칠 범위** (사용자 결정 2026-10-22): 위치 없는 수정 거부, 문서 전체 점검 안 함. 금액 점검은 금액을 바꾼 요청에서만
- 되돌리기는 항목별(↶) — 요청 단위 버튼은 사용자 요청으로 없앰. 되돌린 항목은 ↷로 다시 적용(redo: 기록한 자리를 apply 순서대로 앞에서부터, 글이 원래 글인지 확인 후)
- 개인정보 수정 허용은 **요청 한 번만** (사용자 결정 2026-10-25): 도구 서버가 요청마다 새로 떠서 `HWPGPT_PERSONAL` 환경값이 다음 요청에 남지 않음. 실제 ChatGPT 시험(가짜 명단): 허용 전엔 `[[개인정보 확인]]`만 답하고 문서 그대로, 허용 후엔 요청한 이름·연락처만 바뀜, 연도 바꾸기 같은 일반 요청은 묻지 않음
- 한글 문단 모양 `HParaShape.BreakNonLatinWord`: **0 = 어절, 1 = 글자(새 문서 기본값)** — 글자면 단어가 줄 끝에서 갈라짐 (2026-10-25 시험: 줄 끝 위치로 확인. 창이 숨어 있으면 줄 위치가 계산되지 않아 `Visible=True` 필요)
- 고친 문단 정리는 글머리가 같은 이웃만 따라 함 — 글머리 없는 문단은 제목·본문을 구별할 수 없어 정렬을 건드리지 않음. ↶ 되돌리기는 글만 되돌리고 문단 모양은 그대로
- 설치 파일: 다른 화면을 다 꺼도(`DisableReadyPage=yes`) Inno가 '설치 준비 완료'를 띄움 → 업데이트일 때는 `ShouldSkipPage(wpReady)`로 건너뜀. 설치된 버전은 HKCU 제거 목록 `{AppId}_is1`의 `DisplayVersion`. 패널이 켜져 있으면 '응용 프로그램 자동 닫기' 화면이 잠깐 나오지만 `CloseApplications=force`라 그대로 진행 (2026-10-25 1.0.5→1.0.6 직접 실행 시험)
- 한글 표 줄: `TableDeleteRow`(커서 칸의 줄 지우기)·`TableInsertLowerRow`(아래에 줄 넣기). 표 안인지는 `ParentCtrl.CtrlID == "tbl"`, 칸 주소는 `KeyIndicator()` 마지막 값 "(A3): …", 열의 맨 아래 칸은 `TableColPageDown`
- **서식·표·넣기 COM (2026-11-11 시험 전용 인스턴스로 확인, 한컴 2022):**
  - 글자 모양 `CharShape`(HCharShape: Bold·Italic·UnderlineType·StrikeOutType·TextColor·Height=pt×100·FaceNameHangul/Latin+FontType=1), 문단 모양 `ParagraphShape`(AlignType 0양쪽 1왼쪽 2오른쪽 3가운데 4배분, LineSpacingType=0이면 LineSpacing=%). **문단 여백·들여쓰기(LeftMargin·RightMargin·Indentation) 값은 1mm = 567(HWPUNIT×2), 홀수면 다른 단위로 읽힘**(1000→6px, 1001→28px, 80dpi 쪽 그림으로 측정) → 항상 짝수. 음수 Indentation = 내어쓰기
  - 새 문단 `BreakPara`, 쪽 나누기 `BreakPage`, 문단 지우기 = `MoveParaBegin`→`MoveSelParaEnd`→`MoveSelRight`→`Delete`
  - 표: `TableCreate`(HTableCreation Rows·Cols, **WidthType=0이면 본문 폭**, 기본값이면 열마다 21.6mm. 만든 뒤 커서는 A1 칸). `h.CellShape.Item("Width")`는 칸이 아니라 **표 전체 폭**, 칸 이동 `TableRightCell`/`TableLowerCell`, A1은 `TableColBegin`+`TableColPageUp`, 칸 주소는 `KeyIndicator()` 마지막 값. **칸 글 읽기 = `MoveListBegin`→`Select`→`MoveListEnd`→saveblock** (`TableCellBlock`+saveblock은 표 전체를 돌려줌). 열 `TableInsertLeftColumn`/`TableInsertRightColumn`/`TableDeleteColumn`, 합치기 `TableCellBlock`→`TableCellBlockExtend`→칸 이동→`TableMergeCell`
  - 표 칸 안에서 표 밖(표가 든 문단)으로: `SetPosBySet(ParentCtrl.GetAnchorPos(0))`
  - 그림 `InsertPicture(path, True, 0, False, False, 0, 0, 0)` — 인자 8개 다 줘야 함. 셋째 인자 2 = 칸 크기에 맞춤(칸 폭 × 칸 높이라 납작해짐 → 원래 크기로 비율을 알아 둔 뒤 높이를 다시 맞춤), 3 = 칸 안에서 비율 유지(칸 높이가 작으면 아주 작아짐). 그림 목록은 `HeadCtrl`의 `gso` 중 `UserDesc == "그림"`(표 안 포함, 문서 순서). **원래 크기로 들어가 본문 폭을 넘음**(3000px → 794mm) → `ctrl.Properties`의 Width·Height를 줄여 다시 넣음. 본문 폭 = `PageSetup`의 HSecDef.PageDef `PaperWidth - LeftMargin - RightMargin`
  - 머리말·꼬리말 `HeaderFooter` + **`HSet.SetItem("HeaderFooterCtrlType", 0 머리말 / 1 꼬리말)`** (`Type`은 양쪽·홀·짝 쪽) → 글 → `CloseEx`. 그 글은 `GetTextFile("UNICODE")`에 안 나오고 HWPML2X에만. 쪽 번호 `PageNumPos` DrawPos 5 = 아래 가운데, 3 = 위 오른쪽(HWPML `Pos`로 확인). 각주 `InsertFootnote`→글→`CloseEx`
  - 메모 `InsertFieldMemo`→글→`CloseEx`: 선택한 글을 필드로 감쌈(선택 없으면 커서 근처 낱말). **메모 경계를 걸치는 글은 찾기로 못 찾음** → 문단 전체(`MoveParaBegin`→`MoveSelParaEnd`)에 달면 문단 안 글은 다 찾아짐. 메모 컨트롤 ID `%%me`, 지우기는 `HeadCtrl` 돌며 `DeleteCtrl`. `DeleteAllMemo` 같은 액션 이름은 없음
  - 누름틀 `CreateField(안내, 도움말, 이름)`, `GetFieldList(0,0)`(이름이 `\x02`로 구분), `GetFieldText`/`PutFieldText`
  - 쪽 그림 `CreatePageImage(path, 쪽-1, dpi, 24, 형식)`: 형식과 상관없이 **24비트 BMP**로 저장(확장자도 .bmp로 바뀜) → `bmp_to_png`(표준 라이브러리)로 PNG. **커서가 표 칸에 있으면 그 칸만 그림** → 먼저 `SetPos(0,0,0)`. **경로가 상대 경로면 한글이 멈춤** → 절대 경로
  - MCP 도구가 `Image`를 돌려주면 Codex(0.167)가 그림으로 받아 봄 (실제 ChatGPT 시험)
  - 컨트롤 ID: 표 `tbl`, 그림 `gso`(UserDesc 그림), 메모 `%%me`, 각주 `fn`(안에 `atno`), 머리말 `head`, 꼬리말 `foot`, 쪽 번호 `pgnp`. 자리는 `GetAnchorPos(0)`의 List·Para·Pos. 같은 문단에 뒤에 넣은 컨트롤 때문에 Pos가 밀림
  - 문서 끝 문단에 표를 넣으면 한글이 표 뒤에 빈 문단을 하나 더 만듦. 그림은 새 문단에 넣으므로 지울 때 빈 문단도 지워야 원래대로
  - 열을 넣으면 표가 본문 밖으로 넓어짐. 표 폭 = 칸에 커서가 있을 때 `h.CellShape.Item("Width")`. `TablePropertyDialog` Width는 무시되고, 모든 칸 선택 후 `TableResizeLeft/Right`가 칸마다 약 1mm씩
  - 빈 문단은 `GetTextFile("UNICODE","saveblock")`이 None
- **서식·표·넣기 ↶·↷ (2026-11-11)**: 도구 서버가 수정마다 `undo`/`redo` 작업 목록을 남기고 패널이 자기 HwpBridge로 실행(`app.UNDO_OPS`만). 되돌린 결과는 한글 내부 번호(개체 ID·쌓는 순서·머리말 일련번호·메모 시각)만 다르고 내용은 같음. 서식을 되돌리면 같은 모양 글이 두 덩어리(모양 ID는 원래와 같음)로 남음
- 창 찾기: 한글 창 클래스 `HwndWrapper[Hwp.exe;…]`의 실행 파일 이름 대소문자는 띄운 방법에 따라 다름(COM으로 띄우면 `hwp.exe`) → 대소문자 무시
- 한글 안 모드에서 패널은 한글 창의 자식이고 문서 창(HwpMainEditWnd, WS_CLIPSIBLINGS 있음)과 형제. 둘 다 DPI 인식 system. 패널보다 위에 형제 창이 생기면 0.2초 안에 맨 위로
- 로그인: `codex login`은 브라우저 로그인을 마칠 때까지 포트 1455를 잡고 기다림 → 패널은 5분 제한(`LOGIN_TIMEOUT`)
- 형광펜 있는지 확인: `GetTextFile("HWPML2X")`의 `<MARKPENBEGIN` (HTML 내보내기에는 안 나옴). 표 전체 칸 선택: 표 앞(`GetAnchorPos`) → `FindCtrl` → `ShapeObjTableSelCell` → `TableCellBlockExtend` 두 번
- 패널 창은 `hidden=True`로 만들고 `_dock_loop`가 오른쪽에 둔 뒤 `window.show()` (2026-10-25 실제 창 시험: 숨긴 창도 FindWindow로 찾히고, 옮긴 자리 그대로 보임)
- 옆에 붙이기: 맞닿은 경계를 패널·한글 어느 쪽에서 끌어도 다른 쪽이 맞춰짐. 패널 자리는 놓은 뒤 실제 자리를 다시 읽어 기억 (DPI 반올림으로 1px 어긋나도 사용자가 끈 것으로 오해하지 않게)
- 되돌리기: 한글 `GetPos()`로 바꾼 자리를 기록, 거꾸로 `SetPos` → `MoveSelRight` → 글 확인(`GetTextFile("UNICODE","saveblock")`) → 원래 글. **`MarkPenDelete`는 선택을 풀어 버림** → 원래 글을 넣은 뒤 다시 선택해서 지움
- AI 시험용: `tools_server.main()`의 한글 연결만 글 파일로 바꾼 서버로 실제 ChatGPT 행동을 시험할 수 있음 (Codex는 MCP 서버에 `mcp_servers.*.env`로 준 환경변수만 넘김)
- 요일 검사는 수정 후 문자열(`replace`) 안의 모든 날짜에 대해 수행
- 개인정보 문단 보호: 전화·이메일·주민번호 패턴, 또는 낱말(담당자·성명·연락처·전화(번호)·휴대전화·이메일(주소)·주소)이 **이름표로** 쓰일 때 — `담당자:` 꼴이거나 줄 맨 앞(글머리 뒤)에 뒤에 한글이 붙지 않은 낱말 (2026-11-11 좁힘: '주소지 이전 안내'는 안 막음). 표에서는 1행 머리글(`PERSONAL_COL_RE`: 이름·성명·학번·연락처 등) 아래의 2행 이상 데이터 칸과, 학번·연락처 칸 앞뒤의 이름 칸도 보호 (2026-11-11 보완)
- 물품 표 합계 점검(`check_table_sums`): `(수량, 단가, 금액)` 3칸이 매칭되면 `k += 3`으로 건너뛰어 앞 행 금액과 뒷 행 `수량=1`이 곱해지는 행 경계 오탐을 막음 (2026-11-11)
- 세션·첨부 임시 파일(`%APPDATA%\HWP_GPT\sessions\*.jsonl`, `*.attached.txt`): 요청(`run_turn`)이 끝날 때 `finally`에서 바로 지우고 패널 시작 때도 정리해 문서 본문이 디스크에 남지 않게 함 (2026-11-11)
- **서식·표 모양·문단·그림은 사용자가 말한 것만 바로** (사용자 결정 2026-11-11). 표 열 지우기·개인정보 칸 덮어쓰기·개인정보 문단 지우기는 허락 필요. 이 수정들은 패널 ↶ 없이 한글 Ctrl+Z로 되돌림
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

## 미리 보기·문서 검토·요청 버튼·신구대조표 (2026-11-11)
- **고치기 전 미리 보기**(설정 `preview`): 도구 서버에 `HWPGPT_PREVIEW=1` → `apply_edits`는 규칙 검사만 하고 바꾸지 않은 채 `proposed`로 남김. 서식·표·넣기 도구는 거절(글 바꾸기만 제안). 패널이 체크 목록을 보여 주고 고른 것만 `apply_proposed`로 적용(AI 다시 안 부름), 적용한 것은 ↶ 목록에 들어감. 실제 ChatGPT로 확인: 제안 4개, 문서 그대로, 고른 1개만 적용
- **문서 검토** 버튼: AI 없이 `rules.review_document` — 계산식·표 합계·사업 예산, 요일이 달력과 다른 날짜·없는 날짜, 연도 오타(`20260북구` 꼴: 19xx/20xx 뒤 숫자 하나 + 한글). 빨간 표시만, 사용량 0
- **자주 쓰는 요청** 버튼: 설정 `presets`(최대 20개, 200자). 누르면 입력창에 넣기만(고쳐서 보낼 수 있게). 기본 3개
- **신구대조표**: 이 문서에서 패널로 바꾼 글(되돌리지 않은 것)을 문서 끝에 제목 문단 + '연번|수정 전|수정 후|곳' 표로(`HwpBridge.append_table`, `MoveDocEnd`). ↶ = 표 지우기 → 제목 문단 지우기, 실기 시험 통과

## Codex
- 개발 PC의 예전 폴더 `HWP_GPT`는 2026-10-26 정리로 없음 → 개발 `.venv`는 이 레포 안에. **공식 Codex `rust-v0.167.0`을 이 레포 `spike\bin`(git 제외)에 새로 준비함**(2026-11-11, zip 206MB SHA256 `94b51ca8…2f16` 게시값 일치, 실행 파일 서명 OpenAI OpCo Valid, `codex-path\rg.exe`만 서명 없음). 개발판은 `HWPGPT_CODEX` → `spike\bin` → Codex 앱 해시 폴더 순
- 사용자 PC Codex 경로는 해시 폴더: `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` — **업데이트 시 바뀜, 하드코딩 금지**. 배포본은 Codex를 번들
- `codex login status` → "Logged in using ChatGPT" 이면 구독으로 동작
- **API 키 없이 ChatGPT 로그인만으로 대화·MCP 도구 호출·한글 수정·대화 이어가기 모두 동작 확인** (2026-10-22). 실행 옵션은 `docs/spike-results.md`
- **로그인 방식 결정 (사용자, 2026-10-22): (a) 전용 `CODEX_HOME=%APPDATA%\HWP_GPT\codex`에 패널에서 1회 로그인.** 공식 Codex로 로그인·한글 수정까지 검증. (`--ignore-user-config`로 기존 로그인을 빌리는 방식 b는 채택 안 함)
- 배포용 Codex: openai/codex 릴리스의 `codex-x86_64-pc-windows-msvc.exe.zip`, **SHA256을 릴리스 digest와 대조 + OpenAI 서명 확인 후** 동봉 (spike-results)
- 1회 요청 토큰: 절감 전 약 9.4만 → **절감 후 약 3.2만** (긴판 시험 문서 기준, 2026-10-22). 대부분은 모델 호출마다 붙는 고정 부분(도구 정의·지침)
- 도구 7개 추가 후(2026-11-11, 짧은 가짜 문서): 서식+열+칸 2개+문단+쪽 번호 한 요청 입력 5.9만(캐시 4.8만), 쪽 그림 확인 요청 3.0만. 도구 설명(docstring)은 짧게 유지
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
- GitHub CDN은 `releases/latest/download/latest.json` 이동을 몇 분 캐시 → 확인할 때 `?t=` 붙임. 사용자가 GitHub 웹에서 README를 고칠 수 있음 → 배포 전 pull
- 패널 안 업데이트 실제 확인 (2026-10-22): 1.0.0 → [업데이트] → 1.0.1 설치·재실행. 받은 설치 파일은 다음 실행 때 `updater.cleanup`이 지움
- Codex 동봉 파일: 본체 + `codex-code-mode-host.exe`(필수, MCP 도구 호출) + `codex-resources\*.exe` + `codex-path\rg.exe` + `codex-package.json`. `voice` 폴더·최상위 중복 사본은 불필요 (2026-10-22 시험)
- **배포는 시험 → 사용자 승인 → `release.py publish`** (사용자 결정 2026-10-22). 오류신고 버튼은 만들지 않음 (사용자 결정)
- 아이콘: `src/hwpgpt/assets/hwpgpt.ico` ← `packaging/make_icon.py` (Pillow, 개발 PC에서만). pywebview(WinForms)는 `webview.start(icon=)`가 없으면 실행 파일의 아이콘을 창에 씀
- 첨부: 그림은 Codex `--image`(exec·resume 둘 다 지원, 0.163.0 확인), 문서는 글만 뽑아 프롬프트에 (`attachments.py`, 파일당 15,000자). hwp는 `olefile`, 나머지는 표준 라이브러리. 첨부도 OpenAI로 전송됨을 README에 안내
- 끌어다 놓기 파일 경로: pywebview(EdgeChromium)는 Python으로 등록한 drop 처리기(`window.dom.document.events.drop`)가 있을 때만 `pywebviewFullPath`를 채움. JS만으로는 경로를 알 수 없음
- 붙여넣기: 화면(JS)은 클립보드 그림을 data URL로만 받음 → `save_pasted_image`가 파일로 저장. 탐색기 복사 파일은 JS로 경로를 알 수 없어 `win32clipboard`의 CF_HDROP으로 읽음
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
- 실기 테스트(`-m hwp`)의 'Windows fatal exception 0x800706be'는 한글 종료 뒤 `CoUninitialize`가 COM 연결을 풀며 COM 안에서 처리되는 RPC 실패를 pytest faulthandler가 찍은 것 (2026-11-11 확인, 테스트 정리 동안만 끔)
- 진행률은 Codex `--json` 이벤트 기준 단계값(10·25·45·60·85·95%) — 실제 남은 시간 예측이 아님
- AI 지침 이번 변경(연도 표기·leftover·작성일) 후 **Codex 실제 재시험은 아직** — 시험 문서로 연도 갱신 + 예산 변경 확인 필요
- 패널 멈춤 진단: `py-spy dump --pid <pythonw PID>` (pip로 임시 폴더에 설치해서)
- 창 위치는 **보이는 테두리 기준**으로 맞춘다: Win10/11 창은 `GetWindowRect`에 투명 크기조절 테두리(약 7px)가 포함돼 틈이 생김 → `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`로 보정
- 한글 안 모드에서 패널 왼쪽이 가려진 현상 (2026-10-22 보고) → 2026-11-11 재현 안 됨, 맨 위로 되돌리는 처리 추가 (위 항목)
- 패널 창 핸들은 `win32gui.FindWindow(None, "HWP_GPT")`로 찾음 (창 제목 = TITLE)
- 화면 미리보기: `src/hwpgpt/ui`에서 `python -m http.server` 후 `index.html?mock` (file://은 미리보기 창에서 정적 사본이라 ?mock이 안 먹음)

## 관련 자원
- hwp-cli v1.3.1 (`hwp.exe`): 한컴 없이 HWP/HWPX 읽기·변환·렌더 — 검증·테스트 보조용
- hj-hwpx-codex (byunhyunjin2): 같은 사용자층 대상 Codex 플러그인, 규칙·검증 로직 참고처
- 이름: HANCOM_GPT → **HWP_GPT** (2026-10-21, 한컴 상표 오해 방지). 한컴 공식 제품이 아님을 README에 명시. 로컬 폴더·레포·`%APPDATA%\HWP_GPT` 모두 새 이름
