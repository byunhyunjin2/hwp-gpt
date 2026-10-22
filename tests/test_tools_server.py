from hwpgpt import session
from hwpgpt.tools_server import Tools


def test_apply_rejects_id_edit_marks_red_and_logs(fake_bridge, tmp_path):
    fake_bridge.text = "학번 202699001"
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    out = t.apply_edits([{"find": "2026", "replace": "2027", "reason": "연도"}])
    assert out["applied"] == [] and len(out["checks"]) == 1
    assert fake_bridge.applied == [] and fake_bridge.red == ["2026"]
    assert session.read(tmp_path / "s.jsonl")[0]["kind"] == "check"


def test_apply_ok_logged(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획"
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    out = t.apply_edits([{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}])
    assert out["applied"][0]["count"] == 1
    assert session.read(tmp_path / "s.jsonl")[0]["data"]["replace"] == "2027학년도"


def test_read_document_is_compact_and_logs_doc_type(fake_bridge, tmp_path):
    fake_bridge.text = "제목\r\n\r\n   본문   첫 줄  \r\n\r\n\r\n둘째 줄"
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    assert t.read_document("공문") == {"text": "제목\n본문 첫 줄\n둘째 줄"}
    assert session.read(tmp_path / "s.jsonl") == [{"kind": "doc_type", "data": {"name": "공문"}}]


def test_find_lines_returns_only_matching_lines(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획\r\n추진 배경 문단\r\n기간: 2026. 10. 31.(토)\r\n학번 202699001"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").find_lines(r"20\d\d", "계획서")
    assert out["lines"] == ["2026학년도 계획", "기간: 2026. 10. 31.(토)", "학번 202699001"]
    assert out["total_lines"] == 4


def test_find_lines_caps_and_bad_regex(fake_bridge, tmp_path):
    fake_bridge.text = "\n".join(f"2026 줄{i}" for i in range(200))
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    assert len(t.find_lines("2026")["lines"]) == 80
    assert "error" in t.find_lines("([")


def test_mark_check_logged(fake_bridge, tmp_path):
    fake_bridge.text = "전년도 실적 2025년"
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    t.mark_check("2025년", "전년도 실적은 확인 필요")
    assert [r["kind"] for r in session.read(tmp_path / "s.jsonl")] == ["check"]
    assert fake_bridge.red == ["2025년"]


def test_apply_edits_also_marks_checks_in_same_call(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획 / 전년도 실적: 2025년 만족도 4.5점"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}],
        checks=[{"text": "전년도 실적: 2025년 만족도 4.5점", "note": "2026년 실적으로 갱신 필요"}])
    assert out["applied"][0]["count"] == 1
    assert fake_bridge.red == ["전년도 실적: 2025년 만족도 4.5점"]
    assert out["checks"][0]["note"] == "2026년 실적으로 갱신 필요"


def test_apply_edits_checks_budget_automatically(fake_bridge, tmp_path):
    fake_bridge.text = "사업 예산 2,345,670원 / 식비 450,000 / 합계 2,345,670원"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "450,000", "replace": "500,000", "reason": "예산 변경"}])
    assert out["applied"][0]["count"] == 1
    assert out["checks"] == []  # 합계·사업 예산은 서로 같으니 불일치 없음
    fake_bridge.text = "사업 예산 2,345,670원 / 합계 3,700,000원"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "사업 예산 2,345,670원", "replace": "사업 예산 3,800,000원", "reason": "예산"}])
    assert any("합계" in c["note"] for c in out["checks"])


def test_hwp_not_available_returns_error(dead_bridge, tmp_path):
    t = Tools(dead_bridge, tmp_path / "s.jsonl")
    assert "error" in t.read_document()
    assert "error" in t.apply_edits([{"find": "a", "replace": "b", "reason": ""}])


def test_apply_reports_leftover_old_year(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획\r\n신청일 2026년 9월 1일"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}])
    assert out["leftover"] == ["신청일 2026년 9월 1일"]


def test_leftover_skips_lines_ai_marked_as_check(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획\r\n2026년 실적 100%"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}],
        checks=[{"text": "2026년 실적", "note": "전년도 실적"}])
    assert "leftover" not in out and out["checks"][0]["text"] == "2026년 실적"


def test_year_changed_date_is_marked_red_for_review(fake_bridge, tmp_path):
    fake_bridge.text = "기간: 2026. 10. 31.(토)"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026. 10. 31.(토)", "replace": "2027. 10. 31.(일)", "reason": "연도"}])
    assert out["applied"][0]["count"] == 1
    assert fake_bridge.red == ["2027. 10. 31.(일)"] and "날짜 확인" in out["checks"][0]["note"]


def test_check_and_edit_work_despite_double_spaces(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도\r\n신청일 2026년  9월  1일"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}],
        checks=[{"text": "2026년 9월 1일", "note": "신청일"}])
    assert fake_bridge.red[0] == "2026년  9월  1일" and out["checks"][0]["text"] == "2026년  9월  1일"


def test_amount_edit_retries_without_won(fake_bridge, tmp_path):
    fake_bridge.text = "합계\r\n1,234,560원"
    real_apply = fake_bridge.apply
    # 한글 표 칸처럼 '원'이 붙은 문구로는 못 찾는 상황
    fake_bridge.apply = lambda edits: [(e, 0) if e.find.endswith("원") else real_apply([e])[0] for e in edits]
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "1,234,560원", "replace": "1,000,000원", "reason": ""}])
    assert out["applied"][0] == {"find": "1,234,560", "replace": "1,000,000", "count": 1}
    assert "1,000,000원" in fake_bridge.text
