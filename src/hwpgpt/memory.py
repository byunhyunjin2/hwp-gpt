"""문서 종류별 기억(규칙) 저장소. 사람이 직접 열어 고칠 수 있는 마크다운 파일 하나 = 문서 종류 하나.

형식:
    # <문서 종류>

    - 규칙 1
    - 규칙 2
"""
import re
from pathlib import Path

from . import paths

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class MemoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else paths.memory_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, doc_type: str) -> Path:
        stem = _UNSAFE.sub("_", doc_type.strip()).strip(". ") or "기타"
        if stem.upper() in _RESERVED:
            stem = f"_{stem}"
        return self.root / f"{stem}.md"

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
        # 종류 이름은 AI가 정한다 → 줄바꿈이 있으면 "- …" 가짜 규칙 줄이 끼어들 수 있어 한 줄로 (2026-11-11 점검)
        self._file(doc_type).write_text(f"# {' '.join(doc_type.split())}\n\n{body}", encoding="utf-8")

    def add(self, doc_type: str, rule: str) -> None:
        rs = self.rules(doc_type)
        clean = " ".join(rule.split())
        if clean and clean not in rs:
            self._save(doc_type, rs + [clean])

    def update(self, doc_type: str, index: int, rule: str) -> None:
        rs = self.rules(doc_type)
        clean = " ".join(rule.split())
        if 0 <= index < len(rs) and clean:
            rs[index] = clean
            self._save(doc_type, rs)

    def delete(self, doc_type: str, index: int) -> None:
        rs = self.rules(doc_type)
        if 0 <= index < len(rs):
            del rs[index]
            self._save(doc_type, rs)
