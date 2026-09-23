# -*- coding: utf-8 -*-
"""사다리 게임 페이지 (베팅형, 버튼으로 바로 추첨).

- 추첨·정산은 ladder/game.py 의 LadderTable 이 한다. JS → 파이썬: setTriggerValue("play")
- 정산한 회차는 st.session_state.history 에 기록한다 (베팅 기록 페이지에서 본다).
- 화면에는 사다리에서의 내 누적 손익과 최근 내 회차 기록도 함께 보낸다.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import ui
from ladder.game import LadderError, LadderTable, draw, seed_hash
from ledger import LABELS
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


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_play() -> None:
    payload = getattr(ss[LADDER_KEY], "play", None)
    if not payload:
        return
    try:
        rec = game.play({str(k): int(v) for k, v in payload.get("bets", {}).items()})
    except (LadderError, InsufficientChips, ValueError, TypeError, AttributeError) as e:
        _error(str(e) if isinstance(e, (LadderError, InsufficientChips)) else "잘못된 베팅 정보입니다.")
        return
    ss.history.append({**rec, "no": len(ss.history) + 1,
                       "time": datetime.now().strftime("%H:%M:%S"), "shoe": "사다리"})
    ss.ladder_last = {"round": rec["round_no"], "net": rec["net"],
                      "stake": rec["total_stake"], "returned": rec["total_returned"]}


def _my_ladder() -> dict:
    """사다리에서의 내 누적 손익과 최근 10회차 기록."""
    mine = [h for h in ss.history if h.get("game") == "ladder"]
    stake = sum(h["total_stake"] for h in mine)
    returned = sum(h["total_returned"] for h in mine)
    return {
        "rounds": len(mine),
        "wins": sum(1 for h in mine if h["net"] > 0),
        "stake": stake,
        "returned": returned,
        "net": returned - stake,
        "list": [
            {"round": h["round_no"], "result": h["result"], "code": h["code"],
             "bets": " · ".join(f"{LABELS[k].removeprefix('사다리 ')} {v:,}" for k, v in h["bets"].items()),
             "stake": h["total_stake"], "returned": h["total_returned"], "net": h["net"]}
            for h in reversed(mine[-10:])
        ],
    }


# ── 사이드바 ─────────────────────────────────────────────────────────
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("환수율 · 배당")
    rtp = st.slider("환수율", min_value=80, max_value=99, value=int(round(game.rtp * 100)), step=1, format="%d%%",
                    key="ladder_rtp", help="배당 = 환수율 ÷ 맞힐 확률. 낮을수록 카지노에 유리합니다.")
    game.rtp = rtp / 100
    pay = game.payouts()
    st.caption(f"단일(좌·우·3줄·4줄·홀·짝) {pay['left']:.2f}배 · 조합(좌3짝 등) {pay['L3E']:.2f}배")

    st.subheader("공정성 검증")
    st.caption("추첨 전에 서버 시드의 해시를 보여 주고, 추첨 후 시드를 공개합니다. "
               "결과 = HMAC-SHA256(서버 시드, \"사용자 시드:회차 번호\") 의 첫 바이트 "
               "(비트0: 좌/우, 비트1: 3줄/4줄).")
    with st.form("ladder_seed_form", border=False):
        seed = st.text_input("사용자 시드", value=game.client_seed)
        if st.form_submit_button("시드 적용", width="stretch"):
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
    "my": _my_ladder(),
    "rules": {"min": game.min_bet, "max": game.max_bet},
}

_LADDER_COMPONENT(key=LADDER_KEY, data=data, on_play_change=on_play)

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
                         "서버 시드": r["seed"], "추첨 전 해시": r["commit"], "사용자 시드": r["client_seed"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("서버 시드의 SHA-256 이 추첨 전 해시와 같고, 같은 공식으로 같은 결과가 나오면 조작이 없었다는 뜻입니다.")
