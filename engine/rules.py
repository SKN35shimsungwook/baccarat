"""바카라 점수 계산과 3구 인출 규칙(Tableau).

카드를 뽑는 순서는 실제 딜링과 같다: P1, B1, P2, B2, (P3), (B3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .shoe import Card

PLAYER = "P"
BANKER = "B"
TIE = "T"


def hand_total(values) -> int:
    """카드 점수 합의 일의 자리 (S mod 10)."""
    return sum(values) % 10


def is_natural(total: int) -> bool:
    return total >= 8


def player_draws(player_total: int) -> bool:
    """플레이어: 0~5 인출, 6~7 스탠드."""
    return player_total <= 5


def banker_draws(banker_total: int, player_third: int | None) -> bool:
    """뱅커 인출 여부.

    player_third: 플레이어가 받은 3번째 카드의 점수. 플레이어가 스탠드했으면 None.
    """
    if player_third is None:
        return banker_total <= 5
    if banker_total <= 2:
        return True
    if banker_total == 3:
        return player_third != 8
    if banker_total == 4:
        return 2 <= player_third <= 7
    if banker_total == 5:
        return 4 <= player_third <= 7
    if banker_total == 6:
        return player_third in (6, 7)
    return False  # 7은 스탠드 (8, 9는 내추럴이라 여기까지 오지 않음)


@dataclass(frozen=True)
class RoundResult:
    player: tuple[Card, ...]
    banker: tuple[Card, ...]
    deal_order: tuple[str, ...]  # 화면 애니메이션용: ("P","B","P","B","P"?,"B"?)

    @property
    def player_total(self) -> int:
        return hand_total(c.value for c in self.player)

    @property
    def banker_total(self) -> int:
        return hand_total(c.value for c in self.banker)

    @property
    def winner(self) -> str:
        p, b = self.player_total, self.banker_total
        if p > b:
            return PLAYER
        if b > p:
            return BANKER
        return TIE

    @property
    def natural(self) -> bool:
        return is_natural(hand_total(c.value for c in self.player[:2])) or is_natural(
            hand_total(c.value for c in self.banker[:2])
        )

    @property
    def player_pair(self) -> bool:
        return self.player[0].rank == self.player[1].rank

    @property
    def banker_pair(self) -> bool:
        return self.banker[0].rank == self.banker[1].rank

    def to_dict(self) -> dict:
        return {
            "player": [c.to_dict() for c in self.player],
            "banker": [c.to_dict() for c in self.banker],
            "deal_order": list(self.deal_order),
            "player_total": self.player_total,
            "banker_total": self.banker_total,
            "winner": self.winner,
            "natural": self.natural,
            "player_pair": self.player_pair,
            "banker_pair": self.banker_pair,
        }


def deal_round(draw: Callable[[], Card]) -> RoundResult:
    """카드를 규칙표대로 분배해서 한 판의 결과를 만든다."""
    p1, b1, p2, b2 = draw(), draw(), draw(), draw()
    player, banker = [p1, p2], [b1, b2]
    order = ["P", "B", "P", "B"]

    p_total = hand_total(c.value for c in player)
    b_total = hand_total(c.value for c in banker)

    if not (is_natural(p_total) or is_natural(b_total)):
        player_third = None
        if player_draws(p_total):
            card = draw()
            player.append(card)
            order.append("P")
            player_third = card.value
        if banker_draws(b_total, player_third):
            banker.append(draw())
            order.append("B")

    return RoundResult(tuple(player), tuple(banker), tuple(order))
