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
    assert t.read_document("공문") == {"text": "1| 제목\n2| 본문 첫 줄\n3| 둘째 줄"}
    assert session.read(tmp_path / "s.jsonl") == [{"kind": "doc_type", "data": {"name": "공문"}}]


def test_find_lines_returns_only_matching_lines(fake_bridge, tmp_path):
    fake_bridge.text = "2026학년도 계획\r\n추진 배경 문단\r\n기간: 2026. 10. 31.(토)\r\n학번 202699001"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").find_lines(r"20\d\d", "계획서")
    assert out["lines"] == ["1| 2026학년도 계획", "3| 기간: 2026. 10. 31.(토)", "4| 학번 202699001"]
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
    fake_bridge.apply = lambda edits: [(e, 0, []) if e.find.endswith("원") else real_apply([e])[0] for e in edits]
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "1,234,560원", "replace": "1,000,000원", "reason": ""}])
    assert {k: out["applied"][0][k] for k in ("find", "replace", "count")} == {"find": "1,234,560", "replace": "1,000,000", "count": 1}
    assert "1,000,000원" in fake_bridge.text


def test_lines_limit_edit_to_that_table_cell(fake_bridge, tmp_path):
    # 본문의 "6시간"·학번은 그대로, 표의 참여시간 칸 "6"만 (사용자가 표 캡처를 붙여 요청한 경우)
    fake_bridge.text = "참여시간 6시간 운영\r\n학번 202699061\r\n이수율\r\n참여시간\r\n100%\r\n6\r\n4.0"
    t = Tools(fake_bridge, tmp_path / "s.jsonl")
    lines = t.find_lines(r"^6$|^4\.0$")["lines"]
    assert lines == ["6| 6", "7| 4.0"]
    out = t.apply_edits([{"find": "6", "replace": "8", "lines": [6]}, {"find": "4.0", "replace": "5.0", "lines": [7]}])
    assert [a["count"] for a in out["applied"]] == [1, 1] and out["checks"] == []
    assert fake_bridge.text == "참여시간 6시간 운영\r\n학번 202699061\r\n이수율\r\n참여시간\r\n100%\r\n8\r\n5.0"


def test_short_find_without_lines_is_refused(fake_bridge, tmp_path):
    fake_bridge.text = "참여시간 6시간\r\n6"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits([{"find": "6", "replace": "8"}])
    assert out["applied"] == [] and "줄 번호" in out["checks"][0]["note"] and fake_bridge.text == "참여시간 6시간\r\n6"


def test_find_lines_around_shows_table_headers(fake_bridge, tmp_path):
    fake_bridge.text = "달성 목표값\r\n이수율\r\n참여시간\r\n100%\r\n6\r\n본문\r\n구분\r\n참여율\r\n6"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").find_lines(r"^6$", around=2)
    assert out["lines"] == ["3| 참여시간", "4| 100%", "5| 6", "6| 본문", "7| 구분", "8| 참여율", "9| 6"]


def test_image_request_only_edits_given_lines_and_skips_doc_wide_checks(fake_bridge, tmp_path):
    fake_bridge.text = "사업 예산 1,000,000원\r\n합계 9,999,999원\r\n참여시간 6시간\r\n참여시간\r\n6"
    t = Tools(fake_bridge, tmp_path / "s.jsonl", scoped=True)
    out = t.apply_edits([{"find": "참여시간 6시간", "replace": "참여시간 8시간"},  # 위치 없음 → 거부
                         {"find": "6", "replace": "8", "lines": [5]}])
    assert [a["find"] for a in out["applied"]] == ["6"]
    assert len(out["checks"]) == 1 and "그림 부분만" in out["checks"][0]["note"]  # 합계 불일치는 안 뜸
    assert fake_bridge.text.endswith("참여시간 6시간\r\n참여시간\r\n8")


def test_amount_checks_only_when_amounts_change(fake_bridge, tmp_path):
    fake_bridge.text = "사업 예산 1,000,000원\r\n합계 9,999,999원\r\n2026학년도"
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "2026학년도", "replace": "2027학년도", "reason": "연도"}])
    assert out["checks"] == []  # 금액을 안 건드린 요청에 예산 불일치를 띄우지 않음


def test_personal_edit_blocked_until_user_allows(tmp_path, fake_bridge):
    from hwpgpt.tools_server import Tools

    fake_bridge.text = "참석자 명단\r\n홍길동 010-0000-0000\r\n김철수 010-1111-1111"
    out = Tools(fake_bridge, tmp_path / "a.jsonl").apply_edits([{"find": "홍길동", "replace": "이영희"}])
    assert out["applied"] == [] and out["checks"][0]["note"].startswith("보호 대상")
    out = Tools(fake_bridge, tmp_path / "b.jsonl", personal=True).apply_edits([{"find": "홍길동", "replace": "이영희"}])
    assert out["applied"][0]["count"] == 1 and "이영희 010-0000-0000" in fake_bridge.text
