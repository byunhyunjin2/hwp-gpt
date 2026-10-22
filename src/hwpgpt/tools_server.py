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

    def _lines(self) -> list[str]:
        """빈 줄을 빼고 줄 안의 연속 공백을 하나로 (AI에 보내는 토큰 절약)."""
        return [" ".join(ln.split()) for ln in re.split(r"\r\n|\r|\n", self.b.read_text()) if ln.strip()]

    @_safe
    def read_document(self, doc_type: str = "") -> dict:
        self._doc_type(doc_type)
        return {"text": "\n".join(self._lines())}

    @_safe
    def find_lines(self, pattern: str, doc_type: str = "") -> dict:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"error": f"정규식 오류: {e}"}
        self._doc_type(doc_type)
        lines = self._lines()
        hits = [ln for ln in lines if rx.search(ln)]
        return {"lines": hits[:MAX_LINES], "total_lines": len(lines), "more": max(0, len(hits) - MAX_LINES)}

    @_safe
    def apply_edits(self, edits: list[dict], checks: list[dict] | None = None) -> dict:
        # 확인 표시도 같은 호출에서 (왕복 1회 절약). 먼저 남겨야 leftover에서 빠진다
        marked = [self._check(c["text"], c.get("note", "")) for c in checks or [] if c.get("text")]
        out = self._apply(edits)
        out["checks"] = marked + out["checks"]
        return out

    def _apply(self, edits: list[dict]) -> dict:
        doc = self.b.read_text()
        items = [Edit(resolve_text(e.get("find", ""), doc), e.get("replace", ""), e.get("reason", "")) for e in edits]
        ok, rejected = validate_edits(doc, items)
        applied = []
        for e, n in self.b.apply(ok) if ok else []:
            if not n and strip_unit(e.find) and strip_unit(e.replace):  # 표 칸의 '원'이 떨어져 있으면 숫자만으로
                e = Edit(strip_unit(e.find), strip_unit(e.replace), e.reason)
                n = self.b.apply([e])[0][1]
            a = {"find": e.find, "replace": e.replace, "count": n}
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
    def find_lines(pattern: str, doc_type: str = "") -> dict:
        """정규식에 맞는 줄만 돌려준다 (예: 연도·날짜는 r"20\\d\\d"). 연도 갱신은 이것만으로 충분하다.
        doc_type: 문서 종류(예: 앵커사업 운영계획서)를 첫 호출 때 한 번 적는다."""
        return t.find_lines(pattern, doc_type)

    @mcp.tool()
    @connected
    def read_document(doc_type: str = "") -> dict:
        """본문 전체(빈 줄 제외). 문단을 새로 쓰거나 내용을 이해해야 할 때만 쓴다."""
        return t.read_document(doc_type)

    @mcp.tool()
    @connected
    def apply_edits(edits: list[dict], checks: list[dict] | None = None) -> dict:
        """여러 수정을 한 번에. edits = [{"find": 문서에 있는 문구 그대로, "replace": 바꿀 문구, "reason": 이유}].
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
