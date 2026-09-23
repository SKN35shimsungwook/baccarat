import random
from fractions import Fraction

import pytest

from bj.cards import BJCard, BJShoe, hand_value
from bj.game import BJError, BJTable, Phase
from bj.rules import BJRules, perfect_pairs, twenty_one_3
from bj.strategy import basic_action
from engine.shoe import Card
from wallet import SessionWallet


def cards(*specs):
    """'AS', '10H', 'KD' 같은 표기로 카드 목록을 만든다."""
    return [BJCard(i, Card(s[:-1], s[-1])) for i, s in enumerate(specs)]


class StackedShoe(BJShoe):
    """정해진 순서로 카드를 내주는 테스트용 슈 (뒤에는 무작위 카드)."""

    def __init__(self, order, **kw):
        super().__init__(rng=random.Random(0), **kw)
        stacked = [Card(s[:-1], s[-1]) for s in order]
        self.cards[self._pos:self._pos] = stacked


def table_with(order, balance=1_000_000, **rules):
    t = BJTable(SessionWallet({}, initial=balance), BJRules(**rules), rng=random.Random(0))
    t.shoe = StackedShoe(order, shoe_no=t.shoe_no)
    return t


# ── 점수 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("specs, total, soft", [
    (("AS", "6H"), 17, True),
    (("10S", "7H"), 17, False),
    (("AS", "AH"), 12, True),
    (("AS", "AH", "9D"), 21, True),
    (("AS", "6H", "10D"), 17, False),
    (("AS", "AH", "AD", "AC", "2S", "2H", "2D", "2C", "3S", "3H", "3D"), 21, False),  # 리포트의 11장 예시
])
def test_hand_value(specs, total, soft):
    assert hand_value(cards(*specs)) == (total, soft)


# ── 사이드 베팅 ─────────────────────────────────────────────────────
def test_perfect_pairs():
    assert perfect_pairs(*cards("7H", "7H")) == "perfect"
    assert perfect_pairs(*cards("7H", "7D")) == "colored"
    assert perfect_pairs(*cards("7H", "7S")) == "mixed"
    assert perfect_pairs(*cards("7H", "8H")) is None


@pytest.mark.parametrize("specs, kind", [
    (("7H", "7H", "7H"), "suited_trips"),
    (("5S", "6S", "7S"), "straight_flush"),
    (("9C", "9D", "9S"), "three_kind"),
    (("AS", "2H", "3D"), "straight"),
    (("QS", "KH", "AD"), "straight"),
    (("KS", "AH", "2D"), None),
    (("2H", "9H", "KH"), "flush"),
])
def test_21_plus_3(specs, kind):
    assert twenty_one_3(*cards(*specs)) == kind


# ── 진행 / 정산 ─────────────────────────────────────────────────────
# 딜링 순서: 자리 카드1 → 딜러 업 → 자리 카드2 → 딜러 홀 → 이후 히트
def test_player_blackjack_pays_3_to_2():
    t = table_with(["AS", "9H", "KD", "7C"])
    t.start_round({0: {"main": 10_000}})
    assert t.phase is Phase.DONE
    assert t.seats[0].hands[0].result == "blackjack"
    assert t.round_returned == 25_000
    assert t.wallet.balance == 1_000_000 + 15_000


def test_six_to_five_rounds_down():
    t = table_with(["AS", "9H", "KD", "7C"], blackjack_payout=Fraction(6, 5))
    t.start_round({0: {"main": 1_005}})
    assert t.seats[0].hands[0].returned == 1_005 + 1_206  # 1206.0


def test_dealer_s17_vs_h17():
    # 플레이어 10+8 스탠드, 딜러 A+6 (소프트 17) → S17은 멈추고 H17은 한 장(4) 더 받아 21
    for h17, expect in ((False, "win"), (True, "lose")):
        t = table_with(["10S", "AH", "8D", "6C", "4S"], h17=h17)
        t.start_round({0: {"main": 1_000}})
        if t.phase is Phase.INSURANCE:
            t.insure({})
        t.act("stand")
        assert t.seats[0].hands[0].result == expect, h17


def test_dealer_peek_blackjack_settles_immediately():
    t = table_with(["9S", "KH", "9D", "AC"])
    t.start_round({0: {"main": 1_000}})
    assert t.phase is Phase.DONE and t.hole_revealed
    assert t.seats[0].hands[0].result == "lose"


def test_insurance_pays_2_to_1():
    t = table_with(["9S", "AH", "9D", "KC"])
    t.start_round({0: {"main": 10_000}})
    assert t.phase is Phase.INSURANCE
    t.insure({0: True})
    assert t.phase is Phase.DONE
    # 메인 -10,000, 인슈어런스 5,000 걸고 15,000 돌려받음 → 본전
    assert t.wallet.balance == 1_000_000


def test_split_double_after_split_and_accounting():
    # 8,8 vs 6 → 스플릿. 첫 손 8+3 더블(→ +10), 둘째 손 8+10 스탠드. 딜러 6+10+9 버스트
    t = table_with(["8S", "6H", "8D", "10C", "3S", "10H", "10D", "9C"])
    t.start_round({0: {"main": 1_000}})
    assert "split" in t.legal()
    t.act("split")
    assert t.active == (0, 0) and len(t.seats[0].hands[0].cards) == 2
    assert "double" in t.legal()
    t.act("double")
    t.act("stand")
    assert t.phase is Phase.DONE
    hands = t.seats[0].hands
    assert [h.bet for h in hands] == [2_000, 1_000]
    assert [h.result for h in hands] == ["win", "win"]
    assert t.wallet.balance == 1_000_000 + 3_000
    assert sum(e["stake"] for e in t.settlements) == t.round_stake


def test_split_aces_get_one_card_and_21_is_not_blackjack():
    t = table_with(["AS", "7H", "AD", "9C", "KS", "5H", "10S"])  # 딜러 7+9+10 버스트
    t.start_round({0: {"main": 1_000}})
    t.act("split")
    assert t.phase is Phase.DONE
    first, second = t.seats[0].hands
    assert len(first.cards) == 2 and first.total == 21 and not first.is_blackjack
    assert first.result == "win" and first.returned == 2_000  # 1:1, 3:2 아님


def test_surrender_returns_half():
    t = table_with(["10S", "10H", "6D", "8C"])
    t.start_round({0: {"main": 1_000}})
    assert "surrender" in t.legal()
    t.act("surrender")
    assert t.seats[0].hands[0].returned == 500


def test_bust_ends_hand_and_dealer_skips_when_all_bust():
    t = table_with(["10S", "7H", "6D", "9C", "KS"])
    t.start_round({0: {"main": 1_000}})
    t.act("hit")
    assert t.phase is Phase.DONE
    assert len(t.dealer) == 2  # 살아 있는 손이 없으면 딜러는 더 받지 않는다


def test_side_bets_and_seat_validation():
    t = table_with(["7H", "5H", "7H", "10C"])
    t.start_round({0: {"main": 1_000, "pp": 1_000, "t213": 1_000}})
    kinds = {e["bet"]: e for e in t.settlements}
    assert kinds["bj_pp"]["returned"] == 26_000       # 퍼펙트 페어 25:1
    assert kinds["bj_213"]["returned"] == 6_000        # 7♥ 7♥ + 딜러 5♥ → 플러시 5:1
    with pytest.raises(BJError, match="진행 중"):
        t.start_round({0: {"main": 1_000}})


def test_validation_errors():
    t = BJTable(SessionWallet({}, initial=5_000), rng=random.Random(1))
    with pytest.raises(BJError, match="메인 베팅"):
        t.start_round({0: {"pp": 1_000}})
    with pytest.raises(BJError, match="칩이 부족"):
        t.start_round({0: {"main": 3_000}, 1: {"main": 3_000}})
    assert t.wallet.balance == 5_000


def test_random_play_keeps_chip_accounting():
    rng = random.Random(42)
    store = {}
    t = BJTable(SessionWallet(store, initial=100_000_000), rng=random.Random(3))
    for _ in range(400):
        before = t.wallet.balance
        t.start_round({s: {"main": 1_000, "pp": rng.choice([0, 1_000]), "t213": rng.choice([0, 1_000])}
                       for s in range(rng.randint(1, 3))})
        if t.phase is Phase.INSURANCE:
            t.insure({s.index: rng.random() < 0.5 for s in t.seats})
        while t.phase is Phase.PLAYER:
            t.act(rng.choice(t.legal()))
        assert t.phase is Phase.DONE
        assert t.wallet.balance - before == t.round_returned - t.round_stake
        assert sum(e["stake"] for e in t.settlements) == t.round_stake
        rec = t.round_record()
        assert rec["net"] == t.wallet.balance - before
    assert t.shoe_no > 1  # 컷 카드가 나오면 새 슈로 바뀐다


# ── 기본 전략 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("specs, up, h17, expect", [
    (("10S", "6H"), "10", False, "surrender"),
    (("10S", "6H"), "7", False, "hit"),
    (("10S", "2H"), "4", False, "stand"),
    (("5S", "6H"), "A", False, "hit"),
    (("5S", "6H"), "A", True, "double"),
    (("AS", "7H"), "2", False, "stand"),
    (("AS", "7H"), "2", True, "double"),
    (("AS", "7H"), "9", False, "hit"),
    (("8S", "8H"), "10", False, "split"),
    (("9S", "9H"), "7", False, "stand"),
    (("KS", "QH"), "6", False, "stand"),
    (("5S", "5H"), "9", False, "double"),
])
def test_basic_strategy(specs, up, h17, expect):
    got = basic_action(cards(*specs), up, BJRules(h17=h17), can_double=True, can_split=True, can_surrender=True)
    assert got == expect


def test_simulation_six_to_five_costs_about_1_4_percent():
    from bj.sim import simulate

    base = simulate(BJRules(), 20_000, seed=3)
    worse = simulate(BJRules(blackjack_payout=Fraction(6, 5)), 20_000, seed=3)  # 같은 카드 순서
    assert -0.03 < base["edge"] < 0.03
    assert 0.010 < worse["edge"] - base["edge"] < 0.018
    assert 0.040 < base["blackjack"] < 0.050
