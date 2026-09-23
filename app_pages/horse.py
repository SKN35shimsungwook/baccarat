# -*- coding: utf-8 -*-
"""경마 페이지 (단승식, 6마리, 버튼으로 바로 출발).

- 출전표·경주·정산은 horse/game.py 의 HorseTable 이 한다. JS → 파이썬: setTriggerValue("play")
- 정산한 경주는 st.session_state.history 에 기록한다 (베팅 기록 페이지에서 본다).
- 화면에는 경마에서의 내 누적 손익과 최근 내 경주 기록도 함께 보낸다.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import ui
from horse.game import HorseError, HorseTable, race_order, seed_hash
from wallet import InsufficientChips

HORSE_KEY = "horse_ui"

_HORSE_COMPONENT = st.components.v2.component(
    "horse_game",
    html=ui.frontend("horse.html"),
    css=ui.frontend("table.css", "horse.css"),  # 칩·토스트·키 표시·아래 고정 바는 공통 스타일
    js=ui.frontend("common.js", "horse.js"),
)

ss = st.session_state
game: HorseTable = ss.horse


def _error(msg: str) -> None:
    ss.horse_error_seq += 1
    ss.horse_error = {"id": ss.horse_error_seq, "msg": msg}


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_play() -> None:
    payload = getattr(ss[HORSE_KEY], "play", None)
    if not payload:
        return
    try:
        rec = game.play({str(k): int(v) for k, v in payload.get("bets", {}).items()})
    except (HorseError, InsufficientChips, ValueError, TypeError, AttributeError) as e:
        _error(str(e) if isinstance(e, (HorseError, InsufficientChips)) else "잘못된 베팅 정보입니다.")
        return
    ss.history.append({**rec, "no": len(ss.history) + 1,
                       "time": datetime.now().strftime("%H:%M:%S"), "shoe": "경마"})
    ss.horse_last = {"race_no": rec["round_no"], "net": rec["net"],
                     "stake": rec["total_stake"], "returned": rec["total_returned"], "lanes": rec["lanes"]}


def _my_horse() -> dict:
    """경마에서의 내 누적 손익과 최근 10경주 기록."""
    mine = [h for h in ss.history if h.get("game") == "horse"]
    stake = sum(h["total_stake"] for h in mine)
    returned = sum(h["total_returned"] for h in mine)
    return {
        "rounds": len(mine),
        "wins": sum(1 for h in mine if h["total_returned"] > 0),
        "stake": stake,
        "returned": returned,
        "net": returned - stake,
        "list": [
            {"race_no": h["round_no"], "result": h["result"], "winner": h["order"][0],
             "bets": " · ".join(s["detail"].rsplit(" ", 1)[0] + f" {s['stake']:,}" for s in h["settlements"]),
             "stake": h["total_stake"], "returned": h["total_returned"], "net": h["net"]}
            for h in reversed(mine[-10:])
        ],
    }


# ── 사이드바 ─────────────────────────────────────────────────────────
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("환수율 · 배당")
    rtp = st.slider("환수율", min_value=80, max_value=99, value=int(round(game.rtp * 100)), step=1, format="%d%%",
                    key="horse_rtp", help="배당 = 환수율 ÷ 1등 확률. 낮을수록 카지노에 유리합니다.")
    game.rtp = rtp / 100
    st.caption("등급별 배당 (환수율 95% 기준): 강자 2~4배 · 중간 5~16배 · 복병 18~90배. "
               "어느 말에 걸어도 기대 환수율은 같습니다.")

    st.subheader("공정성 검증")
    st.caption("출전표와 함께 서버 시드의 해시를 먼저 보여 주고, 경주 후 시드를 공개합니다. "
               "순위 = HMAC-SHA256(서버 시드, \"사용자 시드:경주 번호:i\") 로 i번째 자리를 "
               "남은 말 중 1등 확률에 비례해 뽑습니다.")
    with st.form("horse_seed_form", border=False):
        seed = st.text_input("사용자 시드", value=game.client_seed)
        if st.form_submit_button("시드 적용", width="stretch"):
            try:
                game.set_client_seed(seed)
            except HorseError as e:
                st.error(str(e))

# ── 게임 ─────────────────────────────────────────────────────────────
data = {
    "balance": game.wallet.balance,
    "start_chips": ss.start_chips,
    "chips": ui.CHIP_DENOMS,
    "view": game.to_view(),
    "error": ss.horse_error,
    "my_last": ss.horse_last,
    "my": _my_horse(),
    "rules": {"min": game.min_bet, "max": game.max_bet},
}

_HORSE_COMPONENT(key=HORSE_KEY, data=data, on_play_change=on_play)

# 게임 화면 아래: 지난 경주 공정성 검증
with st.expander("지난 경주 검증", icon=":material/verified:"):
    if not game.results:
        st.caption("아직 달린 경주가 없습니다.")
    else:
        rows = []
        for r in reversed(game.results[-30:]):
            again = race_order(r["seed"], r["client_seed"], r["race_no"], [e["prob"] for e in r["lineup"]])
            ok = seed_hash(r["seed"]) == r["commit"] and again == r["order"]
            rows.append({"경주": r["race_no"], "1위": r["text"], "순위": "-".join(map(str, r["order"])),
                         "다시 계산": "-".join(map(str, again)), "검증": "✓" if ok else "✗",
                         "서버 시드": r["seed"], "경주 전 해시": r["commit"], "사용자 시드": r["client_seed"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("서버 시드의 SHA-256 이 경주 전 해시와 같고, 같은 공식으로 같은 순위가 나오면 조작이 없었다는 뜻입니다.")
