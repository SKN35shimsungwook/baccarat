"""출목표(Roadmaps): 주구로, 원매, 대안길/소안길/갑을길, 다음 판 예측(Ask).

좌표는 모두 (col, row), 0부터 시작, 격자 높이는 6행.
파생 도로 3종은 원매의 '논리적 열'(드래곤테일로 꺾이기 전 기준)로 계산한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .rules import BANKER, PLAYER, TIE

ROWS = 6
RED = "R"   # 규칙적(과거 흐름과 일치)
BLUE = "B"  # 불규칙(과거 흐름과 어긋남)

# 파생 도로 이름 → 비교 오프셋 k
DERIVED = {"big_eye": 1, "small": 2, "cockroach": 3}


@dataclass
class BigCell:
    winner: str                 # "B" 또는 "P"
    ties: int = 0               # 이 칸 뒤에 이어진 타이 수 (초록 사선)
    player_pair: bool = False
    banker_pair: bool = False


def bead_road(results: Sequence) -> list[dict]:
    """발생 순서대로 위→아래, 6칸이 차면 오른쪽 열로."""
    return [
        {"col": i // ROWS, "row": i % ROWS, "winner": r.winner,
         "player_pair": r.player_pair, "banker_pair": r.banker_pair,
         "total": r.player_total if r.winner == PLAYER else r.banker_total}
        for i, r in enumerate(results)
    ]


def big_road_columns(results: Sequence) -> list[list[BigCell]]:
    """원매의 논리적 열. 타이는 칸을 만들지 않고 직전 칸에 누적된다.

    결과가 타이로 시작하면 그 타이들은 첫 번째 칸에 붙인다.
    """
    columns: list[list[BigCell]] = []
    pending_ties = 0
    last: BigCell | None = None
    for r in results:
        if r.winner == TIE:
            if last is None:
                pending_ties += 1
            else:
                last.ties += 1
            continue
        cell = BigCell(r.winner, pending_ties, r.player_pair, r.banker_pair)
        pending_ties = 0
        if columns and columns[-1][0].winner == r.winner:
            columns[-1].append(cell)
        else:
            columns.append([cell])
        last = cell
    return columns


def place(columns: Sequence[Sequence], rows: int = ROWS) -> list[tuple[int, int, object]]:
    """논리적 열을 격자에 배치한다. 아래 칸이 막히면 오른쪽으로 꺾인다(드래곤테일)."""
    occupied: set[tuple[int, int]] = set()
    placed = []
    start = -1
    for column in columns:
        start += 1
        while (start, 0) in occupied:
            start += 1
        x, y = start, 0
        turned = False
        for i, item in enumerate(column):
            if i > 0:
                if not turned and y + 1 < rows and (x, y + 1) not in occupied:
                    y += 1
                else:
                    turned = True
                    x += 1
                    while (x, y) in occupied:
                        x += 1
            occupied.add((x, y))
            placed.append((x, y, item))
    return placed


def derived_colors(lengths: Sequence[int], k: int) -> list[str]:
    """원매 열 길이 목록으로 파생 도로 색 순서를 계산한다.

    - 새 열의 첫 칸(row 0): 직전 열과 k+1열 전의 길이가 같으면 빨강, 다르면 파랑.
    - 열이 이어지는 칸(row r≥1): k열 전 열에
        · row r 칸이 있으면 빨강
        · row r 칸은 없고 row r-1 칸이 마지막이면(길이 == r) 파랑
        · 둘 다 없으면(길이 < r) 빨강
    - 시작 지점: k열째의 2번째 칸, 또는 k+1열째의 첫 칸.
    """
    colors = []
    for c, length in enumerate(lengths):
        for r in range(length):
            if c < k or (c == k and r == 0):
                continue
            if r == 0:
                colors.append(RED if lengths[c - 1] == lengths[c - 1 - k] else BLUE)
            else:
                ref = lengths[c - k]
                colors.append(BLUE if ref == r else RED)
    return colors


def group_runs(items: Iterable[str]) -> list[list[str]]:
    """같은 값이 연속되는 구간을 한 열로 묶는다."""
    cols: list[list[str]] = []
    for it in items:
        if cols and cols[-1][0] == it:
            cols[-1].append(it)
        else:
            cols.append([it])
    return cols


@dataclass
class _Winner:
    """예측 계산용 가짜 결과 (winner만 필요)."""
    winner: str
    player_pair: bool = False
    banker_pair: bool = False


@dataclass
class Roads:
    bead: list[dict] = field(default_factory=list)
    big: list[dict] = field(default_factory=list)
    big_eye: list[dict] = field(default_factory=list)
    small: list[dict] = field(default_factory=list)
    cockroach: list[dict] = field(default_factory=list)
    predict: dict = field(default_factory=dict)  # {"B": {"big_eye": "R", ...}, "P": {...}}

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _derived_all(lengths: Sequence[int]) -> dict[str, list[str]]:
    return {name: derived_colors(lengths, k) for name, k in DERIVED.items()}


def compute_roads(results: Sequence) -> Roads:
    columns = big_road_columns(results)
    lengths = [len(c) for c in columns]
    derived = _derived_all(lengths)

    big = [
        {"col": x, "row": y, "winner": cell.winner, "ties": cell.ties,
         "player_pair": cell.player_pair, "banker_pair": cell.banker_pair}
        for x, y, cell in place(columns)
    ]
    roads = Roads(bead=bead_road(results), big=big)
    for name, colors in derived.items():
        setattr(roads, name, [{"col": x, "row": y, "color": c} for x, y, c in place(group_runs(colors))])

    # Ask: 다음 판이 B/P라면 각 파생 도로에 어떤 색이 찍히는지
    for side in (BANKER, PLAYER):
        nxt = big_road_columns(list(results) + [_Winner(side)])
        nd = _derived_all([len(c) for c in nxt])
        roads.predict[side] = {
            name: (nd[name][-1] if len(nd[name]) > len(derived[name]) else None) for name in DERIVED
        }
    return roads
