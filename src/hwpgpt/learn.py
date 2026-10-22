"""사용자가 직접 고친 내용을 찾아 규칙 후보로 만든다. 저장은 하지 않는다 (패널이 물어보고 저장)."""
import difflib
import re
import subprocess
from dataclasses import dataclass

from . import codex_runner as cr


@dataclass
class Change:
    before: str
    after: str
    context: str


def _lines(text: str) -> list[str]:
    return [ln for ln in re.split(r"\r\n|\r|\n", text)]


def _trivial(a: str, b: str) -> bool:
    """오타 수준: 바뀐 글자 2개 이하이고 숫자는 그대로."""
    if re.findall(r"\d", a) != re.findall(r"\d", b):
        return False
    sm = difflib.SequenceMatcher(None, a, b)
    changed = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")
    return changed <= 2


def diff_changes(old: str, new: str) -> list[Change]:
    a, b = _lines(old), _lines(new)
    out: list[Change] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        olds, news = a[i1:i2], b[j1:j2]
        for k in range(max(len(olds), len(news))):
            before = olds[k] if k < len(olds) else ""
            after = news[k] if k < len(news) else ""
            if before.strip() == after.strip() or _trivial(before, after):
                continue
            ctx = a[i1 - 1] if i1 > 0 else ""
            out.append(Change(before, after, ctx))
    return out


def parse_rule_lines(reply: str, limit: int = 3) -> list[str]:
    """AI 답변에서 '- ' 로 시작하는 규칙 줄만 뽑는다."""
    rules = [ln.strip()[2:].strip() for ln in reply.splitlines() if ln.strip().startswith("- ")]
    return [r for r in rules if r][:limit]


def propose_rules(doc_type: str, changes: list[Change]) -> list[str]:
    """ChatGPT에 변경 목록을 보여 주고 다음에도 적용할 규칙 후보를 받는다 (도구 없이 1회)."""
    if not changes:
        return []
    codex = cr.find_codex()
    if not codex:
        return []
    listing = "\n".join(f"- 전: {c.before!r} → 후: {c.after!r}" for c in changes[:20])
    prompt = (
        f"사용자가 '{doc_type}' 문서를 AI가 고친 뒤 직접 아래처럼 다시 고쳤다.\n{listing}\n\n"
        "내년에 같은 종류 문서를 AI가 고칠 때 미리 지킬 규칙을 최대 3개, 한 줄씩 '- '로 시작해 한국어로 써라. "
        "사용자가 하나씩 확인한 뒤 저장하므로, 한 번 고친 것이라도 다음에 다시 쓸 만하면(날짜를 정하는 방식, "
        "선호하는 표현, 장소·명칭을 적는 방식 등) 제안하라. 단순 오타 수정만 제외하고, 정말 없으면 '없음'이라고만 써라. "
        "도구·셸은 쓰지 마라."
    )
    cmd = [str(codex), "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
           "--ephemeral", prompt]
    try:
        r = subprocess.run(cmd, cwd=cr.paths.work_dir(), env=cr.codex_env(), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, creationflags=cr.NO_WINDOW, timeout=300)
    except subprocess.TimeoutExpired:
        return []
    return parse_rule_lines(cr.parse_events((r.stdout or "").splitlines()).reply)
