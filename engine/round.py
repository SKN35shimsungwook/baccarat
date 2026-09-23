"""한 테이블의 게임 진행 (상태 머신).

BETTING → (베팅 마감/검증) → DEAL → THIRD_CARD → SETTLE → ROADMAP → BETTING
                                                               └ 컷 카드가 나왔으면 SHOE_END → 새 슈
승패와 정산은 전부 여기(서버)에서 결정되고, 화면은 결과를 받아서 보여주기만 한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from wallet import Wallet

from .bets import Bet, Settlement, TableRules, settle, validate_bets
from .roads import compute_roads
from .rules import RoundResult, deal_round
from .shoe import Shoe


class Phase(str, Enum):
    BETTING = "betting"
    SHOE_END = "shoe_end"


@dataclass
class RoundOutcome:
    round_no: int
    bets: dict[Bet, int]
    result: RoundResult
    settlements: list[Settlement]
    balance_after: int

    @property
    def total_stake(self) -> int:
        return sum(s.stake for s in self.settlements)

    @property
    def total_returned(self) -> int:
        return sum(s.returned for s in self.settlements)

    @property
    def net(self) -> int:
        return self.total_returned - self.total_stake

    def to_dict(self) -> dict:
        return {
            "round_no": self.round_no,
            "bets": {b.value: s for b, s in self.bets.items()},
            "result": self.result.to_dict(),
            "settlements": [s.to_dict() for s in self.settlements],
            "total_stake": self.total_stake,
            "total_returned": self.total_returned,
            "net": self.net,
            "balance_after": self.balance_after,
        }


@dataclass
class GameTable:
    wallet: Wallet
    rules: TableRules = field(default_factory=TableRules)
    decks: int = 8
    rng: random.Random | None = None  # 테스트용. None이면 CSPRNG
    shoe: Shoe = field(init=False)
    history: list[RoundResult] = field(init=False, default_factory=list)
    shoe_no: int = field(init=False, default=0)
    phase: Phase = field(init=False, default=Phase.BETTING)

    def __post_init__(self):
        self.new_shoe()

    def new_shoe(self) -> None:
        self.shoe = Shoe(decks=self.decks, rng=self.rng)
        self.history = []
        self.shoe_no += 1
        self.phase = Phase.BETTING

    def play_round(self, bets: dict[Bet, int]) -> RoundOutcome:
        """베팅을 받아 한 판을 끝까지 진행한다. 검증에 실패하면 BetError, 칩은 그대로."""
        if self.phase is Phase.SHOE_END:
            raise RuntimeError("슈가 끝났습니다. 새 슈를 시작하세요.")
        bets = {b: int(s) for b, s in bets.items() if s and s > 0}
        validate_bets(bets, self.rules, self.wallet.balance)

        self.wallet.debit(sum(bets.values()))                       # 베팅 마감: 칩 차감
        result = deal_round(self.shoe.draw)                          # 분배 + 3구
        settlements = settle(bets, result, self.rules)               # 정산
        self.wallet.credit(sum(s.returned for s in settlements))
        self.history.append(result)                                  # 출목표 기록

        if self.shoe.cut_reached:
            self.phase = Phase.SHOE_END
        return RoundOutcome(len(self.history), bets, result, settlements, self.wallet.balance)

    def roads(self):
        return compute_roads(self.history)

    def stats(self) -> dict:
        n = len(self.history)
        counts = {w: sum(1 for r in self.history if r.winner == w) for w in ("P", "B", "T")}
        return {
            "rounds": n,
            "counts": counts,
            "player_pairs": sum(r.player_pair for r in self.history),
            "banker_pairs": sum(r.banker_pair for r in self.history),
            "cards_remaining": self.shoe.remaining,
            "shoe_no": self.shoe_no,
        }
