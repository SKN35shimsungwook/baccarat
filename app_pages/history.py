# -*- coding: utf-8 -*-
"""베팅 기록 페이지: 요약 지표, 잔액 추이, 베팅 종류별 손익, 판별 기록."""
import altair as alt
import pandas as pd
import streamlit as st

from ledger import by_bet, rows, summarize

GOLD = "#d4af5f"
GAIN = "#12a396"   # 이익 (어두운 배경 대비·색각 이상 구분 검증 통과)
LOSS = "#e0584e"   # 손실

ss = st.session_state
history: list[dict] = ss.history

st.title("베팅 기록")
st.caption("이번 세션에서 진행한 판만 기록됩니다. 페이지를 새로 고침하면 칩과 함께 초기화됩니다.")

if not history:
    st.info("아직 기록이 없습니다. 테이블에서 한 판을 진행하면 여기에 쌓입니다.", icon=":material/info:")
    st.page_link("app_pages/table.py", label="테이블로 가기", icon=":material/playing_cards:")
    st.stop()

s = summarize(history)

# ── 요약 지표 ────────────────────────────────────────────────────────
row1 = st.columns(3)
row1[0].metric("총 판수", f"{s['rounds']:,}판", border=True)
row1[1].metric("총 베팅액", f"{s['wagered']:,}", border=True)
row1[2].metric("순손익", f"{s['net']:+,}", delta=f"{s['roi']:+.2%} (베팅액 대비)", border=True)
row2 = st.columns(3)
row2[0].metric("이긴 판", f"{s['won']:,} / {s['rounds']:,}",
               help=f"진 판 {s['lost']:,} · 본전 {s['even']:,} (타이 환불 등)", border=True)
row2[1].metric("최대 수익", f"{s['best']:+,}", border=True)
row2[2].metric("최대 손실", f"{s['worst']:+,}", border=True)

# ── 차트 ─────────────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left, st.container(border=True):
    st.subheader("칩 잔액 추이", divider=False)
    bal = pd.DataFrame({"판": [h["no"] for h in history], "잔액": [h["balance_after"] for h in history],
                        "손익": [h["net"] for h in history]})
    line = (
        alt.Chart(bal)
        .mark_line(color=GOLD, strokeWidth=2, point=alt.OverlayMarkDef(color=GOLD, size=36, filled=True))
        .encode(
            x=alt.X("판:Q", axis=alt.Axis(tickMinStep=1, format="d", grid=False)),
            y=alt.Y("잔액:Q", scale=alt.Scale(zero=False), axis=alt.Axis(format=",d", gridOpacity=0.15)),
            tooltip=[alt.Tooltip("판:Q"), alt.Tooltip("잔액:Q", format=","), alt.Tooltip("손익:Q", format="+,")],
        )
    )
    start = alt.Chart(pd.DataFrame({"잔액": [ss.start_chips]})).mark_rule(
        color="#8b7d66", strokeDash=[4, 4], strokeWidth=1
    ).encode(y="잔액:Q")
    st.altair_chart(start + line, height=280)
    st.caption(f"점선: 시작 칩 {ss.start_chips:,}")

with right, st.container(border=True):
    st.subheader("베팅 종류별 손익", divider=False)
    per = pd.DataFrame(by_bet(history))
    per["구분"] = per["net"].map(lambda n: "이익" if n >= 0 else "손실")
    base = alt.Chart(per).encode(
        y=alt.Y("bet:N", sort=None, title=None, axis=alt.Axis(labelFontSize=12)),
        # 양끝에 여백을 둬서 막대 바깥에 적은 금액이 잘리지 않게 한다
        x=alt.X("net:Q", title="손익", scale=alt.Scale(padding=56), axis=alt.Axis(format="~s", gridOpacity=0.15)),
    )
    bars = base.mark_bar(cornerRadius=4, height=18).encode(
        color=alt.Color("구분:N", scale=alt.Scale(domain=["이익", "손실"], range=[GAIN, LOSS]), legend=None),
        tooltip=[
            alt.Tooltip("bet:N", title="베팅"),
            alt.Tooltip("count:Q", title="건수"),
            alt.Tooltip("hit_rate:Q", title="적중률", format=".0%"),
            alt.Tooltip("stake:Q", title="베팅액", format=","),
            alt.Tooltip("net:Q", title="손익", format="+,"),
        ],
    )
    # 색만으로 구분하지 않도록 금액을 직접 적는다
    label = dict(fontSize=12, color="#efe4cf")
    labels = (
        base.transform_filter("datum.net >= 0").mark_text(align="left", dx=6, **label)
        .encode(text=alt.Text("net:Q", format="+,"))
        + base.transform_filter("datum.net < 0").mark_text(align="right", dx=-6, **label)
        .encode(text=alt.Text("net:Q", format="+,"))
    )
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#8b7d66", strokeWidth=1).encode(x="x:Q")
    st.altair_chart(zero + bars + labels, height=280)

st.dataframe(
    per.rename(columns={"bet": "베팅", "count": "건수", "wins": "적중", "hit_rate": "적중률",
                        "stake": "베팅액", "returned": "돌려받음", "net": "손익"}).drop(columns="구분"),
    hide_index=True,
    column_config={
        "적중률": st.column_config.NumberColumn(format="percent"),
        "베팅액": st.column_config.NumberColumn(format="localized"),
        "돌려받음": st.column_config.NumberColumn(format="localized"),
        "손익": st.column_config.NumberColumn(format="localized"),
    },
)

# ── 판별 기록 ────────────────────────────────────────────────────────
st.subheader("판별 기록")
table_rows = pd.DataFrame(rows(history))
view = st.segmented_control("보기", ["전체", "이긴 판", "진 판"], default="전체",
                            key="history_filter", label_visibility="collapsed")
if view == "이긴 판":
    table_rows = table_rows[table_rows["손익"] > 0]
elif view == "진 판":
    table_rows = table_rows[table_rows["손익"] < 0]

st.dataframe(
    table_rows,
    hide_index=True,
    height=min(420, 38 + 35 * max(len(table_rows), 1)),
    column_config={
        "판": st.column_config.NumberColumn(width="small"),
        "베팅액": st.column_config.NumberColumn(format="localized"),
        "돌려받음": st.column_config.NumberColumn(format="localized"),
        "손익": st.column_config.NumberColumn(format="localized"),
        "잔액": st.column_config.NumberColumn(format="localized"),
    },
)

st.download_button(
    "CSV로 내려받기",
    data=pd.DataFrame(rows(history)).to_csv(index=False).encode("utf-8-sig"),  # 엑셀에서 한글이 깨지지 않게
    file_name="baccarat_history.csv",
    mime="text/csv",
    icon=":material/download:",
)
