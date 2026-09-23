# -*- coding: utf-8 -*-
"""바카라 (Streamlit) 진입점.

- 페이지: 테이블(app_pages/table.py), 베팅 기록(app_pages/history.py)
- 여러 페이지가 함께 쓰는 세션 상태(테이블, 칩, 기록)는 여기서 한 번만 만든다.
- 칩은 가상 칩이다. 시작 금액은 테이블 페이지 사이드바에서 사용자가 정한다.
"""
import streamlit as st

from engine import GameTable
from wallet import SessionWallet

st.set_page_config(page_title="바카라 테이블", page_icon=":material/playing_cards:", layout="wide")

DEFAULT_START = 1_000_000

ss = st.session_state
if "table" not in ss:
    ss.start_chips = DEFAULT_START
    ss.table = GameTable(SessionWallet(ss, key="chips", initial=DEFAULT_START))
    ss.outcome = None      # 마지막 판 결과 (dict)
    ss.fresh = None        # 방금 끝난 판: 애니메이션용 {"roads_prev": ...}
    ss.error = None        # {"id": n, "msg": "..."}
    ss.error_seq = 0
    ss.outcome_seq = 0
    ss.history = []        # 판별 베팅 기록 (ledger.py 형식)

# 테이블 페이지의 설정 위젯 값은 다른 페이지에 다녀와도 유지되게 붙잡아 둔다
# (Streamlit은 화면에 없는 위젯의 값을 지우기 때문)
for key in ("tie_opt", "no_comm", "dealer_opt", "reveal_opt", "timer"):
    if key in ss:
        ss[key] = ss[key]

page = st.navigation(
    [
        st.Page("app_pages/table.py", title="테이블", icon=":material/playing_cards:", default=True),
        st.Page("app_pages/history.py", title="베팅 기록", icon=":material/receipt_long:"),
    ],
    position="top",
)
page.run()
