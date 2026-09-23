# -*- coding: utf-8 -*-
"""바카라 테이블 (Streamlit).

- 승패·정산·출목표는 전부 파이썬(engine/)이 계산한다.
- 테이블 화면은 Custom Component v2(frontend/)가 그린다: 칩 베팅, 카드 분배, 스퀴즈, 출목표 표시.
  JS → 파이썬: setTriggerValue("deal" | "new_shoe")  /  파이썬 → JS: data=...
- 칩은 가상 칩이다. 시작 금액은 사이드바에서 사용자가 정한다.
"""
import json
from pathlib import Path

import streamlit as st

from engine import SIDE_BETS, Bet, BetError, GameTable, TableRules
from engine.odds import house_edges, win_probabilities
from wallet import SessionWallet

st.set_page_config(page_title="바카라 테이블", page_icon=":material/playing_cards:", layout="wide")

FRONTEND = Path(__file__).parent / "frontend"
STATIC = Path(__file__).parent / "static"
TABLE_KEY = "table_ui"
CHIP_DENOMS = [1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000]
DEFAULT_START = 1_000_000

_TABLE_COMPONENT = st.components.v2.component(
    "baccarat_table",
    html=(FRONTEND / "table.html").read_text(encoding="utf-8"),
    css=(FRONTEND / "table.css").read_text(encoding="utf-8"),
    js=(FRONTEND / "table.js").read_text(encoding="utf-8"),
)


@st.cache_data
def edge_table(tie_payout: int, no_commission: bool) -> dict:
    return house_edges(TableRules(tie_payout=tie_payout, no_commission=no_commission))


@st.cache_data
def dealer_clips(who: str) -> dict:
    """딜러 동작 클립의 구간·카드 추적 정보 (tools/build_dealer_clips.py 가 만든다)."""
    return json.loads((STATIC / f"dealer_{who}_clips.json").read_text(encoding="utf-8"))


@st.cache_data
def probabilities() -> dict:
    return win_probabilities()


# ── 세션 초기화 (한 곳에서) ──────────────────────────────────────────
ss = st.session_state
if "table" not in ss:
    ss.start_chips = DEFAULT_START
    ss.table = GameTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.outcome = None      # 마지막 판 결과 (dict)
    ss.fresh = None        # 방금 끝난 판: 애니메이션용 {"roads_prev": ...}
    ss.error = None        # {"id": n, "msg": "..."}
    ss.error_seq = 0
    ss.outcome_seq = 0
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
    ss.outcome = {**outcome.to_dict(), "id": ss.outcome_seq}
    ss.fresh = {"roads_prev": roads_prev}


def on_new_shoe() -> None:
    if ss[TABLE_KEY].new_shoe:
        table.new_shoe()
        ss.outcome = None


# ── 사이드바: 칩 / 테이블 설정 ────────────────────────────────────────
with st.sidebar:
    st.subheader("칩")
    with st.form("chips_form", border=False):
        start = st.number_input("시작 칩", min_value=10_000, max_value=1_000_000_000,
                                value=ss.start_chips, step=100_000, format="%d")
        if st.form_submit_button("이 금액으로 시작", icon=":material/restart_alt:", width="stretch"):
            ss.start_chips = int(start)
            table.wallet.reset(int(start))
    st.caption("보유 칩과 손익은 테이블 위쪽에 표시됩니다. (결과 연출 전에 미리 보이지 않도록)")

    st.subheader("테이블 규칙")
    tie = st.segmented_control("타이 배당", ["8:1", "9:1"], default="8:1", key="tie_opt")
    no_comm = st.toggle("노 커미션 (Super 6)", key="no_comm",
                        help="뱅커 승리 시 1:1 지급, 단 뱅커가 6점으로 이기면 0.5:1")
    tie_payout = 9 if tie == "9:1" else 8
    table.rules = TableRules(tie_payout=tie_payout, no_commission=no_comm)

    st.subheader("연출")
    dealer = st.segmented_control("딜러", ["남성 딜러", "여성 딜러"], default="남성 딜러", key="dealer_opt")
    dealer_code = "f" if dealer == "여성 딜러" else "m"
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
    "chips": CHIP_DENOMS,
    "asset_base": "app/static/",  # .streamlit/config.toml 의 enableStaticServing
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
    "clips": dealer_clips(dealer_code),
    "squeeze": reveal == "직접 스퀴즈",
    "timer": timer,
}

_TABLE_COMPONENT(
    key=TABLE_KEY,
    data=data,
    on_deal_change=on_deal,
    on_new_shoe_change=on_new_shoe,
)
