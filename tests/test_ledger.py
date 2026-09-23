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
    assert set(per) == {"바카라 플레이어", "바카라 P 페어"}
    assert per["바카라 플레이어"]["stake"] == 100_000
    assert per["바카라 P 페어"]["count"] == 20
    assert sum(r["net"] for r in per.values()) == summarize(history)["net"]


def test_rows_newest_first_and_text():
    _, history = play(3, {Bet.BANKER: 1_000})
    r = rows(history)
    assert [x["판"] for x in r] == [3, 2, 1]
    assert r[0]["베팅"] == "뱅커 1,000"
    assert r[0]["게임"] == "바카라"
    assert any(s in r[0]["플레이어·자리 카드"] for s in "♠♥♦♣")


def test_empty_history():
    assert summarize([])["rounds"] == 0
    assert by_bet([]) == [] and rows([]) == []


def test_blackjack_records_mix_with_baccarat():
    import random as _r

    from bj.game import BJTable, Phase

    _, history = play(3, {Bet.BANKER: 1_000})
    t = BJTable(SessionWallet({}, initial=10_000_000), rng=_r.Random(5))
    for i in range(10):
        t.start_round({0: {"main": 1_000, "pp": 1_000}, 2: {"main": 2_000}})
        if t.phase is Phase.INSURANCE:
            t.insure({})
        while t.phase is Phase.PLAYER:
            t.act("stand")
        history.append({**t.round_record(), "no": len(history) + 1, "time": "00:00:00", "shoe": t.shoe_no})
    per = {r["bet"]: r for r in by_bet(history)}
    assert {"바카라 뱅커", "블랙잭 메인", "블랙잭 퍼펙트 페어"} <= set(per)
    assert per["블랙잭 퍼펙트 페어"]["count"] == 10
    assert sum(r["net"] for r in per.values()) == summarize(history)["net"]
    top = rows(history)[0]
    assert top["게임"] == "블랙잭" and top["결과"].startswith("딜러")
    assert "1번:" in top["플레이어·자리 카드"] and "3번:" in top["플레이어·자리 카드"]


def test_crash_records():
    from crash.game import CrashTable

    t = CrashTable(SessionWallet({}, initial=1_000_000))
    history = []
    for i in range(5):
        t.start({1: {"stake": 10_000, "auto": 1.5 if i % 2 else None}}, now=0)
        rnd = t.finish()
        history.append({**t.round_record(rnd), "no": i + 1, "time": "00:00:00", "shoe": "비행"})
    per = {r["bet"]: r for r in by_bet(history)}
    assert set(per) == {"비행기 베팅"}
    assert per["비행기 베팅"]["count"] == 5
    assert sum(r["net"] for r in per.values()) == summarize(history)["net"] == t.wallet.balance - 1_000_000
    top = rows(history)[0]
    assert top["게임"] == "비행기" and top["결과"].startswith("추락") and top["슈"] == "#5"


def test_ladder_records():
    from ladder.game import LadderTable

    t = LadderTable(SessionWallet({}, initial=1_000_000))
    history = [{**t.play({"left": 10_000, "odd": 5_000, "R3O": 1_000}), "no": i + 1, "time": "00:00:00",
                "shoe": "사다리"} for i in range(5)]
    assert len(history) == 5
    per = {r["bet"]: r for r in by_bet(history)}
    assert set(per) == {"사다리 좌", "사다리 홀", "사다리 우3홀"}
    assert sum(r["net"] for r in per.values()) == summarize(history)["net"] == t.wallet.balance - 1_000_000
    top = rows(history)[0]
    assert top["게임"] == "사다리" and top["슈"] == "#5" and "적중" in top["결과"]
