"""블랙잭 카드, 슈, 핸드 점수.

- 카드 이미지·셔플은 바카라와 같은 engine.shoe 를 쓴다.
- 블랙잭 슈는 버닝 1장, 약 75% 지점에 컷 카드. 컷 카드가 나오면 다음 판 전에 새로 섞는다.
- 딜링된 카드마다 id(슈 안의 위치)를 붙여서, 화면이 새로 나온 카드만 애니메이션할 수 있게 한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from engine.shoe import Card, Shoe

TEN_RANKS = ("10", "J", "Q", "K")


def card_value(rank: str) -> int:
    """에이스는 11로 두고(핸드 계산에서 1로 내린다), 그림 카드는 10."""
    if rank == "A":
        return 11
    if rank in TEN_RANKS:
        return 10
    return int(rank)


@dataclass(frozen=True)
class BJCard:
    id: int
    card: Card

    @property
    def rank(self) -> str:
        return self.card.rank

    @property
    def suit(self) -> str:
        return self.card.suit

    @property
    def value(self) -> int:
        return card_value(self.rank)

    def to_dict(self) -> dict:
        return {"id": self.id, "rank": self.rank, "suit": self.suit}


def hand_value(cards) -> tuple[int, bool]:
    """(총점, 소프트 여부). 에이스를 모두 1로 센 뒤, 21을 넘지 않으면 한 장을 11로 올린다.

    리포트의 '모두 11로 가정 → 넘으면 10씩 차감'과 같은 결과다.
    """
    total = sum(1 if c.rank == "A" else card_value(c.rank) for c in cards)
    if any(c.rank == "A" for c in cards) and total + 10 <= 21:
        return total + 10, True
    return total, False


class BJShoe(Shoe):
    def __init__(self, decks: int = 6, penetration: float = 0.75, rng: random.Random | None = None,
                 shoe_no: int = 1):
        self.shoe_no = shoe_no  # 카드 id가 슈마다 겹치지 않게 앞자리에 붙인다
        super().__init__(decks=decks, cut_from_end=round(decks * 52 * (1 - penetration)), rng=rng)

    def _burn(self) -> None:
        # 블랙잭은 첫 장 한 장만 버린다
        self.burn_card = self.draw()
        self.burned = [self.burn_card]

    def deal(self) -> BJCard:
        card = self.draw()
        return BJCard(self.shoe_no * 1000 + self.dealt, card)
