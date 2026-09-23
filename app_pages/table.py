# -*- coding: utf-8 -*-
"""바카라 테이블 페이지.

- 승패·정산·출목표는 전부 파이썬(engine/)이 계산한다.
- 테이블 화면은 Custom Component v2(frontend/)가 그린다: 칩 베팅, 카드 분배, 스퀴즈, 출목표 표시.
  JS → 파이썬: setTriggerValue("deal" | "new_shoe")  /  파이썬 → JS: data=...
- 판이 끝날 때마다 st.session_state.history 에 기록을 남긴다 (베팅 기록 페이지에서 본다).
"""
from datetime import datetime

import streamlit as st

import ui
from engine import SIDE_BETS, Bet, BetError, GameTable, TableRules
from engine.odds import house_edges, win_probabilities

TABLE_KEY = "table_ui"

_TABLE_COMPONENT = st.components.v2.component(
    "baccarat_table",
    html=ui.frontend("table.html"),
    css=ui.frontend("table.css"),
    # 공통 코드(딜러 영상, 칩, 토스트 등) 뒤에 바카라 전용 코드를 이어 붙인다
    js=ui.frontend("common.js", "table.js"),
)


@st.cache_data
def edge_table(tie_payout: int, no_commission: bool) -> dict:
    return house_edges(TableRules(tie_payout=tie_payout, no_commission=no_commission))


@st.cache_data
def probabilities() -> dict:
    return win_probabilities()


ss = st.session_state
table: GameTable = ss.table


def _set_error(msg: str) -> None:
    ss.error_seq += 1
    ss.error = {"id": ss.error_seq, "msg": msg}


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_deal() -> None:
    payload = ss[TABLE_KEY].deal
    if not payload:
        return
    try:
        bets = {Bet(k): int(v) for k, v in payload.get("bets", {}).items()}
    except ValueError:
        _set_error("잘못된 베팅 정보입니다.")
        return
    roads_prev = table.roads().to_dict()
    try:
        outcome = table.play_round(bets)
    except (BetError, RuntimeError) as e:
        _set_error(str(e))
        return
    ss.outcome_seq += 1
    record = outcome.to_dict()
    ss.outcome = {**record, "id": ss.outcome_seq}
    ss.fresh = {"roads_prev": roads_prev}
    ss.history.append({
        **record,
        "no": len(ss.history) + 1,
        "time": datetime.now().strftime("%H:%M:%S"),
        "shoe": table.shoe_no,
        "game": "baccarat",
    })


def on_new_shoe() -> None:
    if ss[TABLE_KEY].new_shoe:
        table.new_shoe()
        ss.outcome = None


# ── 사이드바: 칩 / 테이블 설정 ────────────────────────────────────────
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("테이블 규칙")
    tie = st.segmented_control("타이 배당", ["8:1", "9:1"], default="8:1", key="tie_opt")
    no_comm = st.toggle("노 커미션 (Super 6)", key="no_comm",
                        help="뱅커 승리 시 1:1 지급, 단 뱅커가 6점으로 이기면 0.5:1")
    tie_payout = 9 if tie == "9:1" else 8
    table.rules = TableRules(tie_payout=tie_payout, no_commission=no_comm)

    st.subheader("연출")
    dealer_code = ui.dealer_picker()
    reveal = st.segmented_control(
        "카드 공개", ["딜러가 공개", "직접 스퀴즈"], default="딜러가 공개", key="reveal_opt",
        help="딜러가 공개: 딜러가 카드를 뒤집고 결정적인 카드는 천천히 젖힙니다. 직접 스퀴즈: 카드를 드래그해서 직접 젖힙니다.",
    )
    timer = st.select_slider("베팅 타이머", options=[0, 10, 15, 20, 30], value=0, key="timer",
                             format_func=lambda s: "끄기" if s == 0 else f"{s}초")

    st.subheader("슈")
    stats = table.stats()
    st.caption(f"{stats['shoe_no']}번째 슈 · {stats['rounds']}판 진행 · 남은 카드 {stats['cards_remaining']}장")
    if st.button("새 슈로 교체", icon=":material/style:", width="stretch"):
        table.new_shoe()
        ss.outcome = None

    with st.expander("확률과 하우스 에지"):
        p = probabilities()
        e = edge_table(tie_payout, no_comm)
        st.dataframe(
            [
                {"베팅": "뱅커", "승리 확률": f"{p['B']:.2%}", "하우스 에지": f"{e['banker']:.2%}"},
                {"베팅": "플레이어", "승리 확률": f"{p['P']:.2%}", "하우스 에지": f"{e['player']:.2%}"},
                {"베팅": f"타이 ({tie_payout}:1)", "승리 확률": f"{p['T']:.2%}", "하우스 에지": f"{e['tie']:.2%}"},
                {"베팅": "페어 (11:1)", "승리 확률": "7.47%", "하우스 에지": f"{e['pair']:.2%}"},
                {"베팅": "타이거 (12/20:1)", "승리 확률": "-", "하우스 에지": f"{e['tiger']:.2%}"},
            ],
            hide_index=True,
        )
        st.caption("8덱 슈 전체 조합을 정확히 계산한 값입니다. 가상 칩 전용 게임입니다.")

# ── 테이블 ───────────────────────────────────────────────────────────
fresh, ss.fresh = ss.fresh, None
rules = table.rules
data = {
    "balance": table.wallet.balance,
    "start_chips": ss.start_chips,
    "chips": ui.CHIP_DENOMS,
    "asset_base": ui.ASSET_BASE,
    "rules": {
        "tie": rules.tie_payout,
        "no_commission": rules.no_commission,
        "pair": rules.pair_payout,
        "tiger2": rules.tiger_two_card,
        "tiger3": rules.tiger_three_card,
        "min": rules.min_bet,
        "max": rules.max_bet,
        "side_max": rules.side_max_bet,
        "side_bets": [b.value for b in SIDE_BETS],
    },
    "phase": table.phase.value,
    "roads": table.roads().to_dict(),
    "stats": table.stats(),
    "outcome": ss.outcome,
    "fresh": fresh is not None,
    "roads_prev": fresh["roads_prev"] if fresh else None,
    "error": ss.error,
    "dealer": dealer_code,
    "clips": ui.dealer_clips(dealer_code),
    "squeeze": reveal == "직접 스퀴즈",
    "timer": timer,
}

_TABLE_COMPONENT(
    key=TABLE_KEY,
    data=data,
    on_deal_change=on_deal,
    on_new_shoe_change=on_new_shoe,
)
