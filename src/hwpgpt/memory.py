"""문서 종류별 기억(규칙) 저장소. 사람이 직접 열어 고칠 수 있는 마크다운 파일 하나 = 문서 종류 하나.

형식:
    # <문서 종류>

    - 규칙 1
    - 규칙 2
"""
import re
from pathlib import Path

from . import paths

_UNSAFE = re.compile(r'[\\/:*?"<>|]')


class MemoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else paths.memory_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, doc_type: str) -> Path:
        return self.root / (_UNSAFE.sub("_", doc_type.strip()) + ".md")

    def doc_types(self) -> list[str]:
        out = []
        for f in sorted(self.root.glob("*.md")):
            first = f.read_text(encoding="utf-8").splitlines()[:1]
            out.append(first[0][2:].strip() if first and first[0].startswith("# ") else f.stem)
        return out

    def rules(self, doc_type: str) -> list[str]:
        f = self._file(doc_type)
        if not f.exists():
            return []
        return [ln[2:].strip() for ln in f.read_text(encoding="utf-8").splitlines()
                if ln.startswith("- ") and ln[2:].strip()]

    def _save(self, doc_type: str, rules: list[str]) -> None:
        body = "".join(f"- {r}\n" for r in rules)
        self._file(doc_type).write_text(f"# {doc_type}\n\n{body}", encoding="utf-8")

    def add(self, doc_type: str, rule: str) -> None:
        rs = self.rules(doc_type)
        if rule.strip() and rule.strip() not in rs:
            self._save(doc_type, rs + [rule.strip()])

    def update(self, doc_type: str, index: int, rule: str) -> None:
        rs = self.rules(doc_type)
        rs[index] = rule.strip()
        self._save(doc_type, rs)

    def delete(self, doc_type: str, index: int) -> None:
        rs = self.rules(doc_type)
        del rs[index]
        self._save(doc_type, rs)
