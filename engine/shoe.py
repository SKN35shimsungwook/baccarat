"""카드와 슈(Shoe).

- 8덱(416장)을 암호학적으로 안전한 난수(secrets.SystemRandom)로 Fisher-Yates 셔플한다.
- 첫 장을 공개하고 그 점수만큼 버린다(버닝). 0점(10/J/Q/K)이면 10장을 버리는 것이 표준 규칙.
- 슈 끝에서 cut_from_end 번째 위치에 컷 카드를 둔다. 컷 카드가 나오면 진행 중인 판까지만 하고 슈를 마감한다.
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("S", "H", "D", "C")  # 스페이드, 하트, 다이아, 클럽


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        """바카라 점수. A=1, 2~9=숫자, 10/J/Q/K=0."""
        if self.rank == "A":
            return 1
        if self.rank in ("10", "J", "Q", "K"):
            return 0
        return int(self.rank)

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit, "value": self.value}


def fisher_yates(cards: list, rng: random.Random) -> None:
    """제자리(in-place) Fisher-Yates 셔플. 모든 순열이 같은 확률로 나온다."""
    for i in range(len(cards) - 1, 0, -1):
        j = rng.randrange(i + 1)
        cards[i], cards[j] = cards[j], cards[i]


class ShoeEmptyError(RuntimeError):
    pass


class Shoe:
    def __init__(self, decks: int = 8, cut_from_end: int = 16, rng: random.Random | None = None):
        # 테스트에서는 random.Random(seed)를 넣어 재현 가능하게 만든다.
        self._rng = rng or secrets.SystemRandom()
        self.decks = decks
        self.cards = [Card(r, s) for _ in range(decks) for s in SUITS for r in RANKS]
        fisher_yates(self.cards, self._rng)
        self._pos = 0
        self.cut_index = len(self.cards) - cut_from_end
        self.cut_reached = False
        self.burn_card: Card | None = None
        self.burned: list[Card] = []
        self._burn()

    def _burn(self) -> None:
        self.burn_card = self.draw()
        count = self.burn_card.value or 10
        self.burned = [self.draw() for _ in range(count)]

    def draw(self) -> Card:
        if self._pos >= len(self.cards):
            raise ShoeEmptyError("슈에 남은 카드가 없습니다.")
        card = self.cards[self._pos]
        self._pos += 1
        if self._pos > self.cut_index:
            self.cut_reached = True
        return card

    @property
    def remaining(self) -> int:
        return len(self.cards) - self._pos

    @property
    def dealt(self) -> int:
        return self._pos
