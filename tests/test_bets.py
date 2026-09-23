import pytest

from engine.bets import Bet, BetError, Outcome, TableRules, settle, validate_bets
from engine.rules import RoundResult
from engine.shoe import Card


def hand(ranks):
    return tuple(Card(r, "H") for r in ranks)


def result(p, b):
    order = ("P", "B") * 2 + ("P",) * (len(p) - 2) + ("B",) * (len(b) - 2)
    return RoundResult(hand(p), hand(b), order)


def by_bet(settlements):
    return {s.bet: s for s in settlements}


def test_banker_win_commission():
    r = result(["2", "3"], ["4", "4"])  # B 8 승
    s = by_bet(settle({Bet.BANKER: 1000, Bet.PLAYER: 0}, r, TableRules()))
    assert s[Bet.BANKER].outcome is Outcome.WIN
    assert s[Bet.BANKER].returned == 1950
    assert Bet.PLAYER not in s  # 0원 베팅은 무시


def test_commission_rounds_down():
    r = result(["2", "3"], ["4", "4"])
    assert settle({Bet.BANKER: 1010}, r, TableRules())[0].returned == 1010 + 959  # 959.5 → 959


def test_tie_pushes_main_bets_and_pays_tie():
    r = result(["4", "3"], ["5", "2"])  # 7:7
    s = by_bet(settle({Bet.PLAYER: 1000, Bet.TIE: 1000}, r, TableRules()))
    assert s[Bet.PLAYER].outcome is Outcome.PUSH and s[Bet.PLAYER].returned == 1000
    assert s[Bet.TIE].returned == 9000
    s9 = by_bet(settle({Bet.TIE: 1000}, r, TableRules(tie_payout=9)))
    assert s9[Bet.TIE].returned == 10000


def test_super6_banker_six_pays_half():
    r = result(["2", "2"], ["3", "3"])  # B 6 : P 4
    rules = TableRules(no_commission=True)
    assert settle({Bet.BANKER: 1000}, r, rules)[0].returned == 1500
    r8 = result(["2", "2"], ["4", "4"])
    assert settle({Bet.BANKER: 1000}, r8, rules)[0].returned == 2000


def test_pairs_and_tiger():
    r = result(["7", "7", "K"], ["3", "3"])  # P페어, P 4 / B 6 → 뱅커 2장 6 승
    s = by_bet(settle({Bet.PLAYER_PAIR: 1000, Bet.BANKER_PAIR: 1000, Bet.TIGER: 1000}, r, TableRules()))
    assert s[Bet.PLAYER_PAIR].returned == 12000
    assert s[Bet.BANKER_PAIR].returned == 12000
    assert s[Bet.TIGER].returned == 13000
    r3 = result(["7", "7", "K"], ["2", "2", "2"])  # 뱅커 3장 6
    assert settle({Bet.TIGER: 1000}, r3, TableRules())[0].returned == 21000


@pytest.mark.parametrize("bets, balance, msg", [
    ({}, 10_000, "베팅이 없습니다"),
    ({Bet.PLAYER: 500}, 10_000, "최소 베팅"),
    ({Bet.PLAYER: 1000, Bet.BANKER: 1000}, 10_000, "동시에"),
    ({Bet.TIGER: 600_000}, 10_000_000, "최대 베팅"),
    ({Bet.PLAYER: 8000, Bet.TIE: 3000}, 10_000, "칩이 부족"),
])
def test_validation_errors(bets, balance, msg):
    with pytest.raises(BetError, match=msg):
        validate_bets(bets, TableRules(), balance)
