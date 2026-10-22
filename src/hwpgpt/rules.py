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
PERSONAL_KEYWORDS = ("담당자", "성명", "연락처", "전화", "휴대전화", "이메일", "주소")
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
ID_RE = re.compile(r"\d{7,}")


@dataclass
class Edit:
    find: str
    replace: str
    reason: str


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
        or any(k in context for k in PERSONAL_KEYWORDS)
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


def _paragraphs_with(doc_text: str, needle: str) -> list[str]:
    paras = re.split(r"\r\n|\r|\n", doc_text)
    hits = [p for p in paras if needle in p]
    return hits or ([doc_text] if needle in doc_text else [])


def validate_edits(doc_text: str, edits: list[Edit]) -> tuple[list[Edit], list[Check]]:
    """통과한 수정안과, 거부되어 확인(빨강)으로 돌릴 항목."""
    ok: list[Edit] = []
    checks: list[Check] = []
    for e in edits:
        if not e.find or e.find not in doc_text:
            checks.append(Check(e.find, "문서에서 찾지 못함"))
            continue
        reason = next(
            (r for p in _paragraphs_with(doc_text, e.find)
             if (r := is_protected(e.find, p))),
            None,
        )
        if reason:
            checks.append(Check(e.find, f"보호 대상이라 바꾸지 않음: {reason}"))
            continue
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
    out = []
    for y in sorted(old_years):
        for m in re.finditer(rf"(?<!\d){y}(?!\d)", doc_text):
            if _inside_number(doc_text, m.start(), m.end()):
                continue
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
        # 물품 목록(수량·단가·금액): 금액 칸 = 바로 앞 두 숫자의 곱인 칸
        priced = sum(c for a, b, c in zip(nums, nums[1:], nums[2:]) if a * b == c and c >= 100)
        if header and len(cells) >= 2 and _num(total[1]) not in (sum(cells), priced):
            what = f"물품 금액(수량×단가)의 합 {priced:,}원" if priced else f"표 항목의 합 {sum(cells):,}원"
            out.append(Check(total[1], f"합계 {total[1]}원이 {what}과 다름"))
    return out


AMOUNT_NOTES = ("합계 ", "계산 확인")  # 금액 점검 결과 (최종 문서로 다시 점검할 때 예전 것을 버리는 기준)


def amount_checks(doc_text: str) -> list[Check]:
    return check_math(doc_text) + check_table_sums(doc_text) + check_budget(doc_text)


def strip_unit(text: str) -> str | None:
    """'1,234,560원' → '1,234,560'. 한글 표 칸에서 '원'이 따로 떨어져 있어 찾기가 실패하는 경우용. 해당 없으면 None."""
    s = re.sub(r"\s*원$", "", text)
    return s if s != text and s else None
