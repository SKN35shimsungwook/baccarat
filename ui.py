"""여러 페이지가 함께 쓰는 Streamlit 조각."""
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
STATIC = ROOT / "static"
CHIP_DENOMS = [1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000]
ASSET_BASE = "app/static/"  # .streamlit/config.toml 의 enableStaticServing


def frontend(*names: str) -> str:
    """frontend/ 파일들을 순서대로 이어 붙인다 (공통 코드 + 게임별 코드)."""
    return "\n".join((FRONTEND / n).read_text(encoding="utf-8") for n in names)


@st.cache_data
def dealer_clips(who: str) -> dict:
    """딜러 동작 클립의 구간·카드 추적 정보 (tools/build_dealer_clips.py 가 만든다)."""
    return json.loads((STATIC / f"dealer_{who}_clips.json").read_text(encoding="utf-8"))


def chips_sidebar() -> None:
    """시작 칩 설정. 칩 잔액은 두 게임이 함께 쓴다."""
    ss = st.session_state
    st.subheader("칩")
    with st.form("chips_form", border=False):
        start = st.number_input("시작 칩", min_value=10_000, max_value=1_000_000_000,
                                value=ss.start_chips, step=100_000, format="%d")
        if st.form_submit_button("이 금액으로 시작", icon=":material/restart_alt:", width="stretch"):
            ss.start_chips = int(start)
            ss.table.wallet.reset(int(start))  # 두 게임이 같은 지갑(session_state["chips"])을 쓴다
    st.caption("보유 칩과 손익은 테이블 위쪽에 표시됩니다. 바카라와 블랙잭이 같은 칩을 씁니다.")


def dealer_picker() -> str:
    dealer = st.segmented_control("딜러", ["남성 딜러", "여성 딜러"], default="남성 딜러", key="dealer_opt")
    return "f" if dealer == "여성 딜러" else "m"
