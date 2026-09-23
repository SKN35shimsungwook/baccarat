from collections import Counter
from fractions import Fraction

import pytest

from dice.game import BETS, DiceError, DiceTable, describe, odds_for, probability, roll_dice, seed_hash
from wallet import SessionWallet


def test_probabilities():
    # 트리플이면 홀짝·대소는 진다: 216 가지 중 트리플 3개씩 빠짐
    assert probability("odd") == probability("even") == Fraction(105, 216)
    assert probability("small") == probability("big") == Fraction(105, 216)
    assert probability("double") == Fraction(96, 216)
    assert probability("triple") == Fraction(6, 216)


def test_payouts_follow_rtp():
    assert odds_for(0.95, "odd") == 1.95
    assert odds_for(0.95, "double") == 2.13 and odds_for(0.95, "triple") == 34.2
    for key in BETS:  # 기대 환수 ≈ 환수율 (내림 때문에 약간 낮을 수 있음)
        ev = float(probability(key)) * odds_for(0.95, key)
        assert 0.94 < ev <= 0.95 + 1e-9


def test_describe_triple_loses_parity_and_size():
    assert describe((2, 2, 2)) == {"sum": 6, "triple": True, "parity": "triple", "size": "triple"}
    assert describe((1, 2, 4))["parity"] == "odd" and describe((1, 2, 4))["size"] == "small"
    assert describe((6, 5, 1))["parity"] == "even" and describe((6, 5, 1))["size"] == "big"
    assert not BETS["odd"][1]((3, 3, 3)) and not BETS["small"][1]((3, 3, 3))
    assert BETS["double"][1]((3, 3, 3)) and BETS["triple"][1]((3, 3, 3))
    assert BETS["double"][1]((2, 5, 2)) and not BETS["double"][1]((1, 2, 3))


def test_dice_are_uniform():
    faces = Counter()
    for n in range(20_000):
        for f in roll_dice("seed", "client", n):
            faces[f] += 1
    assert set(faces) == {1, 2, 3, 4, 5, 6}
    for c in faces.values():
        assert c / 60_000 == pytest.approx(1 / 6, abs=0.008)


def test_roll_settles_and_reveals_seed():
    t = DiceTable(SessionWallet({}, initial=100_000))
    commit, seed = t.commit, t.server_seed
    rec = t.roll({"odd": 10_000, "triple": 1_000, "double": 1_000})
    dice = tuple(rec["dice"])
    assert dice == roll_dice(seed, t.client_seed, 1)
    assert rec["fair"]["commit"] == commit == seed_hash(rec["fair"]["server_seed"])
    triple = len(set(dice)) == 1
    expected = ((19_500 if sum(dice) % 2 and not triple else 0) + (34_200 if triple else 0)
                + (2_130 if len(set(dice)) < 3 else 0))
    assert rec["total_returned"] == expected
    assert t.wallet.balance == 100_000 - 12_000 + expected
    assert rec["net"] == expected - 12_000 and rec["game"] == "dice"
    assert t.commit != commit  # 다음 판은 새 시드


def test_accounting_over_many_rolls():
    t = DiceTable(SessionWallet({}, initial=10_000_000))
    net = 0
    for _ in range(500):
        net += t.roll({"even": 2_000, "big": 1_000, "double": 1_000})["net"]
    assert t.wallet.balance == 10_000_000 + net
    v = t.to_view()
    assert len(v["recent"]) == 20 and len(v["road"]) == 120
    assert v["stats"]["n"] == 100 and sum(v["stats"]["faces"]) == 300


def test_validation():
    t = DiceTable(SessionWallet({}, initial=5_000))
    with pytest.raises(DiceError, match="칩이 부족"):
        t.roll({"odd": 3_000, "big": 3_000})
    with pytest.raises(DiceError, match="없는 베팅"):
        t.roll({"r1": 1_000})
    with pytest.raises(DiceError, match="베팅은"):
        t.roll({"odd": 500})
    with pytest.raises(DiceError, match="베팅이 없습니다"):
        t.roll({})
    assert t.wallet.balance == 5_000 and t.nonce == 0


def test_ledger_rows_for_dice():
    from ledger import by_bet, rows

    t = DiceTable(SessionWallet({}, initial=100_000))
    rec = t.roll({"odd": 1_000, "double": 1_000})
    h = [{**rec, "no": 1, "time": "00:00:00", "shoe": "주사위"}]
    row = rows(h)[0]
    assert row["게임"] == "주사위" and row["슈"] == "#1"
    assert row["베팅"] == "홀 1,000 · 더블 1,000"
    assert f"합 {rec['sum']}" in row["결과"]
    assert [b["bet"] for b in by_bet(h)] == ["주사위 홀", "주사위 더블"]


def test_no_hedge_bets():
    from dice.game import hedge_error

    t = DiceTable(SessionWallet({}, initial=100_000))
    for bets in ({"odd": 1_000, "even": 1_000}, {"small": 1_000, "big": 1_000},
                 {"odd": 1_000, "small": 1_000, "big": 1_000, "triple": 1_000}):
        with pytest.raises(DiceError, match="양방"):
            t.roll(bets)
    assert t.wallet.balance == 100_000 and t.nonce == 0
    # 한쪽 + 사이드 베팅은 괜찮다
    assert hedge_error({"odd", "small", "double", "triple"}) is None
    assert hedge_error({"even", "big"}) is None
    t.roll({"odd": 1_000, "big": 1_000, "triple": 1_000})
