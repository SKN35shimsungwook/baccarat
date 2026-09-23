from engine.rules import BANKER, PLAYER, TIE, banker_draws, deal_round, hand_total, player_draws
from engine.shoe import Card

# 문서의 뱅커 규칙표: 뱅커 2장 합계 → 플레이어 3번째 카드가 이 값일 때 인출
BANKER_TABLEAU = {
    0: set(range(10)), 1: set(range(10)), 2: set(range(10)),
    3: set(range(10)) - {8},
    4: {2, 3, 4, 5, 6, 7},
    5: {4, 5, 6, 7},
    6: {6, 7},
    7: set(),
}


def c(rank, suit="S"):
    return Card(rank, suit)


def scripted(*ranks):
    it = iter(c(r) for r in ranks)
    return lambda: next(it)


def test_hand_total_mod10():
    assert hand_total([1, 7]) == 8
    assert hand_total([8, 7]) == 5
    assert hand_total([0, 0]) == 0
    assert hand_total([9, 6]) == 5


def test_card_values():
    assert [c(r).value for r in ("A", "2", "9", "10", "J", "Q", "K")] == [1, 2, 9, 0, 0, 0, 0]


def test_player_draw_rule():
    assert all(player_draws(t) for t in range(6))
    assert not player_draws(6) and not player_draws(7)


def test_banker_tableau_all_cases():
    for bt, draws_on in BANKER_TABLEAU.items():
        for p3 in range(10):
            assert banker_draws(bt, p3) == (p3 in draws_on), (bt, p3)


def test_banker_when_player_stands():
    assert all(banker_draws(t, None) for t in range(6))
    assert not banker_draws(6, None) and not banker_draws(7, None)


def test_natural_stops_round():
    # P: 9+K=9 (내추럴), B: 2+3=5 → 추가 카드 없음
    r = deal_round(scripted("9", "2", "K", "3"))
    assert len(r.player) == 2 and len(r.banker) == 2
    assert r.natural and r.winner == PLAYER


def test_player_draws_banker_uses_tableau():
    # P: 2+3=5 → 인출(8), B: 3+K=3 → P3이 8이면 스탠드
    r = deal_round(scripted("2", "3", "3", "K", "8"))
    assert [x.rank for x in r.player] == ["2", "3", "8"]
    assert len(r.banker) == 2
    assert r.deal_order == ("P", "B", "P", "B", "P")
    assert r.player_total == 3 and r.banker_total == 3 and r.winner == TIE


def test_player_stands_banker_draws_on_5():
    # P: 4+3=7 스탠드, B: 2+3=5 → 인출(4) → 9
    r = deal_round(scripted("4", "2", "3", "3", "4"))
    assert len(r.player) == 2 and len(r.banker) == 3
    assert r.deal_order == ("P", "B", "P", "B", "B")
    assert r.winner == BANKER


def test_pairs_use_rank_not_value():
    r = deal_round(scripted("K", "Q", "K", "J", "5", "5"))
    assert r.player_pair            # K, K
    assert not r.banker_pair        # Q, J 는 둘 다 0점이지만 랭크가 다름
