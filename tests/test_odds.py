"""8덱 전체 조합 계산값이 문서(와 널리 알려진) 수치와 일치하는지 확인."""
import pytest

from engine.bets import TableRules
from engine.odds import house_edges, pair_probability, win_probabilities


def test_win_probabilities():
    p = win_probabilities(8)
    assert p["B"] == pytest.approx(0.4586, abs=5e-5)
    assert p["P"] == pytest.approx(0.4462, abs=5e-5)
    assert p["T"] == pytest.approx(0.0952, abs=5e-5)
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-12)


def test_house_edges_standard():
    e = house_edges(TableRules())
    assert e["banker"] == pytest.approx(0.0106, abs=5e-5)
    assert e["player"] == pytest.approx(0.0124, abs=5e-5)
    assert e["tie"] == pytest.approx(0.1436, abs=5e-5)
    assert e["pair"] == pytest.approx(0.1036, abs=5e-5)


def test_tie_9_to_1():
    assert house_edges(TableRules(tie_payout=9))["tie"] == pytest.approx(0.0484, abs=5e-5)


def test_super6_banker_edge():
    assert house_edges(TableRules(no_commission=True))["banker"] == pytest.approx(0.0146, abs=5e-5)


def test_pair_probability():
    assert pair_probability(8) == pytest.approx(0.0747, abs=5e-5)


def test_tiger_has_house_edge():
    assert 0 < house_edges(TableRules())["tiger"] < 0.3
