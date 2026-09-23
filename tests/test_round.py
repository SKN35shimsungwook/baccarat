import random
from collections import Counter

import pytest

from engine import Bet, BetError, GameTable, Phase
from engine.shoe import Shoe
from wallet import SessionWallet


def test_shoe_composition_and_burn():
    shoe = Shoe(rng=random.Random(1))
    assert len(shoe.cards) == 416
    assert Counter(c.rank for c in shoe.cards)["K"] == 32
    assert shoe.dealt == 1 + (shoe.burn_card.value or 10)


def test_invalid_bet_keeps_balance():
    store = {}
    table = GameTable(SessionWallet(store, initial=5000), rng=random.Random(2))
    with pytest.raises(BetError):
        table.play_round({Bet.PLAYER: 10_000})
    assert store["chips"] == 5000
    assert table.history == []


def test_full_shoe_chip_accounting():
    store = {}
    wallet = SessionWallet(store, initial=10_000_000)
    table = GameTable(wallet, rng=random.Random(3))
    expected = wallet.balance
    rounds = 0
    while table.phase is Phase.BETTING:
        out = table.play_round({Bet.BANKER: 1000, Bet.TIE: 1000, Bet.PLAYER_PAIR: 1000})
        expected += out.net
        assert wallet.balance == expected == out.balance_after
        rounds += 1
    assert table.phase is Phase.SHOE_END
    assert 60 < rounds < 90          # 8덱 슈는 보통 70~80판
    assert table.shoe.remaining < 16
    with pytest.raises(RuntimeError):
        table.play_round({Bet.BANKER: 1000})
    table.new_shoe()
    assert table.phase is Phase.BETTING and table.history == [] and table.shoe_no == 2
