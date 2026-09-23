from collections import Counter

import pytest

from horse.game import (LANES, NAMES, RACE_SECONDS, RTP_REF, STYLES, TIERS, HorseError, HorseTable, odds_for,
                        race_order, race_script, seed_hash)
from wallet import SessionWallet


def table(balance=1_000_000, **kw):
    return HorseTable(SessionWallet({}, initial=balance), **kw)


def test_pool_and_lineup():
    t = table()
    assert len(NAMES) == 50 == len(set(NAMES)) == len(t.pool)
    for _ in range(300):
        t._next_race()
        probs = [e["prob"] for e in t.lineup]
        assert len(t.lineup) == LANES and len({e["id"] for e in t.lineup}) == LANES
        assert sum(probs) == pytest.approx(1)
        tiers = Counter(e["tier"] for e in t.lineup)
        assert tiers["S"] >= 1 and tiers["O"] >= 1


def test_odds_bands_by_tier():
    t = table()
    bands = {"S": (2, 4), "A": (5, 16), "O": (18, 90)}
    for _ in range(300):
        t._next_race()
        for e in t.lineup_view():
            lo, hi = bands[e["tier"]]
            assert lo - 0.01 <= e["odds"] <= hi, e
    assert t.rtp == RTP_REF == 0.96 and odds_for(0.95, 0.25) == 3.8


def test_winner_follows_probabilities():
    probs = [0.4, 0.25, 0.15, 0.1, 0.07, 0.03]
    wins = Counter(race_order("seed", "client", n, probs)[0] for n in range(30_000))
    for lane, p in enumerate(probs, start=1):
        assert wins[lane] / 30_000 == pytest.approx(p, abs=0.012)


def test_order_is_a_permutation():
    for n in range(200):
        order = race_order("s", "c", n, [0.3, 0.3, 0.2, 0.1, 0.07, 0.03])
        assert sorted(order) == [1, 2, 3, 4, 5, 6]


def test_script_crosses_finish_in_order():
    for n in range(50):
        order = race_order("s", "c", n, [0.3, 0.3, 0.2, 0.1, 0.07, 0.03])
        sc = race_script("s", "c", n, order)
        dt = sc["dt"]
        crossed = []
        for lane in range(1, 7):
            row = sc["pos"][lane - 1]
            k = next(i for i, p in enumerate(row) if p >= 1.0 - 1e-6)
            crossed.append((k * dt, lane))
            assert all(b >= a - 1e-9 for a, b in zip(row, row[1:]))   # 뒤로 가지 않는다
        assert sc["finish"][order[0] - 1] == RACE_SECONDS
        assert [lane for lane in sorted(range(1, 7), key=lambda l: sc["finish"][l - 1])] == order


def test_play_settles_and_reveals_seed():
    t = table()
    lineup = t.lineup_view()
    commit, seed, probs = t.commit, t.server_seed, [e["prob"] for e in t.lineup]
    rec = t.play({"1": 10_000, "2": 5_000})
    order = race_order(seed, t.client_seed, 1, probs)
    assert rec["order"] == order and rec["fair"]["commit"] == commit == seed_hash(rec["fair"]["seed"])
    expected = sum(int(stake * lineup[int(lane) - 1]["odds"]) for lane, stake in (("1", 10_000), ("2", 5_000))
                   if int(lane) == order[0])
    assert rec["total_returned"] == expected
    assert t.wallet.balance == 1_000_000 - 15_000 + expected
    assert rec["game"] == "horse" and rec["round_no"] == 1
    assert {s["bet"] for s in rec["settlements"]} <= {f"hr_{k}" for k in TIERS}
    assert t.commit != commit and t.race_no == 1                     # 다음 경주는 새 출전표·시드
    winner = t.pool[t.results[-1]["lineup"][order[0] - 1]["id"]]
    assert winner["wins"] >= 1 and winner["form"][-1] == 1


def test_accounting_over_many_races():
    t = table(balance=10_000_000)
    net = sum(t.play({"1": 2_000, "4": 1_000})["net"] for _ in range(200))
    assert t.wallet.balance == 10_000_000 + net
    v = t.to_view()
    assert v["race_no"] == 201 and len(v["recent"]) == 12 and sum(v["tier_wins"].values()) == 100
    tip = v["tipster"]
    assert tip["n"] == 100 and set(tip["lineup"]) == {"1", "2", "3", "4", "5", "6"}
    assert sum(sum(r["lineup"][l - 1]["id"] == h["id"] for r in t.results[-100:]
                   for l in [r["order"][0]]) for h in tip["top"][:1]) == tip["top"][0]["wins"]
    assert all(a["wins"] >= b["wins"] for a, b in zip(tip["top"], tip["top"][1:]))


def test_validation_and_no_hedge():
    t = table(balance=5_000)
    with pytest.raises(HorseError, match="칩이 부족"):
        t.play({"1": 3_000, "2": 3_000})
    with pytest.raises(HorseError, match="없는 말"):
        t.play({"7": 1_000})
    with pytest.raises(HorseError, match="베팅은"):
        t.play({"1": 500})
    with pytest.raises(HorseError, match="양방"):
        t.play({str(i): 1_000 for i in range(1, 7)})
    assert t.wallet.balance == 5_000 and t.race_no == 0
    t.play({str(i): 1_000 for i in range(1, 6)})                   # 5마리까지는 된다


def test_ledger_rows_for_horse():
    from ledger import by_bet, rows

    t = table()
    rec = t.play({"1": 1_000, "2": 1_000})
    h = [{**rec, "no": 1, "time": "00:00:00", "shoe": "경마"}]
    row = rows(h)[0]
    assert row["게임"] == "경마" and row["슈"] == "#1" and row["결과"].startswith("1위 ")
    assert all(b["bet"].startswith("경마 ") for b in by_bet(h))


def test_running_style_shapes_the_race():
    """추입마는 선행마보다 초반(4초)에 뒤처져 있다가 결승선에서는 순위대로 들어온다."""
    order = [1, 2, 3, 4, 5, 6]
    early_front, early_closer = [], []
    for n in range(100):
        sc = race_script("s", "c", n, order, ["front", "closer", "mid", "mid", "mid", "mid"])
        k = int(4 / sc["dt"])
        early_front.append(sc["pos"][0][k])
        early_closer.append(sc["pos"][1][k])
    assert sum(early_front) / 100 > sum(early_closer) / 100 + 0.03
    t = table()
    assert all(h["style"] in STYLES for h in t.pool)
    assert {e["style_name"] for e in t.lineup_view()} <= set(STYLES.values())


def test_tipster_rtp():
    t = table(balance=10_000_000)
    for _ in range(150):
        t.play({"1": 1_000})
    tip = t.tipster()
    for lane, r in tip["lineup"].items():
        hid = t.lineup[int(lane) - 1]["id"]
        runs = [(x, x["order"].index(l) + 1) for x in t.results[-100:] for l in range(1, 7)
                if x["lineup"][l - 1]["id"] == hid]
        assert r["starts"] == len(runs)
        if runs:
            ret = sum(x["lineup"][x["order"][0] - 1]["odds"] for x, rank in runs if rank == 1)
            assert r["rtp"] == round(ret / len(runs) * 100)
    if tip["pick"]:
        best = tip["lineup"][str(tip["pick"])]["rtp"]
        assert all(r["rtp"] is None or r["rtp"] <= best for r in tip["lineup"].values())
