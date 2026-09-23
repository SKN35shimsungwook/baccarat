# -*- coding: utf-8 -*-
"""비행기(크래시) 게임 페이지.

- 추락 지점과 정산은 crash/game.py 의 CrashTable 이 정한다. 화면(frontend/crash.*)은 canvas로 비행을 그린다.
  JS → 파이썬: setTriggerValue("start" | "cashout1" | "finish")
- 배당 확률은 환수율에 비례한다: x배 이상 버틸 확률 = 환수율 ÷ x.
- 판이 끝나면 st.session_state.history 에 기록을 남긴다 (베팅 기록 페이지에서 본다).
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import ui
from crash.game import CrashError, CrashTable, Phase, crash_point, seed_hash, success_table
from wallet import InsufficientChips

CRASH_KEY = "crash_ui"

_CRASH_COMPONENT = st.components.v2.component(
    "crash_game",
    html=ui.frontend("crash.html"),
    css=ui.frontend("table.css", "crash.css"),  # 칩·토스트·키 표시·아래 고정 바는 공통 스타일
    js=ui.frontend("common.js", "crash.js"),
)

ss = st.session_state
game: CrashTable = ss.crash


def _error(msg: str) -> None:
    ss.crash_error_seq += 1
    ss.crash_error = {"id": ss.crash_error_seq, "msg": msg}


def _payload(key: str) -> dict | None:
    return getattr(ss[CRASH_KEY], key, None)


# ── 컴포넌트 이벤트 (스크립트 본문보다 먼저 실행됨) ─────────────────────
def on_start() -> None:
    payload = _payload("start")
    if not payload:
        return
    try:
        game.start({int(k): v for k, v in payload.get("bets", {}).items()})
    except (CrashError, InsufficientChips, ValueError, TypeError) as e:
        _error(str(e) if isinstance(e, (CrashError, InsufficientChips)) else "잘못된 베팅 정보입니다.")


def _cash_out(panel: int) -> None:
    payload = _payload(f"cashout{panel}")
    if not payload:
        return
    try:
        game.cash_out(panel, float(payload.get("m", 0)))
    except (CrashError, ValueError, TypeError) as e:
        _error(str(e) if isinstance(e, CrashError) else "잘못된 요청입니다.")


def on_cashout1() -> None:
    _cash_out(1)


def on_finish() -> None:
    if not _payload("finish") or game.phase is not Phase.FLYING:
        return
    rnd = game.finish()
    ss.history.append({
        **game.round_record(rnd),
        "no": len(ss.history) + 1,
        "time": datetime.now().strftime("%H:%M:%S"),
        "shoe": "비행",
    })


# ── 사이드바 ─────────────────────────────────────────────────────────
flying = game.phase is Phase.FLYING
with st.sidebar:
    ui.chips_sidebar()

    st.subheader("환수율 · 배당 확률")
    rtp = st.slider("환수율", min_value=50, max_value=99, value=int(round(game.rtp * 100)), step=1, format="%d%%",
                    key="crash_rtp", disabled=flying,
                    help="x배 이상 버틸 확률 = 환수율 ÷ x. 어느 배당에서 멈추든 장기 기대 환수는 이 값과 같습니다.")
    if not flying:
        game.rtp = rtp / 100
    with st.expander("목표 배당별 성공 확률", expanded=False):
        st.dataframe(
            pd.DataFrame(success_table(game.rtp)),
            hide_index=True,
            column_config={
                "성공 확률": st.column_config.NumberColumn(format="percent"),
                "기대 환수": st.column_config.NumberColumn(format="percent"),
            },
        )
        st.caption(f"약 {1 - game.rtp / 1.01:.1%}의 판은 1.00x에서 바로 추락합니다. 최대 배당은 1,000x입니다.")

    st.subheader("공정성 검증")
    st.caption("판을 시작하기 전에 서버 시드의 해시를 먼저 보여 주고, 판이 끝나면 서버 시드를 공개합니다. "
               "추락 지점 = HMAC-SHA256(서버 시드, \"사용자 시드:판 번호\") 로 계산됩니다.")
    st.code(f"다음 판 해시: {game.commit}", language=None, wrap_lines=True)
    with st.form("crash_seed_form", border=False):
        seed = st.text_input("사용자 시드", value=game.client_seed, disabled=flying,
                             help="원하는 문자열로 바꾸면, 서버가 미리 결과를 고를 수 없다는 것을 보장합니다.")
        if st.form_submit_button("시드 적용", disabled=flying, width="stretch"):
            try:
                game.set_client_seed(seed)
            except CrashError as e:
                st.error(str(e))

# ── 게임 ─────────────────────────────────────────────────────────────
data = {
    "balance": game.wallet.balance,
    "start_chips": ss.start_chips,
    "view": game.to_view(),
    "error": ss.crash_error,
    "rules": {"min": game.min_bet, "max": game.max_bet},
}

_CRASH_COMPONENT(
    key=CRASH_KEY,
    data=data,
    on_start_change=on_start,
    on_cashout1_change=on_cashout1,
    on_finish_change=on_finish,
)

# 게임 화면 아래: 지난 판 공정성 검증 (위에 두면 게임이 아래로 밀린다)
with st.expander("지난 판 검증", icon=":material/verified:"):
    if not game.history:
        st.caption("아직 끝난 판이 없습니다.")
    else:
        rows = []
        for rnd in reversed(game.history[-30:]):
            recomputed = crash_point(rnd["server_seed"], rnd["client_seed"], rnd["nonce"], rnd["rtp"])
            ok = seed_hash(rnd["server_seed"]) == rnd["commit"] and recomputed == rnd["crash"]
            rows.append({"판": rnd["nonce"], "추락": rnd["crash"], "다시 계산": recomputed, "검증": "✓" if ok else "✗",
                         "서버 시드": rnd["server_seed"], "시작 전 해시": rnd["commit"], "사용자 시드": rnd["client_seed"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={"추락": st.column_config.NumberColumn(format="%.2fx"),
                                    "다시 계산": st.column_config.NumberColumn(format="%.2fx")})
        st.caption("누구나 서버 시드의 SHA-256 이 시작 전 해시와 같은지, 같은 공식으로 추락 지점이 나오는지 확인할 수 있습니다.")
