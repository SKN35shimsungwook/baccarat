"""베팅 기록 집계 (Streamlit과 무관한 순수 파이썬). 바카라와 블랙잭 기록을 함께 다룬다.

기록 한 건은 판이 끝날 때 게임 페이지가 남기는 dict다. 공통 필드:
    {"no", "time", "game", "shoe", "round_no", "bets", "settlements",
     "total_stake", "total_returned", "net", "balance_after"}
- 바카라: "result" (engine.rules.RoundResult.to_dict)
- 블랙잭: "dealer", "seats" (bj.game.BJTable.round_record)
- 비행기: "crash", "cashouts", "fair" (crash.game.CrashTable.round_record)
- 사다리: "result", "code", "fair" (ladder.game.LadderTable._settle)
- 주사위: "dice", "sum", "fair" (dice.game.DiceTable.roll)
- 경마: "result", "order", "lanes", "fair" (horse.game.HorseTable.play)
"""
from __future__ import annotations

from engine.bets import BET_LABELS, Bet

SUIT_SYMBOL = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
WINNER_TEXT = {"P": "플레이어", "B": "뱅커", "T": "타이"}
GAME_TEXT = {"baccarat": "바카라", "blackjack": "블랙잭", "crash": "비행기", "ladder": "사다리", "dice": "주사위", "horse": "경마"}
BJ_RESULT_TEXT = {"blackjack": "블랙잭", "win": "승", "lose": "패", "push": "푸시", "surrender": "서렌더"}

# 베팅 종류 이름표 (표시 순서도 이 순서)
LABELS = {
    **{b.value: f"바카라 {BET_LABELS[b]}" for b in Bet},
    "bj_main": "블랙잭 메인",
    "bj_pp": "블랙잭 퍼펙트 페어",
    "bj_213": "블랙잭 21+3",
    "bj_ins": "블랙잭 인슈어런스",
    "crash_1": "비행기 베팅",
    "crash_2": "비행기 베팅 2",  # 베팅 2개를 쓰던 때의 기록 호환
    **{f"ld_{k}": f"사다리 {name}" for k, name in (
        ("left", "좌"), ("right", "우"), ("three", "3줄"), ("four", "4줄"), ("odd", "홀"), ("even", "짝"),
        ("L3E", "좌3짝"), ("L4O", "좌4홀"), ("R3O", "우3홀"), ("R4E", "우4짝"))},
    **{f"dc_{k}": f"주사위 {name}" for k, name in (
        ("odd", "홀"), ("even", "짝"), ("small", "소"), ("big", "대"), ("double", "더블"), ("triple", "트리플"))},
    **{f"hr_{k}": f"경마 {name}" for k, name in (("S", "강자"), ("A", "중간"), ("O", "복병"))},
}
ORDER = list(LABELS)


def game_of(h: dict) -> str:
    return h.get("game", "baccarat")  # 게임 필드가 생기기 전 바카라 기록 호환


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
    return [
        {
            "bet": LABELS.get(k, k),
            "count": a["count"],
            "wins": a["wins"],
            "hit_rate": a["wins"] / a["count"],
            "stake": a["stake"],
            "returned": a["returned"],
            "net": a["returned"] - a["stake"],
        }
        for k, a in sorted(acc.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else len(ORDER))
    ]


def cards_text(cards: list[dict]) -> str:
    return " ".join(f"{c['rank']}{SUIT_SYMBOL[c['suit']]}" for c in cards)


def bets_text(bets: dict[str, int]) -> str:
    return " · ".join(f"{LABELS.get(k, k).removeprefix('바카라 ').removeprefix('블랙잭 ').removeprefix('비행기 ').removeprefix('사다리 ').removeprefix('주사위 ').removeprefix('경마 ')} {v:,}"
                      for k, v in bets.items())


def _bj_hand_value(cards: list[dict]) -> int:
    total = sum(1 if c["rank"] == "A" else 10 if c["rank"] in ("10", "J", "Q", "K") else int(c["rank"])
                for c in cards)
    return total + 10 if any(c["rank"] == "A" for c in cards) and total + 10 <= 21 else total


def _describe(h: dict) -> tuple[str, str, str]:
    """(결과, 플레이어·자리 카드, 뱅커·딜러 카드)."""
    if game_of(h) == "horse":
        hits = [s["detail"] for s in h["settlements"] if s["outcome"] == "win"]
        return f"1위 {h['result']} · 순위 {'-'.join(map(str, h['order']))} · 적중 {', '.join(hits) if hits else '없음'}", "", ""
    if game_of(h) == "dice":
        d = h["dice"]
        kind = "트리플" if d[0] == d[1] == d[2] else ("홀" if h["sum"] % 2 else "짝")
        hits = [LABELS[s["bet"]].removeprefix("주사위 ") for s in h["settlements"] if s["outcome"] == "win"]
        return f"{'·'.join(map(str, d))} 합 {h['sum']} {kind} · 적중 {', '.join(hits) if hits else '없음'}", "", ""
    if game_of(h) == "ladder":
        hits = [LABELS[s["bet"]].removeprefix("사다리 ") for s in h["settlements"] if s["outcome"] == "win"]
        return f"{h['result']} · 적중 {', '.join(hits) if hits else '없음'}", "", ""
    if game_of(h) == "crash":
        parts = [f"{p}번 {m:.2f}x 멈춤" if m else f"{p}번 추락" for p, m in sorted(h["cashouts"].items())]
        return f"추락 {h['crash']:.2f}x · {', '.join(parts)}", "", ""
    if game_of(h) == "baccarat":
        r = h["result"]
        return (f"{WINNER_TEXT[r['winner']]} {r['player_total']}:{r['banker_total']}",
                cards_text(r["player"]), cards_text(r["banker"]))
    dealer_total = _bj_hand_value(h["dealer"])
    dealer = "딜러 블랙잭" if len(h["dealer"]) == 2 and dealer_total == 21 else (
        f"딜러 {dealer_total}" + (" 버스트" if dealer_total > 21 else ""))
    parts, hands = [], []
    for s in h["seats"]:
        for hi, hand in enumerate(s["hands"]):
            name = f"{s['index'] + 1}번" + (f"-{hi + 1}" if len(s["hands"]) > 1 else "")
            parts.append(f"{name} {BJ_RESULT_TEXT.get(hand['result'], hand['result'])}")
            hands.append(f"{name}: {cards_text(hand['cards'])}")
    return f"{dealer} · {', '.join(parts)}", " | ".join(hands), cards_text(h["dealer"])


def rows(history: list[dict]) -> list[dict]:
    """표·CSV용 행 (최근 판이 위)."""
    out = []
    for h in reversed(history):
        result, player_cards, dealer_cards = _describe(h)
        out.append({
            "판": h["no"],
            "시각": h["time"],
            "게임": GAME_TEXT[game_of(h)],
            "슈": f"#{h['round_no']}" if game_of(h) in ("crash", "ladder", "dice", "horse") else f"{h['shoe']}-{h['round_no']}",
            "베팅": bets_text(h["bets"]),
            "결과": result,
            "플레이어·자리 카드": player_cards,
            "뱅커·딜러 카드": dealer_cards,
            "베팅액": h["total_stake"],
            "돌려받음": h["total_returned"],
            "손익": h["net"],
            "잔액": h["balance_after"],
        })
    return out
