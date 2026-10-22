from hwpgpt import session


def test_write_and_read_roundtrip(tmp_path):
    p = tmp_path / "s.jsonl"
    session.write(p, "applied", {"find": "2026학년도", "replace": "2027학년도", "count": 1})
    session.write(p, "check", {"text": "202699001", "note": "식별번호"})
    rows = session.read(p)
    assert [r["kind"] for r in rows] == ["applied", "check"]
    assert rows[0]["data"]["replace"] == "2027학년도"


def test_read_missing_file_is_empty(tmp_path):
    assert session.read(tmp_path / "none.jsonl") == []
