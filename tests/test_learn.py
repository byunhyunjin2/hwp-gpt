from hwpgpt.learn import diff_changes, parse_rule_lines


def test_parse_rule_lines_takes_dash_lines_max_3():
    reply = "규칙입니다\n- 축제은 10월 마지막 토요일\n- 책임교원 이름 유지\n- a\n- b"
    assert parse_rule_lines(reply) == ["축제은 10월 마지막 토요일", "책임교원 이름 유지", "a"]
    assert parse_rule_lines("없음") == []


def test_diff_ignores_typo_keeps_meaningful():
    old = "교육 기간: 2027. 11. 6.(토)\n목표인원 45명\n추진 배겅"
    new = "교육 기간: 2027. 10. 30.(토)\n목표인원 45명\n추진 배경"
    ch = diff_changes(old, new)
    assert len(ch) == 1 and "10. 30." in ch[0].after and "11. 6." in ch[0].before


def test_diff_handles_cr_lf_and_added_line():
    ch = diff_changes("가\r\n나", "가\r\n나\r\n새 문장을 추가했습니다")
    assert len(ch) == 1 and ch[0].before == "" and "새 문장" in ch[0].after


def test_no_change():
    assert diff_changes("같음", "같음") == []
