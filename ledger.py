"""베팅 기록 집계 (Streamlit과 무관한 순수 파이썬).

기록 한 건은 판이 끝날 때 app_pages/table.py 가 남기는 dict다:
    {"no", "time", "shoe", "round_no", "bets", "result", "settlements",
     "total_stake", "total_returned", "net", "balance_after"}
"""
from __future__ import annotations

from engine.bets import BET_LABELS, Bet

SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
WINNER_TEXT = {"P": "플레이어", "B": "뱅커", "T": "타이"}


def summarize(history: list[dict]) -> dict:
    """전체 요약 지표."""
    nets = [h["net"] for h in history]
    wagered = sum(h["total_stake"] for h in history)
    returned = sum(h["total_returned"] for h in history)
    return {
        "rounds": len(history),
        "wagered": wagered,
        "returned": returned,
        "net": returned - wagered,
        "won": sum(1 for n in nets if n > 0),
        "lost": sum(1 for n in nets if n < 0),
        "even": sum(1 for n in nets if n == 0),
        "best": max(nets, default=0),
        "worst": min(nets, default=0),
        # 베팅액 대비 손익 (환수율 - 1)
        "roi": (returned - wagered) / wagered if wagered else 0.0,
    }


def by_bet(history: list[dict]) -> list[dict]:
    """베팅 종류별 집계. 한 번도 걸지 않은 종류는 빠진다."""
    acc: dict[str, dict] = {}
    for h in history:
        for st in h["settlements"]:
            a = acc.setdefault(st["bet"], {"count": 0, "wins": 0, "stake": 0, "returned": 0})
            a["count"] += 1
            a["wins"] += st["outcome"] == "win"
            a["stake"] += st["stake"]
            a["returned"] += st["returned"]
    order = [b.value for b in Bet]
    return [
        {
            "bet": BET_LABELS[Bet(k)],
            "count": a["count"],
            "wins": a["wins"],
            "hit_rate": a["wins"] / a["count"],
            "stake": a["stake"],
            "returned": a["returned"],
            "net": a["returned"] - a["stake"],
        }
        for k, a in sorted(acc.items(), key=lambda kv: order.index(kv[0]))
    ]


def cards_text(cards: list[dict]) -> str:
    return " ".join(f"{c['rank']}{SUIT_SYMBOL[c['suit']]}" for c in cards)


def bets_text(bets: dict[str, int]) -> str:
    return " · ".join(f"{BET_LABELS[Bet(k)]} {v:,}" for k, v in bets.items())


def rows(history: list[dict]) -> list[dict]:
    """표·CSV용 행 (최근 판이 위)."""
    out = []
    for h in reversed(history):
        r = h["result"]
        out.append({
            "판": h["no"],
            "시각": h["time"],
            "슈": f"{h['shoe']}-{h['round_no']}",
            "베팅": bets_text(h["bets"]),
            "결과": f"{WINNER_TEXT[r['winner']]} {r['player_total']}:{r['banker_total']}",
            "플레이어 카드": cards_text(r["player"]),
            "뱅커 카드": cards_text(r["banker"]),
            "베팅액": h["total_stake"],
            "돌려받음": h["total_returned"],
            "손익": h["net"],
            "잔액": h["balance_after"],
        })
    return out
