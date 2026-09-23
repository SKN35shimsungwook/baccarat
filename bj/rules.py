"""블랙잭 테이블 규칙과 배당, 사이드 베팅(퍼펙트 페어, 21+3) 판정."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

RANK_ORDER = {r: i for i, r in enumerate(("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"), 1)}
RED = ("H", "D")


@dataclass(frozen=True)
class BJRules:
    decks: int = 6
    penetration: float = 0.75
    h17: bool = False                 # True면 딜러가 소프트 17에서 한 장 더 받는다
    blackjack_payout: Fraction = Fraction(3, 2)   # 3:2 또는 6:5
    das: bool = True                  # 스플릿 후 더블 허용
    max_hands: int = 4                # 스플릿으로 만들 수 있는 최대 손 수 (재스플릿 3번)
    resplit_aces: bool = False
    surrender: bool = True            # 늦은 서렌더 (딜러 블랙잭 확인 후)
    insurance: bool = True
    min_bet: int = 1_000
    max_bet: int = 5_000_000
    side_max_bet: int = 500_000

    @property
    def label(self) -> str:
        bj = "3:2" if self.blackjack_payout == Fraction(3, 2) else "6:5"
        return f"{self.decks}덱 · {'H17' if self.h17 else 'S17'} · 블랙잭 {bj}"


# ── 사이드 베팅 ──────────────────────────────────────────────────────
PERFECT_PAIRS = {"perfect": 25, "colored": 12, "mixed": 6}
PERFECT_PAIRS_LABEL = {"perfect": "퍼펙트 페어", "colored": "컬러 페어", "mixed": "믹스 페어"}

TWENTY_ONE_3 = {"suited_trips": 100, "straight_flush": 40, "three_kind": 30, "straight": 10, "flush": 5}
TWENTY_ONE_3_LABEL = {
    "suited_trips": "같은 무늬 트리플", "straight_flush": "스트레이트 플러시",
    "three_kind": "트리플", "straight": "스트레이트", "flush": "플러시",
}


def perfect_pairs(c1, c2) -> str | None:
    """플레이어 첫 두 장이 같은 랭크일 때: 같은 무늬 / 같은 색 / 다른 색."""
    if c1.rank != c2.rank:
        return None
    if c1.suit == c2.suit:
        return "perfect"
    if (c1.suit in RED) == (c2.suit in RED):
        return "colored"
    return "mixed"


def _is_straight(ranks) -> bool:
    nums = sorted(RANK_ORDER[r] for r in ranks)
    if len(set(nums)) != 3:
        return False
    return nums[2] - nums[0] == 2 or nums == [1, 12, 13]  # A-2-3 또는 Q-K-A


def twenty_one_3(c1, c2, up) -> str | None:
    """플레이어 첫 두 장 + 딜러 업카드로 만든 3장 포커 패."""
    cards = (c1, c2, up)
    ranks = [c.rank for c in cards]
    flush = len({c.suit for c in cards}) == 1
    trips = len(set(ranks)) == 1
    if trips and flush:
        return "suited_trips"
    straight = _is_straight(ranks)
    if straight and flush:
        return "straight_flush"
    if trips:
        return "three_kind"
    if straight:
        return "straight"
    if flush:
        return "flush"
    return None
