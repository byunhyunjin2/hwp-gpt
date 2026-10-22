"""시험용 운영계획서(.hwp)를 만든다. 모든 이름·번호는 가짜 값이다 (개인정보 규칙).

사용: python scripts/make_sample.py [--long] [저장경로]
  기본: samples/시험_운영계획서_2026.hwp (*.hwp는 git 제외)
  --long: 실제 운영계획서 길이(약 9천 자)로 문단을 늘린 판 → samples/시험_운영계획서_2026_긴판.hwp (토큰 측정용)
전용 한글 인스턴스를 띄워 만들고 저장한 뒤 닫는다.
"""
import sys
from pathlib import Path

import win32com.client

LONG = "--long" in sys.argv
args = [a for a in sys.argv[1:] if a != "--long"]
name = "시험_운영계획서_2026_긴판.hwp" if LONG else "시험_운영계획서_2026.hwp"
OUT = Path(args[0] if args else Path(__file__).resolve().parent.parent / "samples" / name)

h = win32com.client.Dispatch("HWPFrame.HwpObject")
docs = h.XHwpDocuments
for i in range(docs.Count):
    assert not docs.Item(i).FullName, "전용 인스턴스에 실제 문서가 보여 중단"
A, P = h.HAction, h.HParameterSet


def text(t: str) -> None:
    A.GetDefault("InsertText", P.HInsertText.HSet)
    P.HInsertText.Text = t
    A.Execute("InsertText", P.HInsertText.HSet)


def para(t: str = "") -> None:
    if t:
        text(t)
    A.Run("BreakPara")


def table(rows: list[list[str]]) -> None:
    A.GetDefault("TableCreate", P.HTableCreation.HSet)
    P.HTableCreation.Rows, P.HTableCreation.Cols = len(rows), len(rows[0])
    A.Execute("TableCreate", P.HTableCreation.HSet)
    cells = [c for r in rows for c in r]
    for i, c in enumerate(cells):
        text(c)
        if i < len(cells) - 1:
            A.Run("TableRightCell")
    A.Run("MoveDocEnd")
    para()


para("2026학년도 앵커사업 프로그램 운영계획서")
para("과정명: 지역 축제 참여(2026 OO구 평생학습축제)")
para("책임교원: 김교수 (담당자 연락처 010-0000-0000)")
para("기간/장소: 2026. 10. 31.(토) / OO복지관")
para("목표인원: 학생 30명, 교원 4명 / 총 34명")
para("사업 예산: 사업 예산 2,345,670원")
para()
para("■ 추진 배경")
para("◦ 지역사회 평생학습문화 확산과 주민 참여형 학습의 장 마련 필요")
para("◦ 2026 OO구 평생학습축제 참여를 통한 현장 실무역량 강화")
if LONG:  # 실제 계획서처럼 연도와 무관한 긴 서술 문단 (가짜 문장)
    topics = ["추진 목표", "성과 지표", "추진 내용", "정량적 성과분석", "정성적 성과", "기대 성과", "운영 방법", "안전 관리"]
    for t in topics:
        para(f"■ {t}")
        for i in range(6):
            para(f"◦ 지역사회와 대학이 함께하는 평생학습 프로그램의 {t} 항목 {i + 1}: 참여자 의견을 반영하여 "
                 "현장 실무역량을 강화하고, 세대 간 소통과 학습 연계를 확대하며 운영 성과를 다음 기획에 반영한다.")
        para()
para()
para("■ 예산 계획(안)")
table([
    ["연번", "항목", "예산(원)", "산출내역"],
    ["1", "식비·다과", "340,000", "10,000원×34명"],
    ["2", "재료비", "1,880,670", "체험 재료 외"],
    ["3", "여비", "125,000", "25,000원×5회"],
    ["", "합계", "2,345,670원", ""],
])
para("■ 전년도 개선 사항 반영")
para("◦ 2025년 OO구 평생학습축제 운영 결과 참여율 95%, 만족도 4.5점")
para()
para("■ 참석자 명단 (2026. 10. 31.(토))")
table([
    ["연번", "학과", "학번", "이름"],
    ["1", "OO학과", "-", "김교수"],
    ["2", "OO학과", "202699001", "홍길동"],
    ["3", "OO학과", "202699002", "김철수"],
    ["4", "OO학과", "202699003", "이영희"],
])
OUT.parent.mkdir(parents=True, exist_ok=True)
h.SaveAs(str(OUT), "HWP", "")
print("만듦:", OUT)
h.XHwpDocuments.Item(0).Close(isDirty=False)
h.Quit()
