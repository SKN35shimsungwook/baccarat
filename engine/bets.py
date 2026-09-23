"""베팅 종류, 배당, 정산.

배당은 '이익 배수'로 표현한다(원금 제외). 예: 뱅커 0.95 → 1000 걸고 이기면 1000 + 950을 돌려받음.
금액은 정수 칩 단위로 다루고, 소수점 이하 당첨금은 버린다(카지노 표준).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from .rules import BANKER, PLAYER, TIE, RoundResult


class Bet(str, Enum):
    PLAYER = "player"
    BANKER = "banker"
    TIE = "tie"
    PLAYER_PAIR = "player_pair"
    BANKER_PAIR = "banker_pair"
    TIGER = "tiger"  # 뱅커가 6점으로 승리

    @property
    def label(self) -> str:
        return BET_LABELS[self]


BET_LABELS = {
    Bet.PLAYER: "플레이어",
    Bet.BANKER: "뱅커",
    Bet.TIE: "타이",
    Bet.PLAYER_PAIR: "P 페어",
    Bet.BANKER_PAIR: "B 페어",
    Bet.TIGER: "타이거",
}

MAIN_BETS = (Bet.PLAYER, Bet.BANKER, Bet.TIE)
SIDE_BETS = (Bet.PLAYER_PAIR, Bet.BANKER_PAIR, Bet.TIGER)


@dataclass(frozen=True)
class TableRules:
    tie_payout: int = 8            # 8:1 (표준) 또는 9:1
    no_commission: bool = False    # True면 Super 6 방식: 뱅커 1:1, 단 6점 승리는 0.5:1
    pair_payout: int = 11
    tiger_two_card: int = 12       # 뱅커 2장으로 6점 승리
    tiger_three_card: int = 20     # 뱅커 3장으로 6점 승리
    min_bet: int = 1_000
    max_bet: int = 5_000_000
    side_max_bet: int = 500_000

    def banker_odds(self, result: RoundResult) -> Fraction:
        if self.no_commission:
            return Fraction(1, 2) if result.banker_total == 6 else Fraction(1)
        return Fraction(95, 100)


class Outcome(str, Enum):
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"


@dataclass(frozen=True)
class Settlement:
    bet: Bet
    stake: int
    outcome: Outcome
    returned: int  # 돌려받는 총액 (원금 포함). 지면 0, 무승부 환불이면 stake

    @property
    def net(self) -> int:
        return self.returned - self.stake

    def to_dict(self) -> dict:
        return {"bet": self.bet.value, "stake": self.stake, "outcome": self.outcome.value,
                "returned": self.returned, "net": self.net}


def odds_for(bet: Bet, result: RoundResult, rules: TableRules) -> Fraction | None:
    """이 베팅이 이겼으면 이익 배수, 환불이면 Fraction(0), 졌으면 None."""
    w = result.winner
    if bet is Bet.PLAYER:
        if w == PLAYER:
            return Fraction(1)
        return Fraction(0) if w == TIE else None
    if bet is Bet.BANKER:
        if w == BANKER:
            return rules.banker_odds(result)
        return Fraction(0) if w == TIE else None
    if bet is Bet.TIE:
        return Fraction(rules.tie_payout) if w == TIE else None
    if bet is Bet.PLAYER_PAIR:
        return Fraction(rules.pair_payout) if result.player_pair else None
    if bet is Bet.BANKER_PAIR:
        return Fraction(rules.pair_payout) if result.banker_pair else None
    if bet is Bet.TIGER:
        if w == BANKER and result.banker_total == 6:
            n = len(result.banker)
            return Fraction(rules.tiger_two_card if n == 2 else rules.tiger_three_card)
        return None
    raise ValueError(f"알 수 없는 베팅: {bet}")


def settle(bets: dict[Bet, int], result: RoundResult, rules: TableRules) -> list[Settlement]:
    out = []
    for bet, stake in bets.items():
        if stake <= 0:
            continue
        odds = odds_for(bet, result, rules)
        if odds is None:
            out.append(Settlement(bet, stake, Outcome.LOSE, 0))
        elif odds == 0:
            out.append(Settlement(bet, stake, Outcome.PUSH, stake))
        else:
            out.append(Settlement(bet, stake, Outcome.WIN, stake + math.floor(stake * odds)))
    return out


class BetError(ValueError):
    pass


def validate_bets(bets: dict[Bet, int], rules: TableRules, balance: int) -> None:
    """베팅 금액 검증. 문제가 있으면 BetError."""
    active = {b: s for b, s in bets.items() if s > 0}
    if not active:
        raise BetError("베팅이 없습니다.")
    if Bet.PLAYER in active and Bet.BANKER in active:
        raise BetError("플레이어와 뱅커에 동시에 걸 수 없습니다.")
    for bet, stake in active.items():
        if stake < rules.min_bet:
            raise BetError(f"{bet.label}: 최소 베팅은 {rules.min_bet:,}입니다.")
        limit = rules.max_bet if bet in MAIN_BETS else rules.side_max_bet
        if stake > limit:
            raise BetError(f"{bet.label}: 최대 베팅은 {limit:,}입니다.")
    total = sum(active.values())
    if total > balance:
        raise BetError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {balance:,})")
