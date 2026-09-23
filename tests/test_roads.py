from dataclasses import dataclass

from engine.roads import BLUE, RED, big_road_columns, compute_roads, derived_colors, place


@dataclass
class R:
    winner: str
    player_pair: bool = False
    banker_pair: bool = False
    player_total: int = 0
    banker_total: int = 0


def seq(s):
    return [R(ch) for ch in s]


def test_big_road_columns_and_ties():
    cols = big_road_columns(seq("TBBTTPB"))
    assert [[c.winner for c in col] for col in cols] == [["B", "B"], ["P"], ["B"]]
    assert cols[0][0].ties == 1          # 첫 타이는 첫 칸에 붙음
    assert cols[0][1].ties == 2


def test_bead_road_wraps_every_6():
    roads = compute_roads(seq("BPBPBPT"))
    assert (roads.bead[5]["col"], roads.bead[5]["row"]) == (0, 5)
    assert (roads.bead[6]["col"], roads.bead[6]["row"]) == (1, 0)


def test_dragon_tail():
    cells = [(x, y) for x, y, _ in place([["B"] * 8, ["P"] * 6])]
    assert cells[:8] == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (1, 5), (2, 5)]
    # P열은 1열에서 시작해 row 4까지 내려가다가 (1,5)가 막혀 오른쪽으로 꺾인다
    assert cells[8:] == [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (2, 4)]


def test_derived_big_eye_example():
    # 원매: [B,B] [P] [B,B,B] [P,P]
    lengths = [len(c) for c in big_road_columns(seq("BBPBBBPP"))]
    assert lengths == [2, 1, 3, 2]
    assert derived_colors(lengths, 1) == [BLUE, BLUE, RED, BLUE, RED]


def test_derived_start_points():
    # 대안길: 2열 2행 또는 3열 1행에서 시작
    assert derived_colors([1, 1], 1) == []
    assert derived_colors([1, 2], 1) == [BLUE]   # 2열 2행: 1열은 1행에서 끝남 → 파랑
    assert derived_colors([1, 1, 1], 1) == [RED]  # 3열 1행: 1열과 2열 길이가 같음 → 빨강
    assert derived_colors([1, 1, 1], 2) == []     # 소안길은 3열 2행/4열 1행부터


def test_ask_prediction():
    roads = compute_roads(seq("BBPBBBPP"))
    assert roads.predict["B"]["big_eye"] == BLUE  # 새 열: 길이 2 vs 3
    assert roads.predict["P"]["big_eye"] == RED   # 이어짐: 2열 전 열에 3행 있음
