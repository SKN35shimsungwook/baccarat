from collections import Counter

import pytest

from ladder.game import BETS, LadderError, LadderTable, draw, finish_of, odds_for, seed_hash
from wallet import SessionWallet

T0 = 1_000_000.0  # 테스트용 기준 시각


def table(balance=1_000_000, **kw):
    return LadderTable(SessionWallet({}, initial=balance), epoch=T0, **kw)


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


def test_schedule_lock_and_settlement():
    t = table()
    assert t.round_at(T0) == 1 and t.draw_time(1) == T0 + 60 and t.lock_time(1) == T0 + 50
    k = t.place({"left": 10_000, "odd": 5_000, "L4O": 1_000}, now=T0 + 10)
    assert k == 1 and t.wallet.balance == 1_000_000 - 16_000
    with pytest.raises(LadderError, match="마감"):
        t.place({"right": 1_000}, now=T0 + 55)
    assert t.resolve(now=T0 + 59) == []          # 아직 추첨 전
    [rec] = t.resolve(now=T0 + 60.1)
    res = t.results[-1]
    expected = sum(
        int(amount * odds) if BETS[key][1](res) else 0
        for key, amount, odds in (("left", 10_000, 1.9), ("odd", 5_000, 1.9), ("L4O", 1_000, 3.8))
    )
    assert rec["total_returned"] == expected
    assert t.wallet.balance == 1_000_000 - 16_000 + expected
    assert rec["game"] == "ladder" and rec["round_no"] == 1 and rec["result"] == res["text"]
    assert sum(s["stake"] for s in rec["settlements"]) == rec["total_stake"] == 16_000


def test_odds_are_fixed_when_the_bet_is_placed():
    t = table(rtp=0.95)
    t.place({"left": 10_000}, now=T0 + 1)
    t.rtp = 0.80   # 베팅한 뒤에 환수율을 바꿔도
    [rec] = t.resolve(now=T0 + 61)
    assert rec["settlements"][0]["detail"] == "1.90x"


def test_catch_up_after_being_away():
    t = table()
    t.place({"even": 2_000}, now=T0 + 5)
    recs = t.resolve(now=T0 + 60 * 1000)   # 1000회차 뒤에 돌아옴
    assert len(recs) == 1 and recs[0]["round_no"] == 1   # 걸어 둔 베팅은 정산된다
    assert len(t.results) <= 200
    assert t.results[-1]["round"] == 1000
    assert t.resolve(now=T0 + 60 * 1000 + 1) == []


def test_provably_fair_commit_and_reveal():
    t = table()
    commit = t.commit(1)                     # 회차 전에 보여 주는 해시
    t.resolve(now=T0 + 61)
    res = t.results[-1]
    assert res["round"] == 1 and seed_hash(res["seed"]) == commit == res["commit"]
    assert draw(res["seed"], res["client_seed"], 1)["code"] == res["code"]


def test_period_change_keeps_round_numbers():
    t = table()
    t.place({"left": 1_000}, now=T0 + 5)
    with pytest.raises(LadderError, match="정산된 뒤"):
        t.set_period(30, now=T0 + 6)
    t.resolve(now=T0 + 61)
    t.set_period(30, now=T0 + 70)            # 지금은 2회차가 열려 있다
    assert t.round_at(T0 + 70) == 2 and t.draw_time(2) == T0 + 100
    assert t.round_at(T0 + 101) == 3


def test_validation():
    t = table(balance=5_000)
    with pytest.raises(LadderError, match="칩이 부족"):
        t.place({"left": 3_000, "right": 3_000}, now=T0)
    with pytest.raises(LadderError, match="없는 베팅"):
        t.place({"middle": 1_000}, now=T0)
    with pytest.raises(LadderError, match="베팅은"):
        t.place({"left": 500}, now=T0)
    assert t.wallet.balance == 5_000


def test_view():
    t = table()
    t.place({"odd": 3_000}, now=T0 + 1)
    t.place({"odd": 2_000}, now=T0 + 2)
    v = t.to_view(now=T0 + 3)
    assert v["round"] == 1 and v["mine"] == {"odd": 5_000}
    assert v["draw_at"] == T0 + 60 and v["commit"] == t.commit(1)
    assert v["last"] is None
