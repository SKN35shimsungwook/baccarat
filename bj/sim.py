"""기본 전략 자동 플레이로 하우스 엣지를 추정하는 몬테카를로 시뮬레이션.

실제 게임과 같은 BJTable 엔진을 그대로 쓰고, 매 결정을 bj.strategy.basic_action 으로 내린다.
하우스 엣지 = -(판당 평균 손익) / 처음 건 금액. 인슈어런스·사이드 베팅은 하지 않는다.
"""
from __future__ import annotations

import math
import random
from typing import Callable

from wallet import SessionWallet

from .game import BJTable, Phase
from .rules import BJRules

UNIT = 1_000  # 3:2·6:5·서렌더 계산에서 버림 오차가 없는 단위 (테이블 최소 베팅)


def simulate(rules: BJRules, rounds: int, seed: int | None = None,
             progress: Callable[[float], None] | None = None) -> dict:
    table = BJTable(SessionWallet({}, initial=10**15), rules, rng=random.Random(seed))
    total = sq = 0
    wins = pushes = losses = blackjacks = 0
    step = max(1, rounds // 50)
    for i in range(rounds):
        table.start_round({0: {"main": UNIT}})
        if table.phase is Phase.INSURANCE:
            table.insure({})
        while table.phase is Phase.PLAYER:
            table.act(table.hint())
        net = table.round_returned - table.round_stake
        total += net
        sq += net * net
        wins += net > 0
        pushes += net == 0
        losses += net < 0
        blackjacks += any(h.result == "blackjack" for s in table.seats for h in s.hands)
        if progress and i % step == 0:
            progress(i / rounds)
    mean = total / rounds
    var = sq / rounds - mean * mean
    se = math.sqrt(var / rounds)
    return {
        "rounds": rounds,
        "edge": -mean / UNIT,
        "ci95": 1.96 * se / UNIT,
        "win": wins / rounds,
        "push": pushes / rounds,
        "lose": losses / rounds,
        "blackjack": blackjacks / rounds,
    }
