# -*- coding: utf-8 -*-
"""주사위 홀짝 (식보) 페이지: 주사위 3개, 버튼으로 바로 굴림.

- 굴리기·정산은 dice/game.py 의 DiceTable 이 한다. JS → 파이썬: setTriggerValue("roll")
- 정산한 판은 st.session_state.history 에 기록한다 (베팅 기록 페이지에서 본다).
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import ui
from dice.game import BETS, DiceError, DiceTable, probability, roll_dice, seed_hash
from wallet import InsufficientChips

DICE_KEY = "dice_ui"

_DICE_COMPONENT = st.components.v2.component(
    "dice_game",
    html=ui.frontend("dice.html"),
    css=ui.frontend("table.css", "dice.css"),  # 칩·토스트·키 표시·아래 고정 바는 공통 스타일
    js=ui.frontend("common.js", "dice.js"),
)

ss = st.session_state
game: DiceTable = ss.dice


def _error(msg: str) -> None:
    ss.dice_error_seq += 1
    ss.dice_error = {"id": ss.dice_error_seq, "msg": msg}


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_roll() -> None:
    payload = getattr(ss[DICE_KEY], "roll", None)
    if not payload:
        return
    try:
        rec = game.roll({str(k): int(v) for k, v in payload.get("bets", {}).items()})
    except (DiceError, InsufficientChips, ValueError, TypeError, AttributeError) as e:
        _error(str(e) if isinstance(e, (DiceError, InsufficientChips)) else "잘못된 베팅 정보입니다.")
        return
    ss.history.append({**rec, "no": len(ss.history) + 1,
                       "time": datetime.now().strftime("%H:%M:%S"), "shoe": "주사위"})
    ss.dice_last = {"nonce": rec["round_no"], "net": rec["net"],
                    "stake": rec["total_stake"], "returned": rec["total_returned"]}


# ── 사이드바 ─────────────────────────────────────────────────────────
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("환수율 · 배당")
    rtp = st.slider("환수율", min_value=80, max_value=99, value=int(round(game.rtp * 100)), step=1, format="%d%%",
                    key="dice_rtp", help="배당 = 환수율 ÷ 맞힐 확률. 낮을수록 카지노에 유리합니다.")
    game.rtp = rtp / 100
    pay = game.payouts()
    with st.expander("베팅별 배당표", icon=":material/table:"):
        st.dataframe(
            pd.DataFrame([{"베팅": name, "확률": f"{float(probability(k)) * 100:.2f}%", "배당": f"{pay[k]:.2f}배"}
                          for k, (name, _) in BETS.items()]),
            hide_index=True,
        )
        st.caption("홀·짝·소(4~10)·대(11~17)는 세 주사위가 모두 같은 눈(트리플)이면 집니다. "
                   "더블은 같은 눈이 2개 이상(트리플 포함).")

    st.subheader("공정성 검증")
    st.caption("굴리기 전에 서버 시드의 해시를 보여 주고, 굴린 뒤 시드를 공개합니다. "
               "주사위 = HMAC-SHA256(서버 시드, \"사용자 시드:판 번호:0\") 의 바이트 중 252 미만 값을 "
               "앞에서부터 세 개 골라 (값 % 6) + 1.")
    with st.form("dice_seed_form", border=False):
        seed = st.text_input("사용자 시드", value=game.client_seed)
        if st.form_submit_button("시드 적용", width="stretch"):
            try:
                game.set_client_seed(seed)
            except DiceError as e:
                st.error(str(e))

# ── 게임 ─────────────────────────────────────────────────────────────
data = {
    "balance": game.wallet.balance,
    "start_chips": ss.start_chips,
    "chips": ui.CHIP_DENOMS,
    "view": game.to_view(),
    "error": ss.dice_error,
    "my_last": ss.dice_last,
    "rules": {"min": game.min_bet, "max": game.max_bet},
}

_DICE_COMPONENT(key=DICE_KEY, data=data, on_roll_change=on_roll)

# 게임 화면 아래: 지난 판 공정성 검증
with st.expander("지난 판 검증", icon=":material/verified:"):
    if not game.results:
        st.caption("아직 굴린 판이 없습니다.")
    else:
        rows = []
        for r in reversed(game.results[-30:]):
            again = list(roll_dice(r["server_seed"], r["client_seed"], r["nonce"]))
            ok = seed_hash(r["server_seed"]) == r["commit"] and again == r["dice"]
            rows.append({"판": r["nonce"], "주사위": " · ".join(map(str, r["dice"])), "합계": r["sum"],
                         "다시 계산": " · ".join(map(str, again)), "검증": "✓" if ok else "✗",
                         "서버 시드": r["server_seed"], "굴리기 전 해시": r["commit"], "사용자 시드": r["client_seed"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("서버 시드의 SHA-256 이 굴리기 전 해시와 같고, 같은 공식으로 같은 주사위가 나오면 조작이 없었다는 뜻입니다.")
