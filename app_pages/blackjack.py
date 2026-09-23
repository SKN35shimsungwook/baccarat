# -*- coding: utf-8 -*-
"""블랙잭 테이블 페이지 (최대 3자리).

- 판 진행과 정산은 bj/game.py 의 BJTable 이 한다. 화면(frontend/blackjack.*)은 to_view() 결과를 그린다.
  JS → 파이썬: setTriggerValue("deal" | "action" | "insurance")
- 한 단계가 끝날 때마다 ss.bj_step 에 id를 올려서, 화면이 새로 나온 카드만 애니메이션하게 한다.
- 판이 끝나면 st.session_state.history 에 기록을 남긴다 (베팅 기록 페이지에서 본다).
"""
from datetime import datetime
from fractions import Fraction

import streamlit as st

import ui
from bj.game import BJError, BJTable, Phase
from bj.rules import BJRules
from wallet import InsufficientChips

BJ_KEY = "bj_ui"

_BJ_COMPONENT = st.components.v2.component(
    "blackjack_table",
    html=ui.frontend("blackjack.html"),
    css=ui.frontend("table.css", "blackjack.css"),  # 펠트·카드·칩·무대는 바카라와 같은 스타일
    js=ui.frontend("common.js", "blackjack.js"),
)

ss = st.session_state
bj: BJTable = ss.bj


def _error(msg: str) -> None:
    ss.bj_error_seq += 1
    ss.bj_error = {"id": ss.bj_error_seq, "msg": msg}


def _finish_step(kind: str, seat: int | None, returned_before: int, shoe_before: int) -> None:
    ss.bj_step_seq += 1
    ss.bj_step = {
        "id": ss.bj_step_seq,
        "kind": kind,
        "seat": seat,
        "credited": bj.round_returned - returned_before,  # 화면은 연출이 끝난 뒤에 보유 칩에 반영한다
        "shuffled": bj.shoe_no != shoe_before,
    }
    if bj.phase is Phase.DONE:
        ss.history.append({
            **bj.round_record(),
            "no": len(ss.history) + 1,
            "time": datetime.now().strftime("%H:%M:%S"),
            "shoe": bj.shoe_no,
        })


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_deal() -> None:
    payload = ss[BJ_KEY].deal
    if not payload:
        return
    shoe_before = bj.shoe_no
    try:
        bets = {int(k): {kk: int(vv) for kk, vv in v.items()} for k, v in payload.get("bets", {}).items()}
        bj.start_round(bets)
    except (BJError, InsufficientChips, ValueError, TypeError) as e:
        _error(str(e) if isinstance(e, (BJError, InsufficientChips)) else "잘못된 베팅 정보입니다.")
        return
    _finish_step("deal", None, 0, shoe_before)


def on_action() -> None:
    payload = ss[BJ_KEY].action
    if not payload:
        return
    cur = bj.current()
    seat = cur[0].index if cur else None
    before = bj.round_returned
    try:
        bj.act(str(payload.get("action")))
    except (BJError, InsufficientChips) as e:
        _error(str(e))
        return
    _finish_step("action", seat, before, bj.shoe_no)


def on_insurance() -> None:
    payload = ss[BJ_KEY].insurance
    if not payload:
        return
    before = bj.round_returned
    try:
        bj.insure({int(k): bool(v) for k, v in payload.get("decisions", {}).items()})
    except (BJError, InsufficientChips) as e:
        _error(str(e))
        return
    _finish_step("insurance", None, before, bj.shoe_no)


# ── 사이드바 ─────────────────────────────────────────────────────────
in_round = bj.phase in (Phase.INSURANCE, Phase.PLAYER)
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("테이블 규칙")
    if in_round:
        st.caption("판이 끝난 뒤에 규칙을 바꿀 수 있습니다.")
    h17 = st.segmented_control("딜러 소프트 17", ["S17", "H17"], default="S17", key="bj_h17", disabled=in_round,
                               help="S17: 딜러가 소프트 17에서 멈춤 / H17: 한 장 더 받음 (하우스 엣지 약 +0.2%)")
    payout = st.segmented_control("블랙잭 배당", ["3:2", "6:5"], default="3:2", key="bj_payout", disabled=in_round,
                                  help="6:5 는 하우스 엣지를 약 1.4% 올립니다.")
    surrender = st.toggle("늦은 서렌더", value=True, key="bj_surrender", disabled=in_round,
                          help="첫 두 장에서 베팅의 절반을 돌려받고 포기")
    if not in_round:
        bj.rules = BJRules(h17=h17 == "H17",
                           blackjack_payout=Fraction(6, 5) if payout == "6:5" else Fraction(3, 2),
                           surrender=surrender)

    st.subheader("연출 · 도우미")
    dealer_code = ui.dealer_picker()
    show_hint = st.toggle("기본 전략 힌트", key="bj_hint", help="지금 손에서 수학적으로 가장 좋은 선택을 표시합니다.")
    show_count = st.toggle("카드 카운팅 (하이로)", key="bj_count",
                           help="공개된 카드로 센 러닝 카운트와, 남은 덱 수로 나눈 트루 카운트")

    st.subheader("슈")
    st.caption(f"{bj.shoe_no}번째 슈 · {bj.round_no}판 진행 · 남은 카드 {bj.shoe.remaining}장 "
               f"({bj.rules.decks}덱, 75% 지점에 컷 카드)")
    if st.button("새 슈로 교체", icon=":material/style:", width="stretch", disabled=in_round):
        bj.new_shoe()

    with st.expander("배당표"):
        st.dataframe(
            [
                {"베팅": "메인 승리", "배당": "1:1"},
                {"베팅": "블랙잭", "배당": payout or "3:2"},
                {"베팅": "인슈어런스", "배당": "2:1"},
                {"베팅": "퍼펙트 페어 (같은 무늬)", "배당": "25:1"},
                {"베팅": "컬러 페어 (같은 색)", "배당": "12:1"},
                {"베팅": "믹스 페어 (다른 색)", "배당": "6:1"},
                {"베팅": "21+3 같은 무늬 트리플", "배당": "100:1"},
                {"베팅": "21+3 스트레이트 플러시", "배당": "40:1"},
                {"베팅": "21+3 트리플", "배당": "30:1"},
                {"베팅": "21+3 스트레이트", "배당": "10:1"},
                {"베팅": "21+3 플러시", "배당": "5:1"},
            ],
            hide_index=True,
        )

# ── 테이블 ───────────────────────────────────────────────────────────
r = bj.rules
data = {
    "balance": bj.wallet.balance,
    "start_chips": ss.start_chips,
    "chips": ui.CHIP_DENOMS,
    "asset_base": ui.ASSET_BASE,
    "view": bj.to_view(hint=show_hint),
    "step": ss.bj_step,
    "error": ss.bj_error,
    "dealer": dealer_code,
    "clips": ui.dealer_clips(dealer_code),
    "rules": {
        "min": r.min_bet, "max": r.max_bet, "side_max": r.side_max_bet, "h17": r.h17,
        "bj_payout": "3:2" if r.blackjack_payout == Fraction(3, 2) else "6:5",
    },
    "show_hint": show_hint,
    "show_count": show_count,
}

_BJ_COMPONENT(
    key=BJ_KEY,
    data=data,
    on_deal_change=on_deal,
    on_action_change=on_action,
    on_insurance_change=on_insurance,
)
