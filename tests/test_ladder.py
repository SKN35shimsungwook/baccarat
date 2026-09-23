from collections import Counter

import pytest

from ladder.game import BETS, LadderError, LadderTable, draw, finish_of, odds_for, seed_hash
from wallet import SessionWallet

def table(balance=1_000_000, **kw):
    return LadderTable(SessionWallet({}, initial=balance), **kw)


def test_finish_rule():
    assert finish_of("L", 3) == "even"   # 좌3짝
    assert finish_of("L", 4) == "odd"    # 좌4홀
    assert finish_of("R", 3) == "odd"    # 우3홀
    assert finish_of("R", 4) == "even"   # 우4짝


def test_four_outcomes_are_equally_likely():
    counts = Counter(draw("seed", "client", k)["code"] for k in range(40_000))
    assert set(counts) == {"L3E", "L4O", "R3O", "R4E"}
    for c in counts.values():
        assert c / 40_000 == pytest.approx(0.25, abs=0.01)


def test_rung_heights_are_ordered_and_inside():
    for k in range(200):
        r = draw("s", "c", k)
        h = r["heights"]
        assert len(h) == r["lines"] and h == sorted(h)
        assert 0.15 < h[0] and h[-1] < 0.85


def test_payouts_follow_rtp():
    assert odds_for(0.95, 0.5) == 1.90 and odds_for(0.95, 0.25) == 3.80
    assert odds_for(0.97, 0.5) == 1.94 and odds_for(0.97, 0.25) == 3.88
    t = table()
    assert t.payouts()["left"] == 1.90 and t.payouts()["R4E"] == 3.80


def test_play_settles_immediately():
    t = table()
    commit, seed = t.commit, t.server_seed
    rec = t.play({"left": 10_000, "odd": 5_000, "L4O": 1_000})
    res = t.results[-1]
    assert res["round"] == 1 == rec["round_no"] and t.round == 1
    assert res["code"] == draw(seed, t.client_seed, 1)["code"]
    expected = sum(
        int(amount * odds) if BETS[key][1](res) else 0
        for key, amount, odds in (("left", 10_000, 1.9), ("odd", 5_000, 1.9), ("L4O", 1_000, 3.8))
    )
    assert rec["total_returned"] == expected
    assert t.wallet.balance == 1_000_000 - 16_000 + expected
    assert rec["game"] == "ladder" and rec["result"] == res["text"]
    assert sum(s["stake"] for s in rec["settlements"]) == rec["total_stake"] == 16_000
    assert rec["fair"]["commit"] == commit == seed_hash(rec["fair"]["seed"])
    assert t.commit != commit   # 다음 회차는 새 시드


def test_accounting_over_many_rounds():
    t = table(balance=10_000_000)
    net = sum(t.play({"left": 2_000, "odd": 1_000})["net"] for _ in range(300))
    assert t.wallet.balance == 10_000_000 + net
    assert t.round == 300 and len(t.results) == 200
    v = t.to_view()
    assert v["round"] == 301 and len(v["recent"]) == 20 and len(v["finishes"]) == 120


def test_validation():
    t = table(balance=5_000)
    with pytest.raises(LadderError, match="칩이 부족"):
        t.play({"left": 3_000, "odd": 3_000})
    with pytest.raises(LadderError, match="없는 베팅"):
        t.play({"middle": 1_000})
    with pytest.raises(LadderError, match="베팅은"):
        t.play({"left": 500})
    with pytest.raises(LadderError, match="베팅이 없습니다"):
        t.play({})
    assert t.wallet.balance == 5_000 and t.round == 0


def test_no_hedge_bets():
    from ladder.game import hedge_error

    assert hedge_error({"left", "right"}) and hedge_error({"three", "four"}) and hedge_error({"odd", "even"})
    assert hedge_error({"L3E", "L4O", "R3O", "R4E"})          # 4조합 전부
    assert hedge_error({"odd", "L3E", "R4E"})                 # 홀 + 짝이 되는 조합 전부
    assert hedge_error({"left", "R3O", "R4E"})                # 좌 + 우 조합 전부
    assert hedge_error({"left", "odd", "three"}) is None
    assert hedge_error({"L3E", "R3O"}) is None

    t = table()
    with pytest.raises(LadderError, match="양방"):
        t.play({"left": 1_000, "right": 1_000})
    with pytest.raises(LadderError, match="양방"):
        t.play({"left": 1_000, "R3O": 1_000, "R4E": 1_000})
    assert t.wallet.balance == 1_000_000 and t.round == 0
    t.play({"left": 1_000, "odd": 1_000})
