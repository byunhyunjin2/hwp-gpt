"""Codex가 부르는 한글 도구 서버 (stdio MCP).

모든 수정은 규칙 엔진(validate_edits)을 통과해야 한글에 반영된다. 결과는 HWPGPT_SESSION 파일에 남긴다.
한글이 없거나 끊기면 예외 대신 {"error": ...}를 돌려준다.
"""
import functools
import os
import re
from pathlib import Path

from . import session
from .hwp_bridge import HwpNotAvailable
from .rules import DATE_RE, Edit, amount_checks, changed_years, leftover_years, resolve_text, strip_unit, validate_edits

NO_HWP = "한글 문서를 열어 주세요"
MAX_LINES = 80


def _safe(fn):
    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except HwpNotAvailable as e:
            return {"error": str(e) or NO_HWP}

    return wrap


class Tools:
    def __init__(self, bridge, session_path: Path) -> None:
        self.b = bridge
        self.s = Path(session_path)

    def _check(self, text: str, note: str) -> dict:
        text = resolve_text(text, self.b.read_text())  # 띄어쓰기가 달라도 문서의 실제 문구로 표시
        self.b.mark_check(text)
        c = {"text": text, "note": note}
        session.write(self.s, "check", c)
        return c

    def _doc_type(self, name: str) -> None:
        if name.strip():
            session.write(self.s, "doc_type", {"name": name.strip()})

    @staticmethod
    def _numbered(doc: str) -> list[tuple[int, str]]:
        """빈 줄을 뺀 줄들 (문서 속 시작 위치, 원래 글). 줄 번호 = 이 목록의 1부터 순서."""
        return [(m.start(), m.group()) for m in re.finditer(r"[^\r\n]+", doc) if m.group().strip()]

    def _lines(self) -> list[str]:
        """'줄번호| 글' — 줄 안의 연속 공백은 하나로 (AI에 보내는 토큰 절약). 번호로 바꿀 자리를 정확히 고른다."""
        return [f"{i}| {' '.join(t.split())}" for i, (_, t) in enumerate(self._numbered(self.b.read_text()), 1)]

    @_safe
    def read_document(self, doc_type: str = "") -> dict:
        self._doc_type(doc_type)
        return {"text": "\n".join(self._lines())}

    @_safe
    def find_lines(self, pattern: str, doc_type: str = "", around: int = 0) -> dict:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"error": f"정규식 오류: {e}"}
        self._doc_type(doc_type)
        lines = self._lines()
        hits = [i for i, ln in enumerate(lines) if rx.search(ln.split("| ", 1)[1])]
        around = max(0, min(int(around), 8))  # 표 머리 칸 확인용 앞뒤 줄
        show = sorted({j for i in hits[:MAX_LINES] for j in range(i - around, i + around + 1) if 0 <= j < len(lines)})
        return {"lines": [lines[j] for j in show], "total_lines": len(lines), "more": max(0, len(hits) - MAX_LINES)}

    def _target(self, find: str, line_nos, doc: str) -> tuple[tuple[int, ...] | None, tuple[str, ...]]:
        """줄 번호들 → 그 줄 안에 있는 find가 문서 전체에서 몇 번째들인지(0부터)와 그 줄들. 줄을 안 주면 (None, ())."""
        if not line_nos:
            return None, ()
        rows = self._numbered(doc)
        nths, ctx = [], []
        for n in line_nos:
            if isinstance(n, int) and 1 <= n <= len(rows) and find in rows[n - 1][1]:
                start, text = rows[n - 1]
                before = doc.count(find, 0, start)
                nths += range(before, before + text.count(find))
                ctx.append(text)
        return tuple(sorted(set(nths))), tuple(ctx)

    @_safe
    def apply_edits(self, edits: list[dict], checks: list[dict] | None = None) -> dict:
        # 확인 표시도 같은 호출에서 (왕복 1회 절약). 먼저 남겨야 leftover에서 빠진다
        marked = [self._check(c["text"], c.get("note", "")) for c in checks or [] if c.get("text")]
        out = self._apply(edits)
        out["checks"] = marked + out["checks"]
        return out

    def _apply(self, edits: list[dict]) -> dict:
        doc = self.b.read_text()
        items, lines_of = [], {}
        for e in edits:
            find = resolve_text(e.get("find", ""), doc)
            nths, ctx = self._target(find, e.get("lines"), doc)
            items.append(Edit(find, e.get("replace", ""), e.get("reason", ""), nths, ctx))
            lines_of[id(items[-1])] = e.get("lines")
        ok, rejected = validate_edits(doc, items)
        applied = []
        for e, n, pos in self.b.apply(ok) if ok else []:
            if not n and strip_unit(e.find) and strip_unit(e.replace):  # 표 칸의 '원'이 떨어져 있으면 숫자만으로
                f = strip_unit(e.find)
                nths, ctx = self._target(f, lines_of.get(id(e)), doc)
                e = Edit(f, strip_unit(e.replace), e.reason, nths, ctx)
                _, n, pos = self.b.apply([e])[0]
            a = {"find": e.find, "replace": e.replace, "count": n, "pos": pos}
            session.write(self.s, "applied", a)
            applied.append(a)
        checks = [self._check(c.text, c.note) for c in rejected]
        for a in applied:  # 연도를 바꾼 날짜는 실제 일정인지 사용자가 확인하도록 빨간 표시
            if a["count"] and DATE_RE.search(a["replace"]) and changed_years([(a["find"], a["replace"])]):
                checks.append(self._check(a["replace"], "날짜 확인 필요: 연도를 바꾸고 요일을 달력에 맞춤 — 실제 일정인지 확인"))
        if applied:  # 예산 합계 점검을 따로 부르지 않아도 되게 (왕복 1회 절약)
            text = self.b.read_text()
            checks += [self._check(c.text, c.note) for c in amount_checks(text)]
            rows = session.read(self.s)
            pairs = [(x["data"]["find"], x["data"]["replace"]) for x in rows if x["kind"] == "applied"]
            marked = [x["data"]["text"] for x in rows if x["kind"] == "check"]
            left = leftover_years(text, changed_years(pairs), marked)
            if left:  # AI가 같은 대화에서 마저 고치거나 checks로 표시하게
                return {"applied": applied, "checks": checks, "leftover": list(dict.fromkeys(c["line"] for c in left))[:20]}
        return {"applied": applied, "checks": checks}

    @_safe
    def mark_check(self, text: str, note: str) -> dict:
        return self._check(text, note)


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    from .com_worker import ComWorker
    from .hwp_bridge import HwpBridge

    bridge = HwpBridge(ComWorker())
    t = Tools(bridge, Path(os.environ.get("HWPGPT_SESSION", "session.jsonl")))

    def connected(fn):
        @functools.wraps(fn)
        def wrap(*a, **k):
            if bridge._h is None and not bridge.connect():
                return {"error": NO_HWP}
            return fn(*a, **k)

        return wrap

    mcp = FastMCP("hwpgpt")

    @mcp.tool()
    @connected
    def find_lines(pattern: str, doc_type: str = "", around: int = 0) -> dict:
        """정규식에 맞는 줄만 '줄번호| 글'로 돌려준다 (예: 연도·날짜는 r"20\\d\\d"). 연도 갱신은 이것만으로 충분하다.
        표는 칸마다 한 줄이다. 특정 표·칸을 고칠 땐 around=6처럼 앞뒤 줄도 받아 표 머리 칸(제목·열 이름)을 확인한다.
        doc_type: 문서 종류(예: 앵커사업 운영계획서)를 첫 호출 때 한 번 적는다."""
        return t.find_lines(pattern, doc_type, around)

    @mcp.tool()
    @connected
    def read_document(doc_type: str = "") -> dict:
        """본문 전체(빈 줄 제외). 문단을 새로 쓰거나 내용을 이해해야 할 때만 쓴다."""
        return t.read_document(doc_type)

    @mcp.tool()
    @connected
    def apply_edits(edits: list[dict], checks: list[dict] | None = None) -> dict:
        """여러 수정을 한 번에. edits = [{"find": 문서에 있는 문구 그대로, "replace": 바꿀 문구, "reason": 이유, "lines": [줄번호]}].
        lines를 주면 그 줄(find_lines·read_document의 번호)에 있는 것만 바꾼다. 없으면 문서 전체의 같은 문구를 모두 바꾼다.
        사용자가 그림·인용·표 이름으로 특정 부분을 가리키면 반드시 lines로 그 부분만. "6", "4.0" 같은 짧은 문구는 lines 없으면 거부된다.
        checks = [{"text": 바꾸지 않고 확인만 할 문구, "note": 이유}] — 전년도 실적 등을 같은 호출에서 빨간 표시.
        날짜는 요일 포함 전체 문자열. 연도를 바꾼 날짜는 자동으로 빨간 '확인 필요' 표시.
        금액은 숫자만(예: "1,234,560", '원' 빼고). 계산식·표 합계·사업 예산 점검은 자동 — 결과 checks를 보고 함께 고친다.
        규칙에 걸린 수정은 바뀌지 않고 결과 checks로 돌아온다.
        결과 leftover = 아직 옛 연도가 남은 줄. 바꿔야 하면 다시 apply_edits, 아니면 checks로 표시."""
        return t.apply_edits(edits, checks)

    @mcp.tool()
    @connected
    def mark_check(text: str, note: str) -> dict:
        """바꾸지 않았지만 사용자가 확인해야 할 문구를 빨간 형광펜으로 표시."""
        return t.mark_check(text, note)

    mcp.run()


if __name__ == "__main__":
    main()
