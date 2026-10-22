from hwpgpt.memory import MemoryStore


def test_memory_roundtrip_and_manual_edit(tmp_path):
    m = MemoryStore(tmp_path)
    m.add("앵커사업 운영계획서", "날짜는 요일까지 맞춘다")
    (tmp_path / "앵커사업 운영계획서.md").write_text(
        "# 앵커사업 운영계획서\n\n- 날짜는 요일까지 맞춘다\n- 책임교원 이름은 유지\n", encoding="utf-8")
    assert m.rules("앵커사업 운영계획서") == ["날짜는 요일까지 맞춘다", "책임교원 이름은 유지"]


def test_doc_type_name_is_filesystem_safe(tmp_path):
    MemoryStore(tmp_path).add("공문/표지", "x")
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_update_delete_and_list_types(tmp_path):
    m = MemoryStore(tmp_path)
    m.add("공문", "a")
    m.add("공문", "b")
    m.update("공문", 0, "a2")
    m.delete("공문", 1)
    assert m.rules("공문") == ["a2"] and m.doc_types() == ["공문"]


def test_unknown_type_is_empty(tmp_path):
    assert MemoryStore(tmp_path).rules("없음") == []


def test_duplicate_rule_not_added(tmp_path):
    m = MemoryStore(tmp_path)
    m.add("공문", "a")
    m.add("공문", "a")
    assert m.rules("공문") == ["a"]
