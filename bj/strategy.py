"""기본 전략(Basic Strategy) — 4~8덱, 스플릿 후 더블 허용, 딜러 피크, 늦은 서렌더 기준.

표의 각 문자열은 딜러 업카드 2,3,4,5,6,7,8,9,10,A 순서의 코드다.
    H 히트  S 스탠드  D 더블(안 되면 히트)  Ds 더블(안 되면 스탠드)
    P 스플릿  R 서렌더(안 되면 히트)  Rs 서렌더(안 되면 스탠드)  Rp 서렌더(안 되면 스플릿)
기본은 S17 표이고, H17일 때 달라지는 칸만 H17_* 로 덮어쓴다.
"""
from __future__ import annotations

from .cards import card_value, hand_value
from .rules import BJRules

UP = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")


def _row(s: str) -> list[str]:
    return s.split()


HARD = {
    **{t: _row("H H H H H H H H H H") for t in range(4, 9)},
    9: _row("H D D D D H H H H H"),
    10: _row("D D D D D D D D H H"),
    11: _row("D D D D D D D D D H"),
    12: _row("H H S S S H H H H H"),
    13: _row("S S S S S H H H H H"),
    14: _row("S S S S S H H H H H"),
    15: _row("S S S S S H H H R H"),
    16: _row("S S S S S H H R R R"),
    **{t: _row("S S S S S S S S S S") for t in range(17, 22)},
}
SOFT = {  # 소프트 총점
    12: _row("H H H H H H H H H H"),  # A,A 를 더 스플릿할 수 없을 때
    13: _row("H H H D D H H H H H"),
    14: _row("H H H D D H H H H H"),
    15: _row("H H D D D H H H H H"),
    16: _row("H H D D D H H H H H"),
    17: _row("H D D D D H H H H H"),
    18: _row("S Ds Ds Ds Ds S S H H H"),
    19: _row("S S S S S S S S S S"),
    20: _row("S S S S S S S S S S"),
    21: _row("S S S S S S S S S S"),
}
PAIRS = {  # 한 장의 값 (A=11)
    2: _row("P P P P P P H H H H"),
    3: _row("P P P P P P H H H H"),
    4: _row("H H H P P H H H H H"),
    6: _row("P P P P P H H H H H"),
    7: _row("P P P P P P H H H H"),
    8: _row("P P P P P P P P P P"),
    9: _row("P P P P P S P P S S"),
    11: _row("P P P P P P P P P P"),
    # 5,5 와 10,10 은 스플릿하지 않으므로 총점 표(하드 10 / 하드 20)를 따른다
}
# H17에서 달라지는 칸: (표, 키, 업카드) → 코드
H17_CHANGES = {
    ("hard", 11, "A"): "D",
    ("hard", 15, "A"): "R",
    ("hard", 17, "A"): "Rs",
    ("soft", 18, "2"): "Ds",
    ("soft", 19, "6"): "Ds",
    ("pair", 8, "A"): "Rp",
}

ACTION_LABEL = {"hit": "히트", "stand": "스탠드", "double": "더블", "split": "스플릿", "surrender": "서렌더"}


def _code(kind: str, key: int, up: str, rules: BJRules) -> str:
    table = {"hard": HARD, "soft": SOFT, "pair": PAIRS}[kind]
    if rules.h17 and (kind, key, up) in H17_CHANGES:
        return H17_CHANGES[(kind, key, up)]
    return table[key][UP.index(up)]


def up_key(rank: str) -> str:
    return "10" if card_value(rank) == 10 else rank


def raw_code(cards, dealer_up_rank: str, rules: BJRules, pair_allowed: bool = True) -> tuple[str, str, int]:
    """전략표에서 찾은 코드와 (표 종류, 키). 표를 화면에 그릴 때도 쓴다."""
    up = up_key(dealer_up_rank)
    if pair_allowed and len(cards) == 2 and card_value(cards[0].rank) == card_value(cards[1].rank):
        v = card_value(cards[0].rank)
        if v in PAIRS:
            code = _code("pair", v, up, rules)
            if code in ("P", "Rp"):
                return code, "pair", v
    total, soft = hand_value(cards)
    if soft and total >= 12:
        return _code("soft", total, up, rules), "soft", total
    return _code("hard", max(4, min(total, 21)), up, rules), "hard", total


def basic_action(cards, dealer_up_rank: str, rules: BJRules, *, can_double: bool, can_split: bool,
                 can_surrender: bool) -> str:
    """지금 할 수 있는 행동 중 기본 전략이 권하는 것: hit / stand / double / split / surrender."""
    code, _, _ = raw_code(cards, dealer_up_rank, rules, pair_allowed=can_split)
    if code == "P":
        return "split"
    if code == "Rp":
        return "surrender" if can_surrender else "split"
    if code == "R":
        return "surrender" if can_surrender else "hit"
    if code == "Rs":
        return "surrender" if can_surrender else "stand"
    if code == "D":
        return "double" if can_double else "hit"
    if code == "Ds":
        return "double" if can_double else "stand"
    return "hit" if code == "H" else "stand"


def chart(rules: BJRules) -> dict[str, tuple[list[str], list[list[str]]]]:
    """화면에 그릴 전략표: {"hard"|"soft"|"pairs": (행 이름들, 행마다 업카드별 코드)}.

    서렌더가 없는 규칙이면 R→H, Rs→S, Rp→P 로 바꿔 보여 준다.
    """
    from engine.shoe import Card

    from .cards import BJCard

    def code_for(ranks):
        cards = [BJCard(i, Card(r, "S")) for i, r in enumerate(ranks)]
        row = []
        for up in UP:
            code, _, _ = raw_code(cards, up, rules)
            if not rules.surrender:
                code = {"R": "H", "Rs": "S", "Rp": "P"}.get(code, code)
            row.append(code)
        return row

    hard_rows = [("8 이하", ("2", "6")), *[(str(t), ("10", str(t - 10)) if t >= 12 else ("2", str(t - 2)))
                                          for t in range(9, 17)], ("17 이상", ("10", "7"))]
    soft_rows = [(f"A,{k}", ("A", str(k))) for k in range(2, 10)]
    pair_rows = [(f"{r},{r}", (r, r)) for r in ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")]
    return {
        name: ([label for label, _ in rows], [code_for(ranks) for _, ranks in rows])
        for name, rows in (("hard", hard_rows), ("soft", soft_rows), ("pairs", pair_rows))
    }
