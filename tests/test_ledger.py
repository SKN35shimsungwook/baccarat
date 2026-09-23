import random

from engine import Bet, GameTable
from ledger import by_bet, rows, summarize
from wallet import SessionWallet


def play(n, bets):
    store = {}
    table = GameTable(SessionWallet(store, initial=10_000_000), rng=random.Random(7))
    history = []
    for i in range(n):
        o = table.play_round(bets).to_dict()
        history.append({**o, "no": i + 1, "time": "00:00:00", "shoe": 1})
    return table, history


def test_summary_matches_wallet():
    table, history = play(30, {Bet.BANKER: 10_000, Bet.TIE: 1_000})
    s = summarize(history)
    assert s["rounds"] == 30
    assert s["wagered"] == 30 * 11_000
    assert s["net"] == table.wallet.balance - 10_000_000
    assert s["won"] + s["lost"] + s["even"] == 30
    assert s["best"] >= s["worst"]


def test_by_bet_splits_stakes():
    _, history = play(20, {Bet.PLAYER: 5_000, Bet.PLAYER_PAIR: 1_000})
    per = {r["bet"]: r for r in by_bet(history)}
    assert set(per) == {"플레이어", "P 페어"}
    assert per["플레이어"]["stake"] == 100_000
    assert per["P 페어"]["count"] == 20
    assert sum(r["net"] for r in per.values()) == summarize(history)["net"]


def test_rows_newest_first_and_text():
    _, history = play(3, {Bet.BANKER: 1_000})
    r = rows(history)
    assert [x["판"] for x in r] == [3, 2, 1]
    assert r[0]["베팅"] == "뱅커 1,000"
    assert any(s in r[0]["플레이어 카드"] for s in "♠♥♦♣")


def test_empty_history():
    assert summarize([])["rounds"] == 0
    assert by_bet([]) == [] and rows([]) == []
