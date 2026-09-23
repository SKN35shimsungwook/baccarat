"""슈 전체(비복원 추출)를 기준으로 결과 확률과 하우스 에지를 정확히 계산한다.

rules.py의 규칙 함수를 그대로 써서 계산하므로, 이 값이 알려진 수치와 맞으면
엔진의 3구 규칙이 맞다는 검증이 된다.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from functools import lru_cache

from .bets import TableRules
from .rules import banker_draws, hand_total, is_natural, player_draws


def _value_counts(decks: int) -> list[int]:
    """점수별 카드 수. 0점은 10/J/Q/K 4종이라 16장/덱, 나머지는 4장/덱."""
    return [16 * decks] + [4 * decks] * 9


@lru_cache(maxsize=4)
def outcome_distribution(decks: int = 8) -> dict[tuple, float]:
    """(승자, 뱅커 점수, 뱅커 카드 수) → 확률."""
    counts = _value_counts(decks)
    total = sum(counts)
    dist: Counter = Counter()

    def take(v, n, cnt):
        p = cnt[v] / n
        cnt[v] -= 1
        return p

    cnt = counts[:]
    for p1 in range(10):
        w1 = take(p1, total, cnt)
        for b1 in range(10):
            w2 = w1 * take(b1, total - 1, cnt)
            for p2 in range(10):
                w3 = w2 * take(p2, total - 2, cnt)
                for b2 in range(10):
                    w4 = w3 * take(b2, total - 3, cnt)
                    pt, bt = hand_total((p1, p2)), hand_total((b1, b2))
                    if is_natural(pt) or is_natural(bt):
                        _record(dist, pt, bt, 2, w4)
                    elif player_draws(pt):
                        for p3 in range(10):
                            w5 = w4 * take(p3, total - 4, cnt)
                            pt3 = hand_total((pt, p3))
                            if banker_draws(bt, p3):
                                for b3 in range(10):
                                    if cnt[b3]:
                                        _record(dist, pt3, hand_total((bt, b3)), 3,
                                                w5 * cnt[b3] / (total - 5))
                            else:
                                _record(dist, pt3, bt, 2, w5)
                            cnt[p3] += 1
                    elif banker_draws(bt, None):
                        for b3 in range(10):
                            if cnt[b3]:
                                _record(dist, pt, hand_total((bt, b3)), 3, w4 * cnt[b3] / (total - 4))
                    else:
                        _record(dist, pt, bt, 2, w4)
                    cnt[b2] += 1
                cnt[p2] += 1
            cnt[b1] += 1
        cnt[p1] += 1
    return dict(dist)


def _record(dist, pt, bt, banker_cards, w):
    winner = "P" if pt > bt else "B" if bt > pt else "T"
    dist[(winner, bt, banker_cards)] += w


def win_probabilities(decks: int = 8) -> dict[str, float]:
    out = {"P": 0.0, "B": 0.0, "T": 0.0}
    for (w, _, _), p in outcome_distribution(decks).items():
        out[w] += p
    return out


def pair_probability(decks: int = 8) -> float:
    """처음 두 장이 같은 랭크일 확률 (13랭크 × 4*decks장)."""
    per_rank = 4 * decks
    n = 52 * decks
    return 13 * per_rank * (per_rank - 1) / (n * (n - 1))


def house_edges(rules: TableRules = TableRules(), decks: int = 8) -> dict[str, float]:
    """베팅별 하우스 에지(양수 = 카지노 유리). 메인 베팅은 타이 환불 포함."""
    dist = outcome_distribution(decks)
    probs = win_probabilities(decks)

    if rules.no_commission:
        banker_ev = sum(
            p * (Fraction(1, 2) if bt == 6 else 1) for (w, bt, _), p in dist.items() if w == "B"
        ) - probs["P"]
    else:
        banker_ev = probs["B"] * 0.95 - probs["P"]
    player_ev = probs["P"] - probs["B"]
    tie_ev = probs["T"] * (rules.tie_payout + 1) - 1
    pp = pair_probability(decks)
    pair_ev = pp * (rules.pair_payout + 1) - 1
    tiger_ev = sum(
        p * ((rules.tiger_two_card if n == 2 else rules.tiger_three_card) + 1)
        for (w, bt, n), p in dist.items() if w == "B" and bt == 6
    ) - 1
    return {
        "banker": -float(banker_ev),
        "player": -player_ev,
        "tie": -tie_ev,
        "pair": -pair_ev,
        "tiger": -tiger_ev,
    }
