"""규칙 엔진: AI가 낸 수정안을 문서에 반영하기 전에 검사한다. 순수 함수만 둔다.

- 날짜는 원래 표기(점·띄어쓰기·년월일·괄호)를 유지하고 요일은 달력으로 계산
- 보호: 식별번호(학번 등) 안의 숫자, 개인정보 문단. 그 밖의 내용(금액 포함)은 고칠 수 있다 (사용자 결정 2026-10-22)
- 금액 점검: 산출내역 계산식(A×B = C), 표의 항목 합과 '합계', '합계'와 본문 '사업 예산'
"""
import re
from dataclasses import dataclass
from datetime import date

WEEKDAYS = "월화수목금토일"

DATE_RE = re.compile(
    r"(?P<y>(?:19|20)\d{2})(?P<s1>\s*[.년]\s*)(?P<m>\d{1,2})(?P<s2>\s*[.월]\s*)"
    r"(?P<d>\d{1,2})(?P<s3>\s*[.일]?)(?:(?P<sw>\s*)\((?P<w>[월화수목금토일])\))?"
)
PHONE_RE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RRN_RE = re.compile(r"\b\d{6}-[1-4]\d{6}\b")
_KEY = r"(?:담당자|성명|연락처|휴대\s*전화|전화(?:\s*번호)?|이메일(?:\s*주소)?|주소)"
# 낱말이 '이름표'로 쓰인 때만 (2026-11-11 점검: '주소지 이전 안내'·'전화위복'까지 막았음)
# — 'OO:' 꼴이거나, 줄 맨 앞(글머리 뒤)에 낱말 그대로(뒤에 한글이 붙지 않음)
PERSONAL_LABEL_RE = re.compile(rf"{_KEY}\s*[:：]|^\s*(?:[-•·○●◦▪■□◆◇▶※*]\s*)?{_KEY}(?![가-힣])", re.M)
PERSONAL_COL_RE = re.compile(rf"^\s*(?:{_KEY}|이름|학번|주민\s*(?:등록\s*)?번호)\s*$")
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
ID_RE = re.compile(r"\d{7,}")


@dataclass
class Edit:
    find: str
    replace: str
    reason: str
    nths: tuple[int, ...] | None = None  # 바꿀 것만: 문서에서 find의 몇 번째들(0부터). None = 전부
    context: tuple[str, ...] = ()        # 그 위치들의 줄 (보호 검사는 이 줄들로만)


VAGUE_RE = re.compile(r"[\d.,%\s]{1,6}")  # "6", "4.0", "100%" 같은 짧은 숫자


def is_vague(find: str) -> bool:
    """위치 없이 바꾸면 문서 곳곳이 같이 바뀔 짧은 문구."""
    s = find.strip()
    # "OOO", "○○○", "XXX" 같은 같은 글자 반복(빈칸 표시)은 더 긴 "OOOOO학과장" 속까지 바뀜 → 줄 번호 필요 (2026-11-11 실제 공문)
    return len(s) <= 1 or bool(VAGUE_RE.fullmatch(s)) or len(set(s.replace(" ", ""))) == 1


@dataclass
class Check:
    text: str
    note: str


def parse_date(s: str) -> tuple[date, str] | None:
    """날짜 문자열 전체를 읽어 (날짜, 표기 템플릿)을 돌려준다. 날짜가 아니면 None."""
    m = DATE_RE.fullmatch(s.strip())
    if not m:
        return None
    try:
        d = date(int(m["y"]), int(m["m"]), int(m["d"]))
    except ValueError:
        return None
    mpad = "02" if len(m["m"]) == 2 and m["m"].startswith("0") else ""
    dpad = "02" if len(m["d"]) == 2 and m["d"].startswith("0") else ""
    tpl = f"{{y}}{m['s1']}{{m:{mpad}}}{m['s2']}{{d:{dpad}}}{m['s3']}"
    if m["w"]:
        tpl += f"{m['sw']}({{w}})"
    return d, tpl


def format_date(d: date, template: str) -> str:
    return template.format(y=d.year, m=d.month, d=d.day, w=WEEKDAYS[d.weekday()])


def _weekday_problems(text: str) -> list[str]:
    """text 안의 날짜 중 괄호 요일이 달력과 다른 것."""
    out = []
    for m in DATE_RE.finditer(text):
        if not m["w"]:
            continue
        try:
            real = WEEKDAYS[date(int(m["y"]), int(m["m"]), int(m["d"])).weekday()]
        except ValueError:
            out.append(f"{m.group(0)}: 없는 날짜")
            continue
        if real != m["w"]:
            out.append(f"{m.group(0)}: 요일이 달력과 다름(실제 {real})")
    return out


def _is_personal(context: str) -> bool:
    return bool(
        PHONE_RE.search(context) or EMAIL_RE.search(context) or RRN_RE.search(context)
        or PERSONAL_LABEL_RE.search(context)
    )


def _inside_number(context: str, start: int, end: int) -> str | None:
    """context[start:end]가 식별번호 숫자에 걸치는지."""
    for m in ID_RE.finditer(context):
        if m.start() < end and start < m.end():
            return "식별번호(학번 등) 숫자"
    return None


def is_protected(text: str, context: str) -> str | None:
    """context 속 text를 바꾸면 안 되는 이유. 바꿔도 되면 None."""
    if _is_personal(context):
        return "개인정보가 있는 문단"
    i = context.find(text)
    while i >= 0:
        reason = _inside_number(context, i, i + len(text))
        if reason:
            return reason
        i = context.find(text, i + 1)
    return None


def _lines(doc_text: str) -> list[tuple[int, int, str]]:
    """빈 줄을 뺀 줄들 (시작, 끝, 글)."""
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"[^\r\n]+", doc_text) if m.group().strip()]


# 개인 이력 묶음: 이력서·경력·학력 같은 제목 줄부터 서명 줄까지는 연도 갱신 등에서 절대 바꾸지 않는다 (2026-11-13:
# 결과보고서의 강사 이력서 학력·경력·자격 날짜가 '옛 연도 남음'으로 표시돼 바뀔 수 있었음)
# 서류 제목만 (앞에 '강사'·'개인' 같은 짧은 말 허용). '경력사항'·'학력사항'은 계획서 표의 열 이름에도 쓰여
# 그 아래 행사 일시까지 보호돼 바꾸지 못했음 → 뺌 (2026-11-13 점검)
HISTORY_START_RE = re.compile(r"[가-힣·()]{0,8}?(?:이력서|이력카드|경력증명서|경력확인서|재직증명서|자기소개서|강사카드|강사프로필)")
HISTORY_END_RE = re.compile(r"\(\s*서\s*명\s*\)|\(\s*인\s*\)|서명\s*$")
HISTORY_MAX_LINES = 150


def history_zones(doc_text: str) -> list[tuple[int, int]]:
    """개인 이력 묶음의 (시작, 끝) 글자 위치. 제목 줄(공백 무시 전체가 이력서 등)에서 서명 줄까지, 없으면 150줄까지."""
    ls, zones, i = _lines(doc_text), [], 0
    while i < len(ls):
        if HISTORY_START_RE.fullmatch(re.sub(r"\s", "", ls[i][2])):
            j = i
            while j + 1 < len(ls) and j - i < HISTORY_MAX_LINES and not HISTORY_END_RE.search(ls[j][2]):
                if j > i and HISTORY_START_RE.fullmatch(re.sub(r"\s", "", ls[j + 1][2])):
                    break  # 다음 이력서가 바로 시작
                j += 1
            zones.append((ls[i][0], ls[j][1]))
            i = j + 1
        else:
            i += 1
    return zones


def _in_zone(pos: int, zones: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in zones)


def _occurrence_contexts(doc_text: str, needle: str) -> list[tuple[int, str]]:
    """needle이 나오는 곳마다 (위치, 그 줄). 표 이름 칸(이름·성명 열이 있는 표에서 번호 옆 짧은 한글)은 '성명: '을 붙여 개인정보로."""
    ls = _lines(doc_text)
    has_name_col = any(re.fullmatch(r"\s*(?:이름|성\s*명)\s*", t) for _, _, t in ls)
    out, pos = [], doc_text.find(needle)
    while pos >= 0:
        idx = next((k for k, (a, b, _) in enumerate(ls) if a <= pos < b), None)
        if idx is None or pos + len(needle) > ls[idx][1]:  # 여러 줄에 걸친 글: 걸친 줄을 모두 문맥으로
            p = doc_text[doc_text.rfind("\n", 0, pos) + 1: doc_text.find("\n", pos + len(needle)) % (len(doc_text) + 1)]
        else:
            p = ls[idx][2]
            if has_name_col and not PERSONAL_COL_RE.match(p) and re.fullmatch(r"\s*[가-힣]{2,5}\s*", p):
                near = " ".join(t for _, _, t in ls[max(0, idx - 2): idx + 3])
                if PHONE_RE.search(near) or EMAIL_RE.search(near) or RRN_RE.search(near) or ID_RE.search(near):
                    p = f"성명: {p}"
        out.append((pos, p))
        pos = doc_text.find(needle, pos + len(needle))  # str.count·한글 찾기와 같은 겹치지 않는 순서
    return out


PROTECTED_NOTE = "보호 대상이라 바꾸지 않음"
HISTORY_NOTE = "개인 이력(이력서·학력·경력·자격)"


def validate_edits(doc_text: str, edits: list[Edit], need_lines: bool = False,
                   personal: bool = False) -> tuple[list[Edit], list[Check]]:
    """통과한 수정안과, 거부되어 확인(빨강)으로 돌릴 항목. need_lines: 그림을 첨부한 요청 — 위치 없는 수정은 모두 거부.
    personal: 사용자가 패널에서 이번 요청에 한해 개인정보 수정을 허용함 — 보호 검사를 건너뜀."""
    ok: list[Edit] = []
    checks: list[Check] = []
    for e in edits:
        if not e.find or e.find not in doc_text or e.nths == ():
            checks.append(Check(e.find, "문서에서 찾지 못함" + (" (지정한 줄에 없음)" if e.nths == () else "")))
            continue
        if e.nths is None and need_lines:
            checks.append(Check(e.find, "첨부한 그림 부분만 고치는 요청이라 위치 없는 수정은 하지 않음 — 그림 속 줄 번호(lines)를 주세요"))
            continue
        if e.nths is None and is_vague(e.find):
            checks.append(Check(e.find, "짧은 문구라 문서 곳곳이 같이 바뀔 수 있어 바꾸지 않음 — 바꿀 줄 번호(lines)를 함께 주세요"))
            continue
        if not personal:
            # 나오는 곳마다 따로 검사: 보호할 곳만 빼고 나머지는 바로 바꾼다 (한 곳 때문에 전부 '확인 필요'로 돌리던 문제, 2026-11-13)
            occ = _occurrence_contexts(doc_text, e.find)
            zones = history_zones(doc_text)
            want = range(len(occ)) if e.nths is None else [k for k in e.nths if k < len(occ)]
            bad = {}
            for k in want:
                pos, para = occ[k]
                if r := (HISTORY_NOTE if _in_zone(pos, zones) else is_protected(e.find, para)):
                    bad[k] = r
            if bad:
                keep = tuple(k for k in want if k not in bad)
                reason = next(iter(bad.values()))
                if not keep:
                    checks.append(Check(e.find, f"{PROTECTED_NOTE}: {reason}"))
                    continue
                if any(r != "식별번호(학번 등) 숫자" for r in bad.values()):  # 학번 속 숫자는 당연히 그대로 — 알릴 것 없음
                    checks.append(Check(e.find, f"{PROTECTED_NOTE}: {reason} — 그 {len(bad)}곳만 그대로 두고 나머지 {len(keep)}곳은 바꿈"))
                e = Edit(e.find, e.replace, e.reason, keep, e.context)
        bad = _weekday_problems(e.replace)
        if bad:
            checks.append(Check(e.find, "요일 확인 필요 — " + "; ".join(bad)))
            continue
        ok.append(e)
    return ok, checks


def _amounts(pattern: str, text: str) -> list[int]:
    return [int(x.replace(",", "")) for x in re.findall(pattern, text)]


def check_budget(doc_text: str) -> list[Check]:
    """본문 '사업 예산 N원'과 '합계 N원'이 다르면 확인 항목 하나.
    표마다 소계 '합계'가 여러 개일 수 있으므로, 사업 예산과 같은 합계가 하나도 없을 때 가장 큰 합계만."""
    budget = _amounts(r"사업\s*예산\s*([\d,]+)\s*원", doc_text)
    totals = _amounts(r"합\s*계\s*([\d,]+)\s*원", doc_text)
    if not budget or not totals or budget[0] in totals:
        return []
    t = max(totals)
    return [Check(f"{t:,}", f"합계 {t:,}원이 사업 예산 {budget[0]:,}원과 다름 — 표의 '합계'와 개요의 '사업 예산' 중 하나를 맞춰야 함")]


YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def changed_years(pairs: list[tuple[str, str]]) -> set[str]:
    """적용된 (find, replace) 쌍에서 다른 연도로 바뀐 옛 연도들 (예: 2026학년도→2027학년도 → {"2026"})."""
    old = set()
    for f, r in pairs:
        yf, yr = YEAR_RE.findall(f), YEAR_RE.findall(r)
        if len(yf) == len(yr):
            old |= {a for a, b in zip(yf, yr) if a != b}
    return old


def leftover_years(doc_text: str, old_years: set[str], skip: list[str] = ()) -> list[dict]:
    """연도 갱신 후 문서에 남은 옛 연도. 식별번호 안의 숫자와, 이미 확인 표시한 문구(skip)가 든 줄은 뺀다.
    text = 연도가 붙은 낱말(띄어쓰기 없는 덩어리, 한글 찾기용), nth = 문서에서 그 낱말의 몇 번째(0부터)."""
    out, zones = [], history_zones(doc_text)
    for y in sorted(old_years):
        for m in re.finditer(rf"(?<!\d){y}(?!\d)", doc_text):
            if _inside_number(doc_text, m.start(), m.end()) or _in_zone(m.start(), zones):
                continue  # 이력서의 학력·경력 날짜는 지난 사실 — '남음'으로 알려 바꾸게 하지 않음
            token = re.match(r"\S+", doc_text[m.start():])[0][:20]
            line = " ".join(doc_text[doc_text.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0].split())
            if any(" ".join(t.split()) in line for t in skip if t.strip()):
                continue
            out.append({"text": token, "nth": doc_text.count(token, 0, m.start()), "line": line,
                        "note": f"옛 연도 {y}가 남음 — 바꿔야 하는지 확인: {line[:60]}"})
    return out


def resolve_text(text: str, doc_text: str) -> str:
    """AI가 띄어쓰기를 한 칸으로 줄인 문구(find_lines 결과)를 문서의 실제 문구로 되돌린다.
    예: "2026년 9월 1일" → 문서 속 "2026년  9월  1일". 없으면 그대로."""
    words = text.split()
    if not words or text in doc_text:
        return text
    m = re.search(r"\s+".join(map(re.escape, words)), doc_text)
    return m.group(0) if m else text


def _num(s: str) -> int:
    return int(s.replace(",", ""))


CALC_RE = re.compile(r"(\d[\d,]*)\s*원?((?:\s*[×xX*]\s*\d[\d,]*\s*[가-힣]*)+)\s*=\s*(\d[\d,]*)")


def check_math(doc_text: str) -> list[Check]:
    """산출내역 계산식 'A원×B명(×C회) = D원'이 맞는지. 식과 결과가 다음 줄에 있어도 본다."""
    out = []
    for m in CALC_RE.finditer(" ".join(doc_text.split())):
        want = _num(m[1])
        for n in re.findall(r"\d[\d,]*", m[2]):
            want *= _num(n)
        if want != _num(m[3]):
            out.append(Check(m[3], f"계산 확인: {m[1]}{m[2].strip()} = {want:,}인데 {m[3]}로 적혀 있음"))
    return out


PURE_AMOUNT = re.compile(r"\s*(\d{1,3}(?:,\d{3})+)\s*원?\s*")


def check_table_sums(doc_text: str) -> list[Check]:
    """표의 '합계'가 위쪽 금액 칸(금액만 있는 줄)들의 합과 같은지.
    ponytail: 줄 단위 추정 — 위로 올라가며 '예산'·'금액'이 든 머리글 줄을 만나야만 점검. 표 구조를 읽게 되면 칸 기준으로."""
    lines = [ln for ln in re.split(r"\r\n|\r|\n", doc_text) if ln.strip()]
    out = []
    for i, ln in enumerate(lines[:-1]):
        total = PURE_AMOUNT.fullmatch(lines[i + 1])
        if not re.fullmatch(r"\s*합\s*계\s*", ln) or not total:
            continue
        cells, nums, header = [], [], False  # nums: 쉼표 없는 숫자(수량·작은 단가)까지 모든 숫자 칸
        for up in reversed(lines[:i]):
            if m := PURE_AMOUNT.fullmatch(up):
                cells.append(_num(m[1]))
                nums.append(_num(m[1]))
            elif re.fullmatch(r"\s*\d+\s*", up):
                nums.append(int(up))
            elif "합계" in up.replace(" ", ""):
                break
            elif "예산" in up or "금액" in up:
                header = True
                break
        nums.reverse()
        # 물품 목록(수량·단가·금액): 금액 칸 = 바로 앞 두 숫자의 곱인 칸. 이미 묶인 3칸은 건너뛰어 행 경계(금액×1=단가) 오탐 방지
        priced, k = 0, 0
        while k + 2 < len(nums):
            if k + 3 < len(nums) and nums[k] == 1 and nums[k + 1] * nums[k + 2] == nums[k + 3] > nums[k + 2]:
                k += 1  # 연번 1 뒤에 (수량, 단가, 금액)이 오는 줄
            a, b, c = nums[k], nums[k + 1], nums[k + 2]
            if a * b == c and c >= 100:
                priced += c
                k += 3
            else:
                k += 1
        if header and len(cells) >= 2 and _num(total[1]) not in (sum(cells), priced):
            what = f"물품 금액(수량×단가)의 합 {priced:,}원" if priced else f"표 항목의 합 {sum(cells):,}원"
            out.append(Check(total[1], f"합계 {total[1]}원이 {what}과 다름"))
    return out


AMOUNT_NOTES = ("합계 ", "계산 확인")  # 금액 점검 결과 (최종 문서로 다시 점검할 때 예전 것을 버리는 기준)


def amount_checks(doc_text: str) -> list[Check]:
    return check_math(doc_text) + check_table_sums(doc_text) + check_budget(doc_text)


YEAR_TYPO_RE = re.compile(r"(?<![\d,.])((?:19|20)\d{2})\d(?=[가-힣])")  # "20260북구…" (실제 공문에서 발견)


def review_document(doc_text: str) -> list[Check]:
    """[문서 검토] 버튼: AI 없이 규칙만으로 문서 전체 점검 — 고치지 않고 확인할 곳만.
    금액(계산식·표 합계·사업 예산), 요일이 달력과 다른 날짜·없는 날짜, 연도 오타(숫자 하나 더 붙음)."""
    out = amount_checks(doc_text)
    for m in DATE_RE.finditer(doc_text):
        if bad := _weekday_problems(m.group(0)):
            out.append(Check(m.group(0), "날짜 확인 — " + bad[0].split(": ", 1)[1]))
    for m in YEAR_TYPO_RE.finditer(doc_text):
        out.append(Check(m.group(0), f"연도 오타 의심: {m.group(0)} — {m.group(1)}?"))
    return list({c.text: c for c in out}.values())


def strip_unit(text: str) -> str | None:
    """'1,234,560원' → '1,234,560'. 한글 표 칸에서 '원'이 따로 떨어져 있어 찾기가 실패하는 경우용. 해당 없으면 None."""
    s = re.sub(r"\s*원$", "", text)
    return s if s != text and s else None


def touches_amount(pairs: list[tuple[str, str]]) -> bool:
    """이번 수정에 금액(1,234 꼴)이 들어 있나 — 문서 전체 금액 점검은 이때만 (상관없는 요청에 확인 항목이 뜨지 않게)."""
    return any(AMOUNT_RE.search(f) or AMOUNT_RE.search(r) for f, r in pairs)


_MARK_RE = re.compile(r"^(\s*)([-•·○●◦▪■□◆◇▶※*]|\(?\d{1,2}[.)]|\(?[가-하][.)]|[①-⑳㉠-㉭㉮-㉻])\s")


def para_kind(text: str) -> str | None:
    """문단 머리 모양(앞 공백 + 글머리 종류). 글머리 없는 문단은 None — 제목·본문을 구별할 수 없어 맞추지 않는다.
    '1.'과 '2.', '가.'와 '나.'는 같은 종류."""
    m = _MARK_RE.match(text)
    if not m:
        return None
    mark = re.sub(r"\d{1,2}", "0", m.group(2))
    mark = re.sub(r"[가-하]", "가", mark)
    mark = re.sub(r"[①-⑳]", "①", re.sub(r"[㉠-㉭]", "㉠", re.sub(r"[㉮-㉻]", "㉮", mark)))
    return f"{len(m.group(1).expandtabs(4))}{mark}"


def same_kind_neighbor(text: str, neighbors: list[tuple[int, str]]) -> int | None:
    """고친 문단과 같은 글머리 종류인 가장 가까운 이웃 문단 번호. neighbors = [(문단 번호, 글)], 가까운 순."""
    kind = para_kind(text)
    if kind is None:
        return None
    return next((i for i, t in neighbors if para_kind(t) == kind), None)
