"""HWP_GPT 패널: 한글 창 오른쪽에 붙는 ChatGPT 대화창 (pywebview)."""
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from . import codex_runner as cr
from . import __version__, attachments, paths, updater
from .com_worker import ComWorker
from .dock import Docker, EmbedDocker, find_hwp_window, place_right
from .hwp_bridge import RED, HwpBridge, HwpNotAvailable
from .memory import MemoryStore
from .rules import (AMOUNT_NOTES, PROTECTED_NOTE, Edit, amount_checks, changed_years, leftover_years, resolve_text,
                    review_document, touches_amount)
from .tools_server import NO_MARK_NOTES

TITLE = "HWP_GPT"
DEFAULT_PRESETS = ["올해 학년도로 연도를 바꿔줘", "고치지 말고 맞춤법·띄어쓰기만 확인해서 표시해줘",
                   "금액·합계·날짜 요일이 맞는지 확인만 해줘"]  # 자주 쓰는 요청 버튼 (사용자가 더하고 뺀다)
LOGIN_TIMEOUT = 300  # 초 — 브라우저 로그인을 기다리는 시간
UNDO_OPS = {"format_text", "table_op", "insert", "put_field", "delete_ctrl_at", "delete_para_at", "append_table"}  # ↶·↷에 쓰는 HwpBridge 메서드
UI = Path(__file__).resolve().parent / "ui" / "index.html"
ICON = Path(__file__).resolve().parent / "assets" / "hwpgpt.ico"  # 창 제목줄 (개발판도 병아리)


CHANGE_TABLE_TITLE = "변경 신구대조표"


class Api:
    """화면(JS)에서 window.pywebview.api.* 로 부른다. 각 호출은 별도 스레드에서 실행된다."""

    def __init__(self) -> None:
        self._worker = ComWorker()
        self._bridge = HwpBridge(self._worker)
        self._memory = MemoryStore()
        self._thread_id: str | None = None
        self._doc_type: str | None = None
        self._login = "missing" if not cr.find_codex() else cr.login_status()
        self._last_usage: dict = {}
        self._busy = threading.Lock()
        self._window = None
        self._snapshot: str | None = None   # AI 수정 직후 본문 (직접 수정 비교 기준)
        self._prev_modified: bool | None = None
        self._candidates: list[dict] = []   # 화면에 띄울 "이렇게 기억할까요?" 후보
        self._learning = threading.Lock()
        self._target: str | None = None      # 지금 대상 문서 경로 (바뀌면 대화·기준 초기화)
        self._mode = "embed" if _embed_mode() else "dock"   # embed = 한글 안, dock = 옆에 붙이기
        self._mode_changed = threading.Event()
        self._panel_hwnd = 0
        self._settings = _load_settings()   # 화면 테마, GPT 모델 (패널을 다시 켜도 유지)
        self._models = cr.list_models()
        self._update: dict = {}
        self._log: dict[str, dict] = {}  # 항목별 되돌리기: 번호 → 바꾼 기록(자리 포함)
        self._undone: list[str] = []      # 되돌린 수정 — 다음 요청에 AI에게 알림
        self._proposed: dict[str, dict] = {}  # 미리 보기: 번호 → 제안된 글 바꾸기 (고르면 적용)
        attachments.clear_pasted(paths.pasted_dir())
        attachments.clear_pasted(paths.session_dir())
        self._limits = cr.read_rate_limits()
        self._progress = {"pct": 0, "step": "", "start": 0.0}

    # --- 창 (넣기/빼기, 투명도) ---
    def set_mode(self, mode: str) -> str:
        if mode in ("dock", "embed") and mode != self._mode:
            self._mode = mode
            self._mode_changed.set()  # _dock_loop가 다시 붙임
        return self._mode

    def set_setting(self, key: str, value: str) -> dict:
        """theme: dark|light, model: Codex 모델 이름(빈 값 = Codex 기본), preview: 고치기 전 미리 보기(bool),
        presets: 자주 쓰는 요청 목록."""
        if key == "presets":
            value = [" ".join(str(s).split())[:200] for s in value or [] if str(s).strip()][:20]
        elif key == "preview":
            value = bool(value)
        if key in ("theme", "model", "preview", "presets"):
            self._settings[key] = value
            _save_settings(self._settings)
        return self._settings

    # --- 업데이트 ---
    def check_update(self) -> dict:
        """새 버전이 있는지 (패널 시작 때와 [업데이트] 버튼)."""
        self._update = updater.check()
        return {k: v for k, v in self._update.items() if not k.startswith("_")}

    def apply_update(self) -> dict:
        """설치 파일을 받아(SHA256 확인) 조용히 설치하고 패널을 닫는다. 설치가 끝나면 새 패널이 뜬다."""
        info = self._update.get("_info")
        if not info:
            return {"error": "먼저 업데이트를 확인해 주세요"}
        if not getattr(sys, "frozen", False):
            return {"error": "개발판은 git으로 업데이트합니다"}
        if self._busy.locked():
            return {"error": "요청 처리가 끝난 뒤 업데이트해 주세요"}
        self._progress = {"pct": 0, "step": "업데이트 받는 중", "start": time.time()}
        try:
            setup = updater.download(info, lambda pct: self._on_progress(pct, "업데이트 받는 중"))
        except Exception as e:  # 네트워크·SHA256 불일치: 지금 버전 그대로 계속 사용
            return {"error": f"업데이트를 받지 못했습니다: {e}"}
        updater.run_installer(setup)
        threading.Timer(0.5, self._window.destroy).start()  # 설치 프로그램이 파일을 바꿀 수 있게 패널 종료
        return {"ok": True}

    def _sync_target(self, target: str) -> None:
        """다른 문서로 바뀌면 이전 문서의 대화·종류·비교 기준·표시 목록을 버린다."""
        if self._target is not None and target != self._target:
            self._thread_id = self._doc_type = self._snapshot = self._prev_modified = None
            self._candidates = []
            self._bridge._marks.clear()  # 이전 문서의 형광펜은 그 문서에 그대로 둠
            self._bridge._cleared = {}
            self._log = {}  # 되돌리기는 같은 문서에서만
            self._proposed = {}
        self._target = target

    # --- 기억 학습 (Task 9) ---
    def _rules_for_prompt(self) -> list[str]:
        if self._doc_type:
            return self._memory.rules(self._doc_type)
        # 첫 요청이라 문서 종류를 모르면 모든 종류의 규칙을 종류 이름과 함께
        return [f"[{t}] {r}" for t in self._memory.doc_types() for r in self._memory.rules(t)]

    def _learn_now(self) -> None:
        """기준 본문과 지금 본문을 비교해 사용자가 직접 고친 것에서 규칙 후보를 만든다 (저장 안 함)."""
        if not self._learning.acquire(blocking=False):
            return
        try:
            now = self._bridge.read_text()
            before, self._snapshot = self._snapshot, now
            if before is None or not self._doc_type:
                return
            from .learn import diff_changes, propose_rules

            changes = diff_changes(before, now)
            if changes:
                self._candidates += [{"docType": self._doc_type, "rule": r}
                                     for r in propose_rules(self._doc_type, changes)]
        except HwpNotAvailable:
            pass
        finally:
            self._learning.release()

    def _pop_candidates(self) -> list[dict]:
        out, self._candidates = self._candidates, []
        return out

    def _watch_save(self) -> None:
        """status() 주기마다: 수정됨 → 저장됨 으로 바뀌면 학습을 백그라운드로."""
        try:
            mod = self._bridge.is_modified()
        except HwpNotAvailable:
            return
        if self._prev_modified and not mod and not self._busy.locked():
            threading.Thread(target=self._learn_now, daemon=True).start()
        self._prev_modified = mod

    # --- 상태 ---
    def _connected(self) -> bool:
        if self._bridge._h is None:
            return self._bridge.connect()
        try:
            self._bridge.target_name()
            return True
        except HwpNotAvailable:
            return self._bridge.connect()

    def status(self) -> dict:
        connected = self._connected()
        target = ""
        if connected:
            try:
                path = self._bridge.target_name()
                self._sync_target(path)
                target = Path(path).name or "새 문서"
                self._watch_save()
            except HwpNotAvailable:
                connected = False
        return {
            "login": self._login, "connected": connected, "target": target,
            "hasMarks": self._bridge.has_marks(), "canRestore": self._bridge.can_restore(), "docType": self._doc_type,
            "busy": self._busy.locked(), "usage": self._last_usage,
            "candidates": self._pop_candidates(),
            "mode": self._mode, "limits": self._limits, "version": __version__,
            "settings": {"presets": DEFAULT_PRESETS, **self._settings}, "models": self._models,
        }

    def login_start(self) -> str:
        """[ChatGPT로 로그인]. 브라우저를 닫고 로그인하지 않으면 `codex login`이 끝나지 않아 버튼이 멈추고
        로그인 포트(1455)를 계속 잡아 다음 시도도 실패하므로 LOGIN_TIMEOUT 뒤 끝낸다 (2026-11-11 점검)."""
        import subprocess

        self._stop_login()
        p = self._login_proc = cr.start_login()
        try:
            p.wait(timeout=LOGIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._stop_login()
        self._login = cr.login_status()
        return self._login

    def _stop_login(self) -> None:
        p, self._login_proc = getattr(self, "_login_proc", None), None
        if p and p.poll() is None:
            p.kill()
            p.wait(5)

    # --- 대화 ---
    def _on_progress(self, pct: int, step: str) -> None:
        if pct >= self._progress["pct"]:
            self._progress.update(pct=pct, step=step)

    def progress(self) -> dict:
        """작업 중 진행률 (COM을 부르지 않아 빠르다). 화면이 1초마다 부른다."""
        p = self._progress
        return {"pct": p["pct"], "step": p["step"], "sec": int(time.time() - p["start"]) if p["start"] else 0}

    def _leftover_checks(self, applied: list[dict], checks: list[dict]) -> list[dict]:
        """요청이 끝난 뒤 코드가 한 번 더: 바뀐 옛 연도가 문서에 남았으면 빨간 표시 + 확인 목록."""
        pairs = [(a["find"], a["replace"]) for a in applied if a.get("count")]
        try:
            left = leftover_years(self._bridge.read_text(), changed_years(pairs), [c["text"] for c in checks])
            for c in left:
                self._bridge.mark_check(c["text"], c["nth"])
        except HwpNotAvailable:
            return []
        return [{"text": c["text"], "nth": c["nth"], "note": c["note"]} for c in left]

    def _final_checks(self, checks: list[dict], recheck_amounts: bool = True) -> list[dict]:
        """요청이 끝난 문서 기준으로 확인 목록 정리: 그사이 바뀌어 없어진 문구는 빼고, 금액 점검은 (금액을 바꿨을 때만) 최종 문서로 다시,
        같은 곳은 한 번만(마지막 설명)."""
        try:
            doc = self._bridge.read_text()
        except HwpNotAvailable:
            return checks
        budget = [{"text": c.text, "note": c.note} for c in amount_checks(doc)] if recheck_amounts else []
        for c in budget:
            self._bridge.mark_check(c["text"])
        alive = [c for c in checks if not c["note"].startswith(AMOUNT_NOTES) and resolve_text(c["text"], doc) in doc]
        return list({(c["text"], c.get("nth", 0)): c for c in alive + budget}.values())

    def save_pasted_image(self, data_url: str) -> dict:
        """스크린샷 붙여넣기(Ctrl+V): 화면이 준 그림을 파일로 저장해 첨부 목록에."""
        return attachments.save_pasted(data_url, paths.pasted_dir(), time.strftime("%H%M%S"))

    def clipboard_files(self) -> list[dict]:
        """탐색기에서 복사한 파일 붙여넣기: 클립보드의 실제 경로."""
        return [{"path": p, "name": Path(p).name} for p in attachments.clipboard_paths()]

    def pick_files(self) -> list[dict]:
        """[📎] 버튼: 파일 고르기 창. 고른 파일의 경로·이름 (보낼 때 send에 경로를 다시 넘긴다)."""
        import webview

        paths_ = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                                 file_types=attachments.DIALOG_FILTER) or []
        return [{"path": p, "name": Path(p).name} for p in paths_]

    def send(self, text: str, files: list[str] | None = None, personal: bool = False) -> dict:
        """personal: 사용자가 '개인정보 수정 허용'을 눌러 다시 보낸 요청 — 이번 요청에서만 개인정보도 고친다."""
        if not text.strip():
            return {"error": "요청을 입력해 주세요"}
        if not self._busy.acquire(blocking=False):
            return {"error": "이전 요청을 처리하는 중입니다"}
        try:
            if not self._connected():
                return {"error": "한글 문서를 열어 주세요"}
            self._sync_target(self._bridge.target_name())
            if self._snapshot is not None:
                self._learn_now()  # 지난 요청 뒤 사용자가 직접 고친 것 먼저 확인
            self._progress = {"pct": 0, "step": "", "start": time.time()}
            images, attached, notes = attachments.prepare(files or [])
            r = cr.run_turn(self._with_undo_note(text), self._rules_for_prompt(), self._thread_id, on_progress=self._on_progress,
                            model=self._settings.get("model") or None, images=images, attached=attached,
                            personal=personal, preview=bool(self._settings.get("preview")))
            pairs = [(a["find"], a["replace"]) for a in r.applied if a.get("count")]
            if not images:  # 그림을 첨부한 요청은 그 부분만 — 문서 전체 점검(옛 연도·금액)을 하지 않음
                r.checks += self._leftover_checks(r.applied, r.checks)
            r.checks = self._final_checks(r.checks, recheck_amounts=not images and touches_amount(pairs))
            try:
                self._snapshot = self._bridge.read_text()
            except HwpNotAvailable:
                pass
            if r.error == "login":
                self._login = "logged_out"
            self._thread_id = r.thread_id or self._thread_id
            self._doc_type = r.doc_type or self._doc_type
            self._last_usage = r.usage
            self._limits = cr.read_rate_limits(r.thread_id) or self._limits
            self._bridge.remember_marks([a["replace"] for a in r.applied if a.get("count")]
                                        + [m for d in r.done for m in d.get("marks", [])])
            self._bridge.remember_marks([c["text"] for c in r.checks if not c.get("note", "").startswith(NO_MARK_NOTES)], RED)
            for a in r.applied + [d for d in r.done if d.get("undo")]:  # 항목마다 [↶] 되돌리기용 번호
                if a.get("count") or a.get("undo"):
                    a["id"] = uuid.uuid4().hex[:8]
                    self._log[a["id"]] = a
            for p in r.proposed:  # 미리 보기: 패널에서 고르면 apply_proposed로 적용
                p["id"] = uuid.uuid4().hex[:8]
                self._proposed[p["id"]] = p
            ask = not personal and (cr.asks_permission(r.reply) or any(c.get("note", "").startswith(PROTECTED_NOTE) for c in r.checks))
            return {"reply": cr.strip_permission(r.reply), "changes": r.applied, "checks": r.checks, "done": r.done,
                    "proposed": r.proposed,
                    "askPersonal": ask,
                    "docType": self._doc_type, "error": r.error, "usage": r.usage,
                    "candidates": self._pop_candidates(), "attachNotes": notes}
        finally:
            self._busy.release()

    def _with_undo_note(self, text: str) -> str:
        """되돌린 뒤 같은 대화로 처음 보내는 요청: AI는 되돌린 걸 모르니 알려 준다."""
        notes, self._undone = self._undone, []
        if not (notes and self._thread_id):
            return text
        return f"[참고: 사용자가 패널에서 직접 한 일: {', '.join(notes)}]\n" + text

    def undo_item(self, item_id: str) -> dict:
        """항목 옆 [↶]: 그 수정(같은 요청에서 바꾼 모든 자리)을 원래 글로. 그사이 사용자가 고친 자리는 건드리지 않는다."""
        return self._toggle(item_id, undo=True)

    def redo_item(self, item_id: str) -> dict:
        """되돌린 항목의 [↷]: 그 수정을 다시 적용한다."""
        return self._toggle(item_id, undo=False)

    def _toggle(self, item_id: str, undo: bool) -> dict:
        rec = self._log.get(item_id)
        if not rec or bool(rec.get("undone")) == undo:
            return {"error": "이 항목은 지금 바꿀 수 없습니다 (다른 문서로 바뀌었거나 이미 처리됨)"}
        if not self._busy.acquire(blocking=False):
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            if "undo" in rec:  # 서식·표·넣기: 도구 서버가 적어 둔 되돌리기·다시 하기 작업
                done, skipped = self._run_ops(rec, undo)
            else:
                done, skipped = (self._bridge.undo if undo else self._bridge.redo)([rec])
            self._snapshot = self._bridge.read_text()  # 패널에서 한 것을 '사용자가 직접 고친 것'으로 배우지 않게
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()
        if done:
            rec["undone"] = undo
            if hasattr(self._bridge, "_marks"):
                marks = rec.get("marks") or ([rec["replace"]] if "replace" in rec else [])
                if undo:
                    active = {m for r in self._log.values() if not r.get("undone")
                              for m in (r.get("marks") or ([r["replace"]] if "replace" in r else []))}
                    for m in marks:
                        if m not in active:
                            self._bridge._marks.pop(m, None)
                elif hasattr(self._bridge, "remember_marks"):
                    self._bridge.remember_marks(marks)
            note = (f"{rec['label']} 되돌림" if "label" in rec
                    else f"{rec['find']} → {rec['replace']} 되돌림(원래 글로 돌아감)")
            if undo:
                self._undone.append(note)
            elif note in self._undone:  # AI에게 알리기 전에 다시 적용했으면 알릴 것 없음
                self._undone.remove(note)
            else:
                self._undone.append(f"{rec['label']} 다시 적용" if "label" in rec
                                    else f"{rec['find']} → {rec['replace']} 다시 적용")
        return {"restored": done, "skipped": skipped}

    def _run_ops(self, rec: dict, undo: bool) -> tuple[int, int]:
        """↶·↷: 기록된 작업을 이 패널의 HwpBridge로 실행. (된 수, 안 된 수) — 그사이 문서가 바뀌어 자리가 없으면 안 됨."""
        ok = bad = 0
        for o in rec["undo" if undo else "redo"]:
            if o.get("op") not in UNDO_OPS:  # 도구 서버가 적은 것 중 정해 둔 작업만
                bad += 1
                continue
            self._bridge.undo_spec = None
            r = getattr(self._bridge, o["op"])(*o["args"])
            if isinstance(r, str) or r is False or r == 0:
                bad += 1
            else:
                ok += 1
        if not undo and ok and self._bridge.undo_spec:  # 다시 넣었으면 자리가 새로 생김 → 다음 ↶는 새 자리로
            rec["undo"] = self._bridge.undo_spec
        return ok, bad

    # --- 미리 보기 · 문서 검토 · 신구대조표 ---
    def apply_proposed(self, ids: list[str]) -> dict:
        """미리 보기 목록에서 고른 글 바꾸기만 적용 (AI 없이). 결과는 보내기와 같은 꼴 → 화면이 '바꾼 곳'으로."""
        picked = [self._proposed.pop(i) for i in ids if i in self._proposed]
        if not picked:
            return {"error": "적용할 항목이 없습니다 (이미 적용했거나 다른 문서로 바뀜)"}
        if not self._busy.acquire(blocking=False):
            for p in picked:
                self._proposed[p["id"]] = p
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            edits = [Edit(p["find"], p["replace"], p.get("reason", ""), None if p.get("nths") is None else tuple(p["nths"]))
                     for p in picked]
            changes = []
            for e, n, pos in self._bridge.apply(edits):
                a = {"find": e.find, "replace": e.replace, "count": n, "pos": pos}
                if n:
                    a["id"] = uuid.uuid4().hex[:8]
                    self._log[a["id"]] = a
                changes.append(a)
            pairs = [(a["find"], a["replace"]) for a in changes if a["count"]]
            checks = self._final_checks(self._leftover_checks(changes, []), touches_amount(pairs))
            self._bridge.remember_marks([a["replace"] for a in changes if a["count"]])
            self._bridge.remember_marks([c["text"] for c in checks], RED)
            self._snapshot = self._bridge.read_text()
            self._undone.append(f"미리 보기 제안 중 {len(pairs)}개를 사용자가 골라 적용함")
            return {"changes": changes, "checks": checks}
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()

    def review(self) -> dict:
        """[문서 검토]: AI 없이 규칙으로 문서 전체 점검 — 고치지 않고 빨간 표시와 확인 목록만 (사용량 0)."""
        if not self._busy.acquire(blocking=False):
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            checks = [{"text": c.text, "note": c.note} for c in review_document(self._bridge.read_text())]
            for c in checks:
                self._bridge.mark_check(c["text"])
            self._bridge.remember_marks([c["text"] for c in checks], RED)
            return {"checks": checks}
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()

    def change_table(self) -> dict:
        """[신구대조표]: 이 문서에서 바꾼 글(되돌리지 않은 것)을 문서 끝에 '수정 전 | 수정 후' 표로. ↶로 뺄 수 있다."""
        recs = [r for r in self._log.values() if "replace" in r and r.get("count") and not r.get("undone")]
        if not recs:
            return {"error": "표로 만들 바꾼 글이 없습니다 (이 문서에서 패널로 바꾼 것만)"}
        if not self._busy.acquire(blocking=False):
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            rows = [["연번", "수정 전", "수정 후", "곳"]] + [[str(i), r["find"], r["replace"], str(r["count"])]
                                                        for i, r in enumerate(recs, 1)]
            title = CHANGE_TABLE_TITLE + " (" + time.strftime("%Y. %m. %d.") + ")"
            why = self._bridge.append_table(title, rows)
            if why:
                return {"error": why}
            d = {"label": f"신구대조표 {len(recs)}건 (문서 끝)", "at": title, "marks": [],
                 "undo": self._bridge.undo_spec, "redo": [{"op": "append_table", "args": [title, rows]}],
                 "id": uuid.uuid4().hex[:8]}
            self._log[d["id"]] = d
            self._snapshot = self._bridge.read_text()
            return {"done": [d]}
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()

    def delete_change_tables(self) -> dict:
        """[대조표 지우기]: 문서의 신구대조표(제목+표)를 모두 지운다 — 이전에 만든 것도. 한글 Ctrl+Z로 되돌림."""
        if not self._busy.acquire(blocking=False):
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            n = self._bridge.delete_titled_tables(CHANGE_TABLE_TITLE)
            if not n:
                return {"error": "문서에 신구대조표가 없습니다"}
            for r in self._log.values():  # 패널 목록의 ↶가 이미 지운 표를 또 지우지 않게
                if any(x.get("op") == "append_table" for x in r.get("redo") or []):
                    r["undone"] = True
            self._snapshot = self._bridge.read_text()
            return {"deleted": n}
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()

    def new_conversation(self) -> None:
        self._thread_id = None

    def set_doc_type(self, name: str) -> None:
        self._doc_type = name.strip() or None

    # --- 문서 ---
    def goto(self, text: str, nth: int = 0) -> bool:
        """목록 항목을 누르면 한글에서 그곳을 선택하고 한글 창을 앞으로."""
        try:
            ok = self._bridge.goto(resolve_text(text, self._bridge.read_text()), nth)
        except HwpNotAvailable:
            return False
        if ok and (hwp := find_hwp_window()):
            import ctypes

            ctypes.windll.user32.SetForegroundWindow(hwp)  # 패널은 한글 소유·자식 창이라 계속 위에 보임
        return ok

    def restore_marks(self) -> int:
        try:
            return self._bridge.restore_marks()
        except HwpNotAvailable:
            return 0

    def clear_marks(self) -> int:
        try:
            return self._bridge.clear_marks()
        except HwpNotAvailable:
            return 0

    def clear_all_marks(self) -> dict:
        """윗줄 [🖍]: 문서의 형광펜 전부 (남은 표시·직접 칠한 것 포함). 요청 처리 중엔 안 함."""
        if not self._busy.acquire(blocking=False):
            return {"error": "요청 처리가 끝난 뒤 눌러 주세요"}
        try:
            return {"cleared": self._bridge.clear_all_marks(), "memos": self._bridge.delete_memos()}
        except HwpNotAvailable:
            return {"error": "한글 문서를 열어 주세요"}
        finally:
            self._busy.release()

    # --- 기억 ---
    def memory_list(self, doc_type: str | None = None) -> list[str]:
        t = doc_type or self._doc_type
        return self._memory.rules(t) if t else []

    def memory_add(self, rule: str, doc_type: str | None = None) -> None:
        t = doc_type or self._doc_type
        if t:
            self._memory.add(t, rule)

    def memory_update(self, index: int, rule: str) -> None:
        if self._doc_type:
            self._memory.update(self._doc_type, index, rule)

    def memory_delete(self, index: int) -> None:
        if self._doc_type:
            self._memory.delete(self._doc_type, index)


def _load_settings() -> dict:
    try:
        return json.loads((paths.app_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(d: dict) -> None:
    (paths.app_dir() / "settings.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _embed_mode() -> bool:
    """한글 안에 넣기: run.pyw --embed 또는 환경변수 HWPGPT_MODE=embed. 기본은 옆에 붙이기."""
    return "--embed" in sys.argv or os.environ.get("HWPGPT_MODE") == "embed"


def _dock_loop(api: Api, stop: threading.Event) -> None:
    import win32gui

    panel = 0
    while not panel and not stop.is_set():
        panel = win32gui.FindWindow(None, TITLE)
        stop.wait(0.3)
    api._panel_hwnd = panel
    if panel and api._mode == "dock":  # 처음 뜰 때부터 붙을 자리(오른쪽)에 — 숨긴 채 옮긴 뒤 보여 줌
        try:
            place_right(panel)
        finally:
            api._window.show()
    elif panel:
        api._window.show()
    gone = threading.Event()

    def make():
        return (EmbedDocker if api._mode == "embed" else Docker)(panel, on_hwp_gone=gone.set)

    docker = make()
    while not stop.is_set():
        hwp = find_hwp_window()
        if not hwp:
            stop.wait(2)
            continue
        gone.clear()
        docker.attach(hwp)
        while not (gone.is_set() or stop.is_set()):
            if api._mode_changed.is_set():  # [한글 안/옆] 버튼
                api._mode_changed.clear()
                docker.detach()
                docker = make()
                docker.attach(hwp)
            stop.wait(0.3)
    docker.detach()


def dropped_files(event: dict) -> list[dict]:
    """패널에 끌어다 놓은 파일들 (경로·이름). 실제 경로는 pywebview가 Python 쪽 drop 처리기에만 넣어 준다."""
    out = []
    for f in (event.get("dataTransfer") or {}).get("files", []):
        if p := f.get("pywebviewFullPath"):
            out.append({"path": p, "name": Path(p).name})
    return out


def _wire_drop(window) -> None:
    """패널 어디에 파일을 놓아도 첨부 목록에 넣는다 (📎과 같은 곳으로)."""
    from webview.dom import DOMEventHandler

    def on_drop(e):
        if files := dropped_files(e):
            window.evaluate_js(f"window.addFiles({json.dumps(files, ensure_ascii=False)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)


def main() -> None:
    import webview

    api = Api()
    stop = threading.Event()
    api._window = webview.create_window(TITLE, url=str(UI), js_api=api, width=380, height=900,
                                       min_size=(320, 400), hidden=True)  # _dock_loop가 오른쪽에 둔 뒤 보여 줌
    api._window.events.loaded += lambda: _wire_drop(api._window)
    t = threading.Thread(target=_dock_loop, args=(api, stop), daemon=True)
    t.start()
    webview.start(gui="edgechromium", icon=str(ICON))
    stop.set()
    t.join(3)  # 패널을 닫으면 한글 창 크기 원래대로
    api._stop_login()  # 로그인 중에 닫으면 남은 codex login이 포트를 잡지 않게
    api._worker.stop()


if __name__ == "__main__":
    main()
