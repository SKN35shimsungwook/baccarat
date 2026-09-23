# -*- coding: utf-8 -*-
"""카지노 테이블 (Streamlit) 진입점.

- 페이지: 바카라, 블랙잭, 블랙잭 전략·시뮬레이션, 비행기(크래시), 사다리, 주사위, 베팅 기록
- 여러 페이지가 함께 쓰는 세션 상태(두 게임 테이블, 칩, 기록)는 여기서 한 번만 만든다.
  모든 게임은 같은 지갑(session_state["chips"])을 쓴다.
- 칩은 가상 칩이다. 시작 금액은 게임 페이지 사이드바에서 사용자가 정한다.
"""
import streamlit as st

from bj.game import BJTable
from crash.game import CrashTable
from dice.game import DiceTable
from engine import GameTable
from ladder.game import LadderTable
from wallet import SessionWallet

st.set_page_config(page_title="카지노 테이블", page_icon=":material/playing_cards:", layout="wide")

DEFAULT_START = 1_000_000

ss = st.session_state
if "table" not in ss:
    ss.start_chips = DEFAULT_START
    ss.table = GameTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.outcome = None      # 바카라: 마지막 판 결과 (dict)
    ss.fresh = None        # 바카라: 방금 끝난 판 (애니메이션용)
    ss.error = None        # 바카라: {"id": n, "msg": "..."}
    ss.error_seq = 0
    ss.outcome_seq = 0
    ss.history = []        # 두 게임의 판별 베팅 기록 (ledger.py 형식)
if "bj" not in ss:
    ss.bj = BJTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.bj_step = None      # 블랙잭: 마지막 진행 단계 {"id", "kind", "seat", "credited", "shuffled"}
    ss.bj_step_seq = 0
    ss.bj_error = None
    ss.bj_error_seq = 0
if "crash" not in ss:
    ss.crash = CrashTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.crash_error = None
    ss.crash_error_seq = 0
if "ladder" not in ss:
    ss.ladder = LadderTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.ladder_error = None
    ss.ladder_error_seq = 0
    ss.ladder_last = None  # 마지막으로 정산한 내 회차 {"round", "net", "stake", "returned"}
if "dice" not in ss:
    ss.dice = DiceTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.dice_error = None
    ss.dice_error_seq = 0
    ss.dice_last = None    # 마지막 판 내 결과 {"nonce", "net", "stake", "returned"}

# 게임 페이지의 설정 위젯 값은 다른 페이지에 다녀와도 유지되게 붙잡아 둔다
# (Streamlit은 화면에 없는 위젯의 값을 지우기 때문)
for key in ("tie_opt", "no_comm", "dealer_opt", "reveal_opt", "timer",
            "bj_h17", "bj_payout", "bj_surrender", "bj_hint", "bj_count", "crash_rtp",
            "ladder_rtp", "dice_rtp"):
    if key in ss:
        ss[key] = ss[key]

page = st.navigation(
    [
        st.Page("app_pages/table.py", title="바카라", icon=":material/playing_cards:", default=True),
        st.Page("app_pages/blackjack.py", title="블랙잭", icon=":material/style:"),
        st.Page("app_pages/bj_lab.py", title="블랙잭 전략", icon=":material/science:"),
        st.Page("app_pages/crash.py", title="비행기", icon=":material/flight_takeoff:"),
        st.Page("app_pages/ladder.py", title="사다리", icon=":material/stairs:"),
        st.Page("app_pages/dice.py", title="주사위", icon=":material/casino:"),
        st.Page("app_pages/history.py", title="베팅 기록", icon=":material/receipt_long:"),
    ],
    position="top",
)
page.run()
