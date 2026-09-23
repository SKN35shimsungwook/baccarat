# -*- coding: utf-8 -*-
"""사다리 게임 페이지 (베팅형, 자동 회차).

- 회차 시간표·추첨·정산은 ladder/game.py 의 LadderTable 이 서버 시계로 한다.
  JS → 파이썬: setTriggerValue("bet" | "tick")
- 페이지가 실행될 때마다 추첨 시각이 지난 회차를 정산한다 (다른 페이지에 다녀와도 밀린 회차가 정산된다).
- 정산한 회차는 st.session_state.history 에 기록한다 (베팅 기록 페이지에서 본다).
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import ui
from ladder.game import BETS, LadderError, LadderTable, draw, seed_hash
from wallet import InsufficientChips

LADDER_KEY = "ladder_ui"

_LADDER_COMPONENT = st.components.v2.component(
    "ladder_game",
    html=ui.frontend("ladder.html"),
    css=ui.frontend("table.css", "ladder.css"),  # 칩·토스트·키 표시·아래 고정 바는 공통 스타일
    js=ui.frontend("common.js", "ladder.js"),
)

ss = st.session_state
game: LadderTable = ss.ladder


def _error(msg: str) -> None:
    ss.ladder_error_seq += 1
    ss.ladder_error = {"id": ss.ladder_error_seq, "msg": msg}


def _settle_due() -> None:
    """추첨 시각이 지난 회차를 정산하고 기록에 남긴다."""
    for rec in game.resolve():
        ss.history.append({**rec, "no": len(ss.history) + 1,
                           "time": datetime.now().strftime("%H:%M:%S"), "shoe": "사다리"})
        ss.ladder_last = {"round": rec["round_no"], "net": rec["net"], "stake": rec["total_stake"]}


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_bet() -> None:
    payload = getattr(ss[LADDER_KEY], "bet", None)
    if not payload:
        return
    _settle_due()
    try:
        game.place({str(k): int(v) for k, v in payload.get("bets", {}).items()})
    except (LadderError, InsufficientChips, ValueError, TypeError) as e:
        _error(str(e) if isinstance(e, (LadderError, InsufficientChips)) else "잘못된 베팅 정보입니다.")


def on_tick() -> None:
    _settle_due()


_settle_due()  # 페이지를 열 때마다 밀린 회차 정산

# ── 사이드바 ─────────────────────────────────────────────────────────
has_pending = any(game.pending.values())
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("환수율 · 배당")
    rtp = st.slider("환수율", min_value=80, max_value=99, value=int(round(game.rtp * 100)), step=1, format="%d%%",
                    key="ladder_rtp", help="배당 = 환수율 ÷ 맞힐 확률. 이미 확정한 베팅은 확정할 때의 배당으로 정산됩니다.")
    game.rtp = rtp / 100
    pay = game.payouts()
    st.caption(f"단일(좌·우·3줄·4줄·홀·짝) {pay['left']:.2f}배 · 조합(좌3짝 등) {pay['L3E']:.2f}배")

    st.subheader("회차")
    period = st.segmented_control("간격", [30, 60], default=game.period, key="ladder_period",
                                  format_func=lambda p: f"{p}초", disabled=has_pending,
                                  help="걸어 둔 베팅이 정산된 뒤에 바꿀 수 있습니다.")
    if period and period != game.period and not has_pending:
        game.set_period(int(period))
    st.caption(f"추첨 {game.lock}초 전에 베팅이 마감됩니다. 결과는 추첨 시각이 지나야 계산되어 미리 알 수 없습니다.")

    st.subheader("공정성 검증")
    st.caption("회차 시작 전에 회차 시드의 해시를 보여 주고, 추첨 후 시드를 공개합니다. "
               "결과 = HMAC-SHA256(회차 시드, \"사용자 시드:회차 번호\") 의 첫 바이트 "
               "(비트0: 좌/우, 비트1: 3줄/4줄).")
    with st.form("ladder_seed_form", border=False):
        seed = st.text_input("사용자 시드", value=game.client_seed, disabled=has_pending)
        if st.form_submit_button("시드 적용", disabled=has_pending, width="stretch"):
            try:
                game.set_client_seed(seed)
            except LadderError as e:
                st.error(str(e))

# ── 게임 ─────────────────────────────────────────────────────────────
data = {
    "balance": game.wallet.balance,
    "start_chips": ss.start_chips,
    "chips": ui.CHIP_DENOMS,
    "view": game.to_view(),
    "error": ss.ladder_error,
    "my_last": ss.ladder_last,
    "rules": {"min": game.min_bet, "max": game.max_bet},
}

_LADDER_COMPONENT(
    key=LADDER_KEY,
    data=data,
    on_bet_change=on_bet,
    on_tick_change=on_tick,
)

# 게임 화면 아래: 지난 회차 공정성 검증
with st.expander("지난 회차 검증", icon=":material/verified:"):
    if not game.results:
        st.caption("아직 추첨한 회차가 없습니다.")
    else:
        rows = []
        for r in reversed(game.results[-30:]):
            again = draw(r["seed"], r["client_seed"], r["round"])["code"]
            ok = seed_hash(r["seed"]) == r["commit"] and again == r["code"]
            rows.append({"회차": r["round"], "결과": r["text"], "다시 계산": again, "검증": "✓" if ok else "✗",
                         "회차 시드": r["seed"], "시작 전 해시": r["commit"], "사용자 시드": r["client_seed"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("회차 시드의 SHA-256 이 시작 전 해시와 같고, 같은 공식으로 같은 결과가 나오면 조작이 없었다는 뜻입니다.")
