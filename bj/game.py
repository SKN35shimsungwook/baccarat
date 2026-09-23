"""블랙잭 테이블 상태 머신 (최대 3자리).

BETTING → 분배(+사이드 베팅 정산) → [INSURANCE] → 딜러 피크 → PLAYER(자리·손 차례대로) → 딜러 → 정산 → DONE

- 승패와 정산은 전부 여기서 결정한다. 화면에는 to_view() 로 공개된 정보만 보낸다
  (딜러 홀카드는 공개 전까지 id만 보낸다).
- 칩은 걸 때(베팅·더블·스플릿·인슈어런스) 바로 차감하고, 정산할 때 돌려준다.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum

from wallet import Wallet

from .cards import BJCard, BJShoe, card_value, hand_value
from .rules import (PERFECT_PAIRS, PERFECT_PAIRS_LABEL, TWENTY_ONE_3, TWENTY_ONE_3_LABEL, BJRules,
                    perfect_pairs, twenty_one_3)
from .strategy import basic_action

SEATS = 3
HI_LO = {**{r: 1 for r in ("2", "3", "4", "5", "6")}, **{r: 0 for r in ("7", "8", "9")},
         **{r: -1 for r in ("10", "J", "Q", "K", "A")}}
BET_KEYS = ("main", "pp", "t213")


class Phase(str, Enum):
    BETTING = "betting"
    INSURANCE = "insurance"
    PLAYER = "player"
    DONE = "done"


class BJError(ValueError):
    pass


@dataclass
class Hand:
    cards: list[BJCard]
    bet: int
    doubled: bool = False
    from_split: bool = False
    split_aces: bool = False
    done: bool = False
    surrendered: bool = False
    result: str | None = None      # blackjack / win / push / lose / surrender
    returned: int = 0

    @property
    def total(self) -> int:
        return hand_value(self.cards)[0]

    @property
    def soft(self) -> bool:
        return hand_value(self.cards)[1]

    @property
    def is_bust(self) -> bool:
        return self.total > 21

    @property
    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and self.total == 21 and not self.from_split

    def to_dict(self) -> dict:
        return {
            "cards": [c.to_dict() for c in self.cards], "total": self.total, "soft": self.soft,
            "bet": self.bet, "doubled": self.doubled, "done": self.done, "surrendered": self.surrendered,
            "blackjack": self.is_blackjack, "bust": self.is_bust, "result": self.result, "returned": self.returned,
        }


@dataclass
class Seat:
    index: int
    main: int
    pp: int = 0
    t213: int = 0
    hands: list[Hand] = field(default_factory=list)
    insurance: int | None = None   # None: 해당 없음/미결정, 0: 거절, >0: 건 금액
    side: list[dict] = field(default_factory=list)


class BJTable:
    def __init__(self, wallet: Wallet, rules: BJRules | None = None, rng: random.Random | None = None):
        self.wallet = wallet
        self.rules = rules or BJRules()
        self.rng = rng
        self.shoe_no = 0
        self.phase = Phase.BETTING
        self.seats: list[Seat] = []
        self.dealer: list[BJCard] = []
        self.hole_revealed = False
        self.active: tuple[int, int] | None = None
        self.settlements: list[dict] = []
        self.round_stake = 0
        self.round_returned = 0
        self.new_shoe()

    # ── 슈 / 카운트 ─────────────────────────────────────────────────
    def new_shoe(self) -> None:
        if self.phase in (Phase.INSURANCE, Phase.PLAYER):
            raise BJError("판이 끝난 뒤에 슈를 바꿀 수 있습니다.")
        self.shoe_no += 1
        self.shoe = BJShoe(self.rules.decks, self.rules.penetration, self.rng, self.shoe_no)
        self.seen: list[BJCard] = []
        self.round_no = 0

    def _deal(self, visible: bool = True) -> BJCard:
        card = self.shoe.deal()
        if visible:
            self.seen.append(card)
        return card

    def count(self) -> dict:
        """하이로 카운트. 공개된 카드만 센다 (공개 전 홀카드는 남은 카드로 친다)."""
        rc = sum(HI_LO[c.rank] for c in self.seen)
        unseen = self.shoe.remaining + (1 if self.dealer and not self.hole_revealed else 0)
        decks_left = max(unseen / 52, 0.25)
        return {"rc": rc, "tc": round(rc / decks_left, 1), "decks_left": round(decks_left, 1)}

    # ── 판 시작 ─────────────────────────────────────────────────────
    def _debit(self, amount: int) -> None:
        self.wallet.debit(amount)
        self.round_stake += amount

    def _credit(self, amount: int) -> None:
        if amount:
            self.wallet.credit(amount)
        self.round_returned += amount

    def validate_bets(self, bets: dict[int, dict[str, int]]) -> dict[int, dict[str, int]]:
        r = self.rules
        clean: dict[int, dict[str, int]] = {}
        for seat, b in bets.items():
            seat = int(seat)
            if not 0 <= seat < SEATS:
                raise BJError("없는 자리입니다.")
            b = {k: int(b.get(k, 0) or 0) for k in BET_KEYS}
            if not any(b.values()):
                continue
            if b["main"] <= 0:
                raise BJError(f"{seat + 1}번 자리: 사이드 베팅은 메인 베팅이 있어야 합니다.")
            for k, v in b.items():
                if v and v < r.min_bet:
                    raise BJError(f"{seat + 1}번 자리: 최소 베팅은 {r.min_bet:,}입니다.")
                limit = r.max_bet if k == "main" else r.side_max_bet
                if v > limit:
                    raise BJError(f"{seat + 1}번 자리: 최대 베팅은 {limit:,}입니다.")
            clean[seat] = b
        if not clean:
            raise BJError("베팅이 없습니다.")
        total = sum(sum(b.values()) for b in clean.values())
        if total > self.wallet.balance:
            raise BJError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")
        return dict(sorted(clean.items()))

    def start_round(self, bets: dict[int, dict[str, int]]) -> None:
        if self.phase in (Phase.INSURANCE, Phase.PLAYER):
            raise BJError("진행 중인 판이 있습니다.")
        clean = self.validate_bets(bets)
        if self.shoe.cut_reached:
            self.new_shoe()  # 컷 카드가 나왔으면 다음 판 전에 새로 섞는다
        self.round_no += 1
        self.settlements = []
        self.round_stake = 0
        self.round_returned = 0
        self._debit(sum(sum(b.values()) for b in clean.values()))
        self.seats = [Seat(i, b["main"], b["pp"], b["t213"], [Hand([], b["main"])]) for i, b in clean.items()]
        self.dealer = []
        self.hole_revealed = False
        self.active = None

        # 자리마다 한 장 → 딜러 업카드 → 자리마다 한 장 → 딜러 홀카드(비공개)
        for s in self.seats:
            s.hands[0].cards.append(self._deal())
        self.dealer.append(self._deal())
        for s in self.seats:
            s.hands[0].cards.append(self._deal())
        self.dealer.append(self._deal(visible=False))

        self._settle_side_bets()
        if self.rules.insurance and self.dealer[0].rank == "A":
            self.phase = Phase.INSURANCE
            return
        self._after_insurance()

    def _settle_side_bets(self) -> None:
        up = self.dealer[0]
        for s in self.seats:
            c1, c2 = s.hands[0].cards
            for key, stake, kind, table, labels in (
                ("bj_pp", s.pp, perfect_pairs(c1, c2), PERFECT_PAIRS, PERFECT_PAIRS_LABEL),
                ("bj_213", s.t213, twenty_one_3(c1, c2, up), TWENTY_ONE_3, TWENTY_ONE_3_LABEL),
            ):
                if not stake:
                    continue
                returned = stake * (table[kind] + 1) if kind else 0
                self._credit(returned)
                entry = {"seat": s.index, "bet": key, "stake": stake, "returned": returned,
                         "outcome": "win" if kind else "lose", "detail": labels[kind] if kind else None}
                s.side.append(entry)
                self.settlements.append(entry)

    # ── 인슈어런스 / 딜러 피크 ─────────────────────────────────────
    def insure(self, decisions: dict[int, bool]) -> None:
        if self.phase is not Phase.INSURANCE:
            raise BJError("지금은 인슈어런스를 걸 수 없습니다.")
        cost = {s.index: s.main // 2 for s in self.seats if decisions.get(s.index)}
        if sum(cost.values()) > self.wallet.balance:
            raise BJError("인슈어런스를 걸 칩이 부족합니다.")
        for s in self.seats:
            s.insurance = cost.get(s.index, 0)
            if s.insurance:
                self._debit(s.insurance)
        self._after_insurance()

    def _after_insurance(self) -> None:
        dealer_bj = hand_value(self.dealer)[0] == 21
        peek = card_value(self.dealer[0].rank) in (10, 11)
        for s in self.seats:
            if s.insurance:
                returned = s.insurance * 3 if dealer_bj else 0
                self._credit(returned)
                self.settlements.append({"seat": s.index, "bet": "bj_ins", "stake": s.insurance,
                                         "returned": returned, "outcome": "win" if dealer_bj else "lose",
                                         "detail": None})
        if peek and dealer_bj:
            # 딜러 블랙잭: 바로 공개하고 정산 (플레이어 블랙잭은 무승부)
            self._reveal_hole()
            self._settle()
            return
        for s in self.seats:
            if s.hands[0].is_blackjack:
                s.hands[0].done = True
        self.phase = Phase.PLAYER
        self._advance()

    def _reveal_hole(self) -> None:
        if not self.hole_revealed:
            self.hole_revealed = True
            self.seen.append(self.dealer[1])

    # ── 플레이어 차례 ───────────────────────────────────────────────
    def _advance(self) -> None:
        """다음에 결정할 손으로 넘어간다. 스플릿으로 한 장만 남은 손은 먼저 한 장 받는다."""
        for si, s in enumerate(self.seats):
            for hi, h in enumerate(s.hands):
                if h.done:
                    continue
                if len(h.cards) == 1:
                    h.cards.append(self._deal())
                    if h.split_aces and not (self.rules.resplit_aces and h.cards[1].rank == "A"
                                             and len(s.hands) < self.rules.max_hands):
                        h.done = True  # 에이스 스플릿은 한 장씩만
                        continue
                if h.total >= 21:
                    h.done = True
                    continue
                self.active = (si, hi)
                return
        self.active = None
        self._dealer_play()
        self._settle()

    def current(self) -> tuple[Seat, Hand] | None:
        if self.phase is not Phase.PLAYER or self.active is None:
            return None
        s = self.seats[self.active[0]]
        return s, s.hands[self.active[1]]

    def legal(self) -> list[str]:
        cur = self.current()
        if not cur:
            return []
        s, h = cur
        r = self.rules
        acts = ["hit", "stand"]
        two = len(h.cards) == 2
        if two and not h.split_aces and (not h.from_split or r.das) and self.wallet.balance >= h.bet:
            acts.append("double")
        if (two and card_value(h.cards[0].rank) == card_value(h.cards[1].rank)
                and len(s.hands) < r.max_hands and self.wallet.balance >= h.bet
                and (not h.split_aces or r.resplit_aces)):
            acts.append("split")
        if r.surrender and two and len(s.hands) == 1 and not h.from_split:
            acts.append("surrender")
        return acts

    def act(self, action: str) -> None:
        if action not in self.legal():
            raise BJError("지금 할 수 없는 행동입니다.")
        s, h = self.current()
        if action == "hit":
            h.cards.append(self._deal())
            if h.total >= 21:
                h.done = True
        elif action == "stand":
            h.done = True
        elif action == "double":
            self._debit(h.bet)
            h.bet *= 2
            h.doubled = True
            h.cards.append(self._deal())
            h.done = True
        elif action == "split":
            self._debit(h.bet)
            aces = h.cards[0].rank == "A"
            moved = h.cards.pop()
            h.from_split = True
            h.split_aces = aces
            s.hands.insert(self.active[1] + 1, Hand([moved], h.bet, from_split=True, split_aces=aces))
        elif action == "surrender":
            h.surrendered = True
            h.done = True
        self._advance()

    # ── 딜러 / 정산 ────────────────────────────────────────────────
    def _dealer_play(self) -> None:
        self._reveal_hole()
        live = any(not (h.is_bust or h.surrendered or h.is_blackjack) for s in self.seats for h in s.hands)
        if not live:
            return
        while True:
            total, soft = hand_value(self.dealer)
            if total < 17 or (self.rules.h17 and total == 17 and soft):
                self.dealer.append(self._deal())
            else:
                return

    def _settle(self) -> None:
        dealer_total = hand_value(self.dealer)[0]
        dealer_bj = len(self.dealer) == 2 and dealer_total == 21
        for s in self.seats:
            for hi, h in enumerate(s.hands):
                if h.surrendered:
                    h.result, h.returned = "surrender", h.bet // 2
                elif h.is_bust:
                    h.result, h.returned = "lose", 0
                elif h.is_blackjack:
                    if dealer_bj:
                        h.result, h.returned = "push", h.bet
                    else:
                        h.result = "blackjack"
                        h.returned = h.bet + math.floor(h.bet * self.rules.blackjack_payout)
                elif dealer_bj:
                    h.result, h.returned = "lose", 0
                elif dealer_total > 21 or h.total > dealer_total:
                    h.result, h.returned = "win", h.bet * 2
                elif h.total == dealer_total:
                    h.result, h.returned = "push", h.bet
                else:
                    h.result, h.returned = "lose", 0
                h.done = True
                self._credit(h.returned)
                self.settlements.append({
                    "seat": s.index, "hand": hi, "bet": "bj_main", "stake": h.bet, "returned": h.returned,
                    "outcome": {"blackjack": "win", "surrender": "lose"}.get(h.result, h.result),
                    "detail": h.result,
                })
        self.active = None
        self.phase = Phase.DONE

    # ── 화면 / 기록 ─────────────────────────────────────────────────
    def hint(self) -> str | None:
        cur = self.current()
        if self.phase is Phase.INSURANCE:
            return "decline"  # 기본 전략은 인슈어런스를 걸지 않는다
        if not cur:
            return None
        _, h = cur
        legal = self.legal()
        return basic_action(h.cards, self.dealer[0].rank, self.rules, can_double="double" in legal,
                            can_split="split" in legal, can_surrender="surrender" in legal)

    def dealer_view(self) -> dict:
        shown = self.dealer if self.hole_revealed else self.dealer[:1]
        total, soft = hand_value(shown) if shown else (0, False)
        cards = [c.to_dict() for c in shown]
        if self.dealer and not self.hole_revealed:
            cards.append({"id": self.dealer[1].id, "hidden": True})
        return {"cards": cards, "total": total, "soft": soft,
                "blackjack": self.hole_revealed and len(self.dealer) == 2 and total == 21,
                "bust": total > 21, "revealed": self.hole_revealed}

    def to_view(self, hint: bool = False) -> dict:
        return {
            "phase": self.phase.value,
            "shoe_no": self.shoe_no,
            "round_no": self.round_no,
            "cards_remaining": self.shoe.remaining,
            "dealer": self.dealer_view(),
            "seats": [{
                "index": s.index, "main": s.main, "pp": s.pp, "t213": s.t213, "insurance": s.insurance,
                "hands": [h.to_dict() for h in s.hands], "side": s.side,
            } for s in self.seats],
            "active": {"seat": self.seats[self.active[0]].index, "hand": self.active[1]} if self.active else None,
            "legal": self.legal(),
            "hint": self.hint() if hint else None,
            "insurance_cost": {s.index: s.main // 2 for s in self.seats} if self.phase is Phase.INSURANCE else None,
            "count": self.count(),
            "round": {"stake": self.round_stake, "returned": self.round_returned,
                      "net": self.round_returned - self.round_stake} if self.phase is Phase.DONE else None,
        }

    def round_record(self) -> dict:
        """베팅 기록(ledger)에 남길 한 판. phase가 DONE일 때만."""
        assert self.phase is Phase.DONE
        bets: dict[str, int] = {}
        for e in self.settlements:
            bets[e["bet"]] = bets.get(e["bet"], 0) + e["stake"]
        return {
            "game": "blackjack",
            "bets": bets,
            "settlements": self.settlements,
            "dealer": [c.to_dict() for c in self.dealer],
            "seats": [{"index": s.index, "hands": [h.to_dict() for h in s.hands]} for s in self.seats],
            "total_stake": self.round_stake,
            "total_returned": self.round_returned,
            "net": self.round_returned - self.round_stake,
            "balance_after": self.wallet.balance,
            "round_no": self.round_no,
        }
