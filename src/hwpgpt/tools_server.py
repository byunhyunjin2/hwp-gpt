"""Codex가 부르는 한글 도구 서버 (stdio MCP).

모든 수정은 규칙 엔진(validate_edits)을 통과해야 한글에 반영된다. 결과는 HWPGPT_SESSION 파일에 남긴다.
한글이 없거나 끊기면 예외 대신 {"error": ...}를 돌려준다.
"""
import functools
import os
import re
from pathlib import Path

import difflib
import tempfile

from . import session
from .hwp_bridge import ALIGN, MM, HwpNotAvailable
from .rules import (DATE_RE, Edit, PERSONAL_COL_RE, amount_checks, changed_years, is_protected, is_vague,
                    leftover_years, resolve_text, strip_unit, PROTECTED_NOTE, touches_amount, validate_edits)

NO_HWP = "한글 문서를 열어 주세요"
MAX_LINES = 80
PERMIT_NOTE = f"{PROTECTED_NOTE}: 사용자 허락이 필요함"
NO_MARK_NOTES = ("문서에서 찾지 못함", "첨부한 그림 부분만", "짧은 문구라")
TABLE_KO = {"set_cell": "칸 채우기", "insert_col_left": "왼쪽에 열 넣기", "insert_col_right": "오른쪽에 열 넣기",
            "delete_col": "열 지우기", "merge": "칸 합치기", "create": "새 표"}
INSERT_KO = {"paragraph": "새 문단", "delete_paragraph": "문단 지우기", "page_break": "쪽 나누기", "picture": "그림 넣기",
             "footnote": "각주", "memo": "메모", "header": "머리말", "footer": "꼬리말", "page_number": "쪽 번호",
             "replace_picture": "그림 바꾸기"}
NO_FIND = ("header", "footer", "page_number", "replace_picture")  # 기준 글 없이 하는 넣기
PREVIEW_NOTE = "미리 보기: 아직 문서를 바꾸지 않았음 — 사용자가 패널에서 고른 것만 적용됨. 답변은 제안 요약만"
PREVIEW_ONLY_TEXT = {"error": "미리 보기 중이라 서식·표·넣기는 하지 않음 — 글 바꾸기(apply_edits)만 제안하고, "
                              "나머지는 사용자에게 미리 보기를 끄고 다시 요청하라고 답한다"}


def shapes(item: dict) -> tuple[dict, dict]:
    """format_text 항목 → (한글 글자 모양, 문단 모양) 값. 잘못된 값이면 ValueError."""
    char, para = {}, {}
    for k, key in (("bold", "Bold"), ("italic", "Italic")):
        if k in item:
            char[key] = int(bool(item[k]))
    if "underline" in item:
        char["UnderlineType"] = 1 if item["underline"] else 0  # 1 = 글자 아래
    if "strike" in item:
        char["StrikeOutType"] = 1 if item["strike"] else 0
    if (c := item.get("color")) is not None and c != "":
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(c))
        if not m:
            raise ValueError(f"색은 #RRGGBB: {c}")
        char["TextColor"] = tuple(int(m[1][i:i + 2], 16) for i in (0, 2, 4))
    if (s := item.get("size")) is not None and s != "":
        if not 1 <= float(s) <= 200:
            raise ValueError(f"글자 크기는 1~200pt: {s}")
        char["Height"] = int(float(s) * 100)
    if (f := item.get("font")) is not None and str(f).strip():
        char.update(FaceNameHangul=str(f), FaceNameLatin=str(f), FontTypeHangul=1, FontTypeLatin=1)
    if (a := item.get("align")) is not None and a != "":
        if a not in ALIGN:
            raise ValueError(f"정렬은 {'/'.join(ALIGN)}: {a}")
        para["AlignType"] = ALIGN[a]
    if (ls := item.get("line_spacing")) is not None and ls != "":
        if not 50 <= int(ls) <= 500:
            raise ValueError(f"줄 간격은 50~500%: {ls}")
        para.update(LineSpacingType=0, LineSpacing=int(ls))  # 0 = 글자에 따라(%)
    # 문단 여백·들여쓰기: 한글 값은 1mm = 567(HWPUNIT×2)이고 **홀수면 다른 단위로 읽힘** → 짝수로 (2026-11-11 쪽 그림으로 측정)
    for k, key, low in (("left_margin_mm", "LeftMargin", 0), ("right_margin_mm", "RightMargin", 0),
                        ("indent_mm", "Indentation", -100)):
        if k in item:
            mm = float(item[k])
            if not low <= mm <= 100:
                raise ValueError(f"{k}는 {low}~100mm: {mm}")
            para[key] = 2 * round(mm * MM)
    if not char and not para:
        raise ValueError("바꿀 서식이 없음")
    return char, para


def _safe(fn):
    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except HwpNotAvailable as e:
            return {"error": str(e) or NO_HWP}

    return wrap


class Tools:
    def __init__(self, bridge, session_path: Path, scoped: bool = False, personal: bool = False,
                 files: list[str] = (), attached: Path | None = None, preview: bool = False) -> None:
        self.b = bridge
        self.s = Path(session_path)
        self.preview = preview  # 고치기 전 미리 보기: 글 바꾸기는 제안만, 서식·표·넣기는 하지 않음
        self.scoped = scoped  # 그림을 첨부한 요청: 그림 부분만 (위치 없는 수정 거부, 문서 전체 점검 안 함)
        self.personal = personal  # 사용자가 패널에서 이번 요청만 보호 해제를 허용함 (개인정보·표 줄 삭제/추가)
        self.files = [f for f in files if f]  # 이번 요청에 첨부한 그림 — 문서에 넣을 수 있는 그림은 이것뿐
        self.attached = attached  # 첨부 문서에서 뽑은 글 (비교용)

    def _done(self, label: str, at: str = "", marks: list[str] = (), undo: list | None = None,
              redo: list | None = None) -> dict:
        """서식·표·넣기처럼 글 바꾸기가 아닌 수정 — 패널 '바꾼 곳'에 이름표로.
        undo/redo = 패널이 ↶·↷에서 자기 HwpBridge로 실행할 [{"op": 메서드, "args": [...]}] (없으면 한글 Ctrl+Z로만)."""
        d = {"label": label, "at": at, "marks": [m for m in marks if m]}
        if undo and redo:
            d.update(undo=undo, redo=redo)
        session.write(self.s, "done", d)
        return d

    def _where(self, find: str, lines, doc: str) -> tuple[str, tuple | None, str | None]:
        """(문서의 실제 문구, 몇 번째들, 안 되는 이유) — 위치를 받는 새 도구들의 공통 검사."""
        find = resolve_text(find or "", doc)
        nths, _ = self._target(find, lines, doc)
        if not find or find not in doc or nths == ():
            return find, nths, "문서에서 찾지 못함" + (" (지정한 줄에 없음)" if nths == () else "")
        if nths is None and self.scoped:
            return find, nths, "첨부한 그림 부분만 고치는 요청이라 줄 번호(lines)가 필요함"
        if nths is None and is_vague(find):
            return find, nths, "짧은 문구라 줄 번호(lines)가 필요함"
        return find, nths, None

    def _check(self, text: str, note: str) -> dict:
        text = resolve_text(text, self.b.read_text())  # 띄어쓰기가 달라도 문서의 실제 문구로 표시
        if text and not note.startswith("문서에서 찾지 못함") and not (note.startswith(NO_MARK_NOTES) and len(text.strip()) <= 3):
            self.b.mark_check(text)
        c = {"text": text, "note": note}
        session.write(self.s, "check", c)
        return c

    def _doc_type(self, name: str) -> None:
        if name := " ".join(str(name).split())[:60]:  # 한 줄로 (기억 파일 제목·파일 이름이 됨)
            session.write(self.s, "doc_type", {"name": name})

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
        if len(pattern) > 200:
            return {"error": "정규식이 너무 깁니다 (200자 이하)"}
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
        ok, rejected = validate_edits(doc, items, need_lines=self.scoped, personal=self.personal)
        if self.preview:  # 바꾸지 않고 제안만 — 사용자가 패널에서 고른 것만 패널이 적용한다
            proposed = []
            for e in ok:
                p = {"find": e.find, "replace": e.replace, "reason": e.reason,
                     "nths": None if e.nths is None else list(e.nths),
                     "count": doc.count(e.find) if e.nths is None else len(e.nths)}
                session.write(self.s, "proposed", p)
                proposed.append(p)
            return {"applied": [], "proposed": proposed, "checks": [self._check(c.text, c.note) for c in rejected],
                    "note": PREVIEW_NOTE}
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
        if applied and not self.scoped:  # 문서 전체 점검: 그림 부분만 고치는 요청에는 하지 않음
            text = self.b.read_text()
            if touches_amount([(a["find"], a["replace"]) for a in applied]):  # 금액을 바꿨을 때만 합계 점검
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

    @_safe
    def edit_table_rows(self, rows: list[dict]) -> dict:
        """표 줄 지우기·추가. 표 모양을 바꾸므로 사용자가 패널에서 허락한 요청에서만 (아니면 패널이 허락을 묻는다)."""
        if self.preview:
            return PREVIEW_ONLY_TEXT
        if not self.personal:
            return {"done": [], "checks": [self._check(r.get("find", ""), f"{PROTECTED_NOTE}: 표 줄 삭제·추가는 사용자 허락이 필요함")
                                           for r in rows[:1]]}
        done, failed = [], []
        for r in rows:  # 지우면 아래 줄 번호가 바뀌므로 받은 순서대로, 매번 문서를 새로 읽어 위치를 찾는다
            doc = self.b.read_text()
            find = resolve_text(r.get("find", ""), doc)
            nths, _ = self._target(find, r.get("lines"), doc)
            why = None if find else "find가 비어 있음"
            if nths == ():
                why = "지정한 줄에 없음"
            until = resolve_text(r.get("until", ""), doc) if r.get("until") else ""
            u_nths, _ = self._target(until, r.get("until_lines"), doc) if until else (None, ())
            why = why or self.b.table_rows(r.get("action", ""), find, (nths or (0,))[0], int(r.get("count", 1)),
                                           until, (u_nths or (0,))[0], bool(r.get("to_end")))
            item = {"action": r.get("action"), "find": find, "count": int(r.get("count", 1)), "until": until}
            (failed if why else done).append({**item, "error": why} if why else item)
            if not why:
                session.write(self.s, "rows", item)
        return {"done": done, "failed": failed}

    @_safe
    def format_text(self, items: list[dict]) -> dict:
        if self.preview:
            return PREVIEW_ONLY_TEXT
        doc = self.b.read_text()
        done, failed = [], []
        for it in items:
            find, nths, why = self._where(it.get("find", ""), it.get("lines"), doc)
            try:
                char, para = shapes(it)
            except (ValueError, TypeError) as e:
                why = why or str(e)
            if why:
                failed.append({"find": find, "error": why})
                continue
            old = self.b.shapes_of(find, nths, list(char), list(para))
            n = self.b.format_text(find, nths, char, para)
            what = ", ".join(f"{k}={it[k]}" for k in ("bold", "italic", "underline", "strike", "color", "size", "font",
                                                      "align", "line_spacing", "left_margin_mm", "right_margin_mm",
                                                      "indent_mm") if k in it)
            (done if n else failed).append({"find": find, "count": n} if n else {"find": find, "error": "한글에서 찾지 못함"})
            if n:
                self._done(f"서식({what}): {find}", find,
                           undo=[{"op": "format_text", "args": [find, [k], c, p]} for k, c, p in old],
                           redo=[{"op": "format_text", "args": [find, None if nths is None else list(nths), char, para]}])
        return {"done": done, "failed": failed}

    def _anchor(self, find: str, lines, doc: str) -> tuple[str, int]:
        find = resolve_text(find or "", doc)
        nths, _ = self._target(find, lines, doc)
        return find, (nths or (0,))[0]

    @_safe
    def read_table(self, find: str, lines: list[int] | None = None) -> dict:
        find, nth = self._anchor(find, lines, self.b.read_text())
        r = self.b.read_table(find, nth)
        if "error" in r:
            return r
        rows: dict[str, list[str]] = {}
        for addr, text in r["cells"]:
            rows.setdefault(re.sub(r"\D", "", addr), []).append(f"{addr}: {' '.join(text.split())}")
        return {"rows": [" | ".join(v) for v in rows.values()]}

    def _cell_protected(self, find: str, nth: int, cell: str, old: str | None) -> str | None:
        if not old or not old.strip() or PERSONAL_COL_RE.match(old):
            return None
        if reason := is_protected(old, old):
            return reason
        m = re.fullmatch(r"([A-Z]+)(\d+)", cell.upper())
        if m and int(m[2]) >= 2 and PERSONAL_COL_RE.match(self.b.cell_text(find, nth, f"{m[1]}1") or ""):
            return "개인정보가 있는 표 칸"
        return None

    @_safe
    def edit_table(self, ops: list[dict]) -> dict:
        if self.preview:
            return PREVIEW_ONLY_TEXT
        done, failed, checks = [], [], []
        for op in ops:  # 열을 지우면 칸 주소가 바뀌므로 받은 순서대로, 매번 새로 읽는다
            doc = self.b.read_text()
            a = op.get("action", "")
            find, nth = self._anchor(op.get("find", ""), op.get("lines"), doc)
            op = {**op, "find": find}
            why = None if find and find in doc else "find 글을 문서에서 찾지 못함"
            if not why and a == "delete_col" and not self.personal:  # 표 줄 지우기처럼 내용이 사라짐 → 허락
                checks.append(self._check(find, f"{PERMIT_NOTE} (표 열 지우기)"))
                why = PERMIT_NOTE
            old = self.b.cell_text(find, nth, op.get("cell", "")) if not why and a in ("set_cell", "merge") else None
            if not why and a in ("set_cell", "merge") and not self.personal:
                if reason := self._cell_protected(find, nth, str(op.get("cell", "")), old):
                    checks.append(self._check(old, f"{PROTECTED_NOTE}: {reason}"))
                    why = PERMIT_NOTE
                elif a == "merge" and (to_old := self.b.cell_text(find, nth, str(op.get("to", "")))):
                    if reason := self._cell_protected(find, nth, str(op.get("to", "")), to_old):
                        checks.append(self._check(to_old, f"{PROTECTED_NOTE}: {reason}"))
                        why = PERMIT_NOTE
            why = why or self.b.table_op(op, nth)
            item = {"action": a, "cell": op.get("cell", ""), "find": find}
            if why:
                failed.append({**item, "error": why})
                continue
            done.append(item)
            text = str(op.get("text", ""))
            marks = text.splitlines() if a == "set_cell" else [str(v) for r in op.get("rows") or [] for v in r]
            self._done(f"표 {TABLE_KO.get(a, a)} {op.get('cell', '')}".rstrip() + (f": {text}" if text else ""),
                       (marks or [find])[0], marks, self._table_undo(op, nth, old, text),
                       [{"op": "table_op", "args": [op, nth]}])
        return {"done": done, "failed": failed, "checks": checks}

    def _table_undo(self, op: dict, nth: int, old: str | None, text: str) -> list | None:
        """표 작업 되돌리기: 칸 채우기 → 예전 글, 열 넣기 → 그 열 지우기, 새 표 → 그 표 지우기. 칸 합치기·열 지우기는 없음."""
        a, cell = op.get("action"), str(op.get("cell", "")).upper()
        if a == "create":
            return self.b.undo_spec
        m = re.fullmatch(r"([A-Z]+)(\d+)", cell)
        if not m:
            return None
        find = op["find"]
        if a == "set_cell":
            if find not in self.b.read_text():  # 기준 글이 든 칸을 바꿨으면 새 글로 그 표를 찾음
                find = (text.splitlines() or [""])[0]
            undo_op = {"action": "set_cell", "find": find, "cell": cell, "text": old or "", "mark": False}
            return [{"op": "table_op", "args": [undo_op, nth]}] if find and old is not None else None
        if a in ("insert_col_left", "insert_col_right"):  # 왼쪽에 넣으면 새 열이 그 자리, 오른쪽이면 다음 열
            n = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(m[1]))) + (a == "insert_col_right")
            col = ""
            while n:
                n, r = divmod(n - 1, 26)
                col = chr(65 + r) + col
            undo_op = {"action": "delete_col", "find": find, "cell": f"{col}{m[2]}", "width": self.b.table_width_before}
            return [{"op": "table_op", "args": [undo_op, nth]}]
        return None

    @_safe
    def insert_content(self, items: list[dict]) -> dict:
        if self.preview:
            return PREVIEW_ONLY_TEXT
        done, failed, checks = [], [], []
        for it in items:
            doc = self.b.read_text()
            kind, text = it.get("kind", ""), str(it.get("text", ""))
            find, nth, why, picture = "", 0, None, ""
            if kind not in NO_FIND:
                find, nths, why = self._where(it.get("find", ""), it.get("lines"), doc)
                nth = (nths or (0,))[0]
            if not why and kind == "delete_paragraph":
                para = self.b.paragraph_of(find, nth)
                if para is None:
                    why = "표 칸 안이거나 찾지 못함 — 표는 edit_table로"
                elif not self.personal and (reason := is_protected(para, para)):
                    checks.append(self._check(find, f"{PROTECTED_NOTE}: {reason}"))
                    why = PERMIT_NOTE
            if not why and kind in ("picture", "replace_picture"):
                want = Path(str(it.get("file", ""))).name
                picture = next((f for f in self.files if Path(f).name == want or len(self.files) == 1 and not want), "")
                why = None if picture else "이번 요청에 첨부한 그림만 넣을 수 있음"
            if kind == "memo" and find:  # 메모는 문단 전체에 달리므로 어느 글에 대한 메모인지 앞에 적음
                it = {**it, "text": f"[{find[:30]}] {text}"}
            why = why or self.b.insert({**it, "find": find}, nth, picture)
            item = {"kind": kind, "find": find}
            if why:
                failed.append({**item, "error": why})
                continue
            done.append(item)
            label = INSERT_KO.get(kind, kind) + (f": {text}" if text else f" ({find})" if find else "")
            self._done(label[:80], text.splitlines()[0] if kind == "paragraph" and text.strip() else find,
                       text.splitlines() if kind == "paragraph" else [], self.b.undo_spec,
                       [{"op": "insert", "args": [{**it, "find": find}, nth, picture]}])
        return {"done": done, "failed": failed, "checks": checks}

    @_safe
    def fill_fields(self, values: dict[str, str] | None = None) -> dict:
        current = self.b.fields()
        if not values:
            return {"fields": current}
        if self.preview:
            return PREVIEW_ONLY_TEXT
        done, failed, checks = [], [], []
        for name, text in values.items():
            old = current.get(name)
            if old is None:
                failed.append({"name": name, "error": "그런 누름틀이 없음"})
            elif old.strip() and not self.personal and (reason := is_protected(old, old)):
                checks.append(self._check(old, f"{PROTECTED_NOTE}: {reason}"))
                failed.append({"name": name, "error": PERMIT_NOTE})
            else:
                self.b.put_field(name, str(text))
                done.append(name)
                self._done(f"누름틀 {name}: {text}", str(text), undo=[{"op": "put_field", "args": [name, old]}],
                           redo=[{"op": "put_field", "args": [name, str(text)]}])
        return {"done": done, "failed": failed, "checks": checks}

    @_safe
    def page_image(self, page: int = 1) -> bytes | dict:
        try:
            return self.b.page_png(int(page), tempfile.gettempdir())
        except ValueError as e:
            return {"error": str(e)}

    def compare_attachment(self, name: str = "") -> dict:
        """첨부 문서 글과 열린 문서의 다른 줄 (- 첨부에만, + 열린 문서에만)."""
        try:
            raw = self.attached.read_text(encoding="utf-8") if self.attached else ""
        except OSError:
            raw = ""
        blocks = dict(re.findall(r"\[첨부 파일: ([^\]\n]+)\]\n(.*?)(?=\n\n\[첨부 파일: |\Z)", raw, re.S))
        pick = next((k for k in blocks if name and name in k), next(iter(blocks), None))
        if pick is None:
            return {"error": "이번 요청에 첨부한 문서가 없음"}
        try:
            doc = self.b.read_text()
        except HwpNotAvailable as e:
            return {"error": str(e) or NO_HWP}
        norm = lambda t: [" ".join(x.split()) for x in t.splitlines() if x.strip()]  # noqa: E731
        diff = [d for d in difflib.unified_diff(norm(blocks[pick]), norm(doc), lineterm="", n=0)
                if d[:1] in "+-" and not d.startswith(("+++", "---"))]
        return {"attachment": pick, "diff": diff[:150], "more": max(0, len(diff) - 150)}


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    from .com_worker import ComWorker
    from .hwp_bridge import HwpBridge

    bridge = HwpBridge(ComWorker())
    attached = os.environ.get("HWPGPT_ATTACHED")
    t = Tools(bridge, Path(os.environ.get("HWPGPT_SESSION", "session.jsonl")), os.environ.get("HWPGPT_SCOPED") == "1",
              os.environ.get("HWPGPT_PERSONAL") == "1", os.environ.get("HWPGPT_FILES", "").split(os.pathsep),
              Path(attached) if attached else None, os.environ.get("HWPGPT_PREVIEW") == "1")

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
        결과 leftover = 아직 옛 연도가 남은 줄(이력서 등 개인 이력은 빠져 있음). 행사·사업 연도면 다시 apply_edits, 지난 실적이면 checks."""
        return t.apply_edits(edits, checks)

    @mcp.tool()
    @connected
    def mark_check(text: str, note: str) -> dict:
        """바꾸지 않았지만 사용자가 확인해야 할 문구를 빨간 형광펜으로 표시."""
        return t.mark_check(text, note)

    @mcp.tool()
    @connected
    def edit_table_rows(rows: list[dict]) -> dict:
        """표 줄 지우기·추가. rows = [{"action": "delete" 또는 "insert_below", "find": 그 줄의 칸에 있는 글, "lines": [줄번호],
        "until": 마지막으로 지울 줄의 칸 글, "until_lines": [줄번호], "to_end": true, "count": 몇 줄}].
        "~부터 마지막 줄까지"는 to_end: true (표의 마지막 줄은 패널이 직접 찾는다).
        delete: find가 든 줄부터 until이 든 줄까지 지운다. **여러 줄을 지울 땐 count를 세지 말고 until을 쓴다**(표는 칸마다 한 줄이라 줄 수를 세면 틀림).
        insert_below: find가 든 줄 아래에 빈 줄 count개.
        여러 곳이면 위에서부터가 아니라 **아래쪽 줄부터** 적는다(지운 뒤 위치가 밀리지 않게).
        사용자 허락([보호 해제 허용])이 없는 요청이면 바뀌지 않고 checks로 돌아온다 — 그때는 답변을 [[권한 확인]] 한 줄로."""
        return t.edit_table_rows(rows)

    @mcp.tool()
    @connected
    def format_text(items: list[dict]) -> dict:
        """글자·문단 서식. items = [{"find": 글, "lines": [줄번호], "bold"/"italic"/"underline"/"strike": true|false,
        "color": "#RRGGBB", "size": pt, "font": 글꼴 이름, "align": left|center|right|justify|distribute,
        "line_spacing": %, "left_margin_mm"/"right_margin_mm": 문단 여백, "indent_mm": 첫 줄 들여쓰기(음수 = 내어쓰기)}].
        정렬·줄 간격·여백·들여쓰기는 그 글이 든 문단 전체에. 사용자가 서식을 말했을 때만 쓴다."""
        return t.format_text(items)

    @mcp.tool()
    @connected
    def read_table(find: str, lines: list[int] | None = None) -> dict:
        """find(표 칸의 글)가 든 표를 칸 주소(A1, B2…)와 함께 줄별로. 표 칸을 고치기 전에 쓴다."""
        return t.read_table(find, lines)

    @mcp.tool()
    @connected
    def edit_table(ops: list[dict]) -> dict:
        """표 작업. ops = [{"action", "find": 그 표 칸의 글(read_table에 쓴 것), "lines", "cell": "B3", ...}].
        set_cell(cell, text: 칸 글 전체를 바꿈) · insert_col_left/insert_col_right(cell 옆) · delete_col(허락 필요) ·
        merge(cell~"to": "C3") · create(find 문단 아래 새 표, "rows": [[칸, …], …]). 줄 지우기·추가는 edit_table_rows."""
        return t.edit_table(ops)

    @mcp.tool()
    @connected
    def insert_content(items: list[dict]) -> dict:
        """넣기·지우기. items = [{"kind", "find": 기준 글, "lines", "text"}].
        paragraph(find 문단 아래 새 문단, 여러 줄 가능) · delete_paragraph(find 문단) · page_break(find 문단 뒤) ·
        picture(find 문단 아래, "file": 첨부 그림 이름, "width_mm", "in_cell": true면 find가 든 표 칸 안에,
        "cell": "A2"면 find가 든 표의 그 칸 안에 — 빈 칸은 이것으로) ·
        replace_picture("picture_no": 문서 몇 번째 그림, "file": 첨부 그림 — 같은 폭으로 바꿈) · footnote(find 글 뒤) ·
        memo(find가 든 문단에 메모, 메모 앞에 [find]가 붙음) · header/footer(text) · page_number("position": bottom_center 등).
        find·lines 없이: header·footer·page_number·replace_picture."""
        return t.insert_content(items)

    @mcp.tool()
    @connected
    def fill_fields(values: dict[str, str] | None = None) -> dict:
        """누름틀(양식 칸). values 없이 부르면 {이름: 지금 글}, values={이름: 글}이면 채운다."""
        return t.fill_fields(values)

    @mcp.tool()
    @connected
    def page_image(page: int = 1):
        """page쪽을 그림으로 본다 (표·그림·배치가 제대로 됐는지 눈으로 확인할 때만, 토큰이 많이 듦)."""
        from mcp.server.fastmcp import Image

        r = t.page_image(page)
        return r if isinstance(r, dict) else Image(data=r, format="png")

    @mcp.tool()
    def compare_attachment(name: str = "") -> dict:
        """첨부한 문서(name: 파일 이름 일부)와 열린 문서의 다른 줄. - 첨부에만 / + 열린 문서에만."""
        if bridge._h is None:
            bridge.connect()
        return t.compare_attachment(name)

    mcp.run()


if __name__ == "__main__":
    main()
