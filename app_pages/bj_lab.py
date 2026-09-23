# -*- coding: utf-8 -*-
"""블랙잭 전략·시뮬레이션 페이지.

- 규칙에 맞는 기본 전략표 (bj.strategy.chart)
- 기본 전략 자동 플레이로 하우스 엣지를 추정하는 몬테카를로 시뮬레이션 (bj.sim.simulate)
"""
import time
from fractions import Fraction

import pandas as pd
import streamlit as st

from bj.rules import BJRules
from bj.sim import simulate
from bj.strategy import UP, chart

CODE_TEXT = {"H": "히트", "S": "스탠드", "D": "더블", "Ds": "더블/스탠드", "P": "스플릿",
             "R": "서렌더/히트", "Rs": "서렌더/스탠드", "Rp": "서렌더/스플릿"}
# 칸 배경색 (글자로도 코드를 적어서 색만으로 구분하지 않는다)
CODE_BG = {"H": "#7a2a22", "S": "#2d6a4f", "D": "#2c5aa8", "Ds": "#2c5aa8", "P": "#6b4c9a",
           "R": "#5b5348", "Rs": "#5b5348", "Rp": "#5b5348"}
# 알려진 하우스 엣지 (6덱, 딜러 피크, 스플릿 후 더블) — Wizard of Odds 등 공개 계산값 기준 근사
REFERENCE = [
    {"규칙": "S17 · 3:2 · 서렌더", "알려진 값": "약 0.36%"},
    {"규칙": "H17 · 3:2 · 서렌더", "알려진 값": "약 0.56%"},
    {"규칙": "S17 · 6:5 · 서렌더", "알려진 값": "약 1.7%"},
]

ss = st.session_state
ss.setdefault("sim_runs", [])

st.title("블랙잭 전략 · 시뮬레이션")
st.caption("6덱 · 딜러 피크(업카드 A/10이면 블랙잭 확인) · 스플릿 후 더블 기준입니다.")

with st.container(horizontal=True):
    h17 = st.segmented_control("딜러 소프트 17", ["S17", "H17"], default="S17", key="lab_h17")
    payout = st.segmented_control("블랙잭 배당", ["3:2", "6:5"], default="3:2", key="lab_payout")
    surrender = st.toggle("늦은 서렌더", value=True, key="lab_surrender")
rules = BJRules(h17=h17 == "H17", blackjack_payout=Fraction(6, 5) if payout == "6:5" else Fraction(3, 2),
                surrender=surrender)

# ── 기본 전략표 ──────────────────────────────────────────────────────
st.subheader("기본 전략표")
st.caption("가로: 딜러 업카드 · 세로: 내 손. "
           + " · ".join(f"{k} {v}" for k, v in CODE_TEXT.items() if surrender or not k.startswith("R")))


def styled(labels, rows):
    df = pd.DataFrame(rows, index=labels, columns=list(UP))
    return df.style.map(lambda c: f"background-color: {CODE_BG[c]}; color: #fff; text-align: center;")


tables = chart(rules)
tab_hard, tab_soft, tab_pair = st.tabs(["하드", "소프트 (에이스 포함)", "페어"])
with tab_hard:
    st.dataframe(styled(*tables["hard"]))
with tab_soft:
    st.dataframe(styled(*tables["soft"]))
with tab_pair:
    st.dataframe(styled(*tables["pairs"]))

# ── 시뮬레이션 ───────────────────────────────────────────────────────
st.subheader("하우스 엣지 시뮬레이션")
st.caption("위 규칙으로 한 자리에 같은 금액을 걸고 기본 전략대로 자동 플레이합니다. "
           "인슈어런스·사이드 베팅은 하지 않습니다. 판 수가 많을수록 오차 범위가 줄어듭니다.")


@st.cache_data(max_entries=30, show_spinner=False)
def run_sim(h17: bool, payout: str, surrender: bool, rounds: int, seed: int) -> dict:
    r = BJRules(h17=h17, blackjack_payout=Fraction(6, 5) if payout == "6:5" else Fraction(3, 2),
                surrender=surrender)
    start = time.perf_counter()
    out = simulate(r, rounds, seed=seed)
    out["seconds"] = time.perf_counter() - start
    return out


with st.container(horizontal=True, vertical_alignment="bottom"):
    rounds = st.select_slider("판 수", options=[20_000, 50_000, 100_000, 200_000, 400_000], value=100_000,
                              format_func=lambda n: f"{n:,}판", key="lab_rounds")
    seed = st.number_input("시드", min_value=0, max_value=9999, value=7, step=1, key="lab_seed",
                           help="같은 시드면 같은 카드 순서로 돌려서 규칙끼리 비교하기 좋습니다.")
    run = st.button("시뮬레이션 실행", type="primary", icon=":material/play_arrow:")

if run:
    with st.spinner(f"{rounds:,}판 자동 플레이 중… (초당 약 1만 5천 판)"):
        res = run_sim(rules.h17, payout, surrender, rounds, int(seed))
    ss.sim_runs.insert(0, {
        "규칙": f"{h17} · {payout} · {'서렌더' if surrender else '서렌더 없음'}",
        "판 수": rounds,
        "시드": int(seed),
        "하우스 엣지": res["edge"],
        "±95%": res["ci95"],
        "승": res["win"], "무": res["push"], "패": res["lose"],
        "블랙잭": res["blackjack"],
        "초": res["seconds"],
    })

if ss.sim_runs:
    last = ss.sim_runs[0]
    cols = st.columns(4)
    cols[0].metric("하우스 엣지", f"{last['하우스 엣지']:.2%}", border=True,
                   help=f"95% 신뢰구간 ±{last['±95%']:.2%}")
    cols[1].metric("이긴 판", f"{last['승']:.1%}", border=True)
    cols[2].metric("비긴 판", f"{last['무']:.1%}", border=True)
    cols[3].metric("블랙잭 빈도", f"{last['블랙잭']:.2%}", border=True)
    st.caption(f"{last['규칙']} · {last['판 수']:,}판 · 시드 {last['시드']} · {last['초']:.1f}초 · "
               f"오차 범위 ±{last['±95%']:.2%} (95%)")
    st.dataframe(
        pd.DataFrame(ss.sim_runs),
        hide_index=True,
        column_config={
            "판 수": st.column_config.NumberColumn(format="localized"),
            "하우스 엣지": st.column_config.NumberColumn(format="percent"),
            "±95%": st.column_config.NumberColumn(format="percent"),
            "승": st.column_config.NumberColumn(format="percent"),
            "무": st.column_config.NumberColumn(format="percent"),
            "패": st.column_config.NumberColumn(format="percent"),
            "블랙잭": st.column_config.NumberColumn(format="percent"),
            "초": st.column_config.NumberColumn(format="%.1f"),
        },
    )
else:
    st.info("규칙을 고르고 '시뮬레이션 실행'을 누르세요.", icon=":material/science:")

with st.expander("참고: 알려진 하우스 엣지"):
    st.dataframe(pd.DataFrame(REFERENCE), hide_index=True)
    st.caption("공개된 계산값의 근사치입니다. 시뮬레이션 결과가 오차 범위 안에서 이 값과 맞으면 엔진과 전략이 제대로 동작하는 것입니다.")
