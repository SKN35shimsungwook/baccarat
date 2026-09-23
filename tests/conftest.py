import sys
from pathlib import Path

# streamlit run main.py 과 같은 import 경로(baccarat/ 기준)로 테스트한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
