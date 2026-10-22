import json

from hwpgpt import updater


def test_version_rule_rolls_over_at_9():
    assert updater.next_version("1.0.1") == "1.0.2"
    assert updater.next_version("1.0.9") == "1.1.0"
    assert updater.next_version("1.9.9") == "2.0.0"
    assert updater.parse("v1.1.0") > updater.parse("1.0.9")


def test_check_compares_with_latest_json(monkeypatch):
    info = {"version": "1.0.2", "notes": "- 고침", "setup": "HWP_GPT-Setup-1.0.2.exe", "sha256": "ab"}
    monkeypatch.setattr(updater, "_get", lambda url, timeout: json.dumps(info).encode())
    assert updater.check("1.0.1")["available"] and not updater.check("1.0.2")["available"]


def test_check_offline_is_not_an_error_for_the_panel(monkeypatch):
    def boom(url, timeout):
        raise OSError("오프라인")

    monkeypatch.setattr(updater, "_get", boom)
    r = updater.check("1.0.1")
    assert r["available"] is False and "오프라인" in r["error"]


def test_download_rejects_hash_mismatch(monkeypatch, tmp_path):
    import hashlib
    import io

    import pytest

    class Resp(io.BytesIO):
        headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: Resp(b"data"))
    good = {"version": "1.0.2", "setup": "s.exe", "sha256": hashlib.sha256(b"data").hexdigest()}
    assert updater.download(good).read_bytes() == b"data"
    with pytest.raises(ValueError):
        updater.download({**good, "sha256": "00"})
    assert not (tmp_path / "s.exe").exists()


def test_check_removes_leftover_setup_files(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "HWP_GPT-Setup-1.0.1.exe").write_bytes(b"x")
    (tmp_path / "다른파일.exe").write_bytes(b"x")
    monkeypatch.setattr(updater, "_get", lambda url, timeout: b'{"version": "1.0.1"}')
    updater.check("1.0.1")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["다른파일.exe"]
