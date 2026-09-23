"""사다리 게임 엔진 (베팅형, 버튼으로 바로 추첨).

- 회차마다 출발(좌/우)과 가로줄 수(3/4)를 각각 1/2 확률로 뽑는다. 도착은 이 둘로 정해진다.
    좌3 → 짝, 좌4 → 홀, 우3 → 홀, 우4 → 짝   (아래 왼쪽 칸이 홀, 오른쪽 칸이 짝)
- 배당 = 환수율 ÷ 맞힐 확률 (단일 1/2, 조합 1/4).
- 진행: 베팅을 받은 뒤 서버가 바로 추첨·정산한다 (베팅이 확정된 뒤에 계산하므로 미리 알 수 없다).
- 공정성 검증: 회차마다 서버 시드를 새로 만들어 추첨 전에 SHA-256 해시를 보여 주고, 추첨 후 시드를 공개한다.
  결과 = HMAC-SHA256(서버 시드, "사용자 시드:회차 번호") 의 첫 바이트.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass, field

from wallet import Wallet

SIDE_TEXT = {"L": "좌", "R": "우"}
FINISH_TEXT = {"odd": "홀", "even": "짝"}

# 베팅 칸: 키 → (이름, 맞히는 조건, 확률)
BETS = {
    "left": ("좌", lambda r: r["side"] == "L", 0.5),
    "right": ("우", lambda r: r["side"] == "R", 0.5),
    "three": ("3줄", lambda r: r["lines"] == 3, 0.5),
    "four": ("4줄", lambda r: r["lines"] == 4, 0.5),
    "odd": ("홀", lambda r: r["finish"] == "odd", 0.5),
    "even": ("짝", lambda r: r["finish"] == "even", 0.5),
    "L3E": ("좌3짝", lambda r: r["code"] == "L3E", 0.25),
    "L4O": ("좌4홀", lambda r: r["code"] == "L4O", 0.25),
    "R3O": ("우3홀", lambda r: r["code"] == "R3O", 0.25),
    "R4E": ("우4짝", lambda r: r["code"] == "R4E", 0.25),
}
# 양방 베팅 금지: 정반대 쌍, 그리고 어떤 결과가 나와도 하나는 맞는 조합
OPPOSITE = (("left", "right"), ("three", "four"), ("odd", "even"))
HISTORY_KEEP = 200      # 결과 기록은 최근 200회차까지만


def finish_of(side: str, lines: int) -> str:
    """가로줄 수가 홀수면 반대쪽으로, 짝수면 같은 쪽으로 도착. 아래 왼쪽 = 홀, 오른쪽 = 짝."""
    ends_left = (side == "L") == (lines % 2 == 0)
    return "odd" if ends_left else "even"


def odds_for(rtp: float, prob: float) -> float:
    return math.floor(rtp / prob * 100 + 1e-9) / 100


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def draw(round_seed: str, client_seed: str, round_no: int) -> dict:
    """회차 결과. 첫 바이트의 비트 0 = 출발(0 좌 / 1 우), 비트 1 = 줄 수(0 → 3줄 / 1 → 4줄).
    이어지는 바이트로 가로줄 높이(화면 표시용)를 정한다."""
    digest = hmac.new(round_seed.encode(), f"{client_seed}:{round_no}".encode(), hashlib.sha256).digest()
    side = "R" if digest[0] & 1 else "L"
    lines = 4 if digest[0] & 2 else 3
    finish = finish_of(side, lines)
    # 가로줄 높이: 0.16 ~ 0.84 구간을 줄 수만큼 나눠 칸마다 하나씩 흔들어 놓는다 (겹치지 않게)
    heights = []
    span = 0.68 / lines
    for i in range(lines):
        jitter = digest[1 + i] / 255
        heights.append(round(0.16 + span * (i + 0.2 + 0.6 * jitter), 4))
    code = f"{side}{lines}{'O' if finish == 'odd' else 'E'}"
    return {"side": side, "lines": lines, "finish": finish, "code": code, "heights": heights,
            "text": f"{SIDE_TEXT[side]}{lines}{FINISH_TEXT[finish]}"}


# 나올 수 있는 결과 4가지 (좌3 · 좌4 · 우3 · 우4)
OUTCOMES = [
    {"side": side, "lines": lines, "finish": finish_of(side, lines),
     "code": f"{side}{lines}{'O' if finish_of(side, lines) == 'odd' else 'E'}"}
    for side in ("L", "R") for lines in (3, 4)
]


def hedge_error(keys) -> str | None:
    """양방 베팅이면 안내 문구, 아니면 None. keys = 한 회차에 건 베팅 종류 전부."""
    keys = set(keys)
    for a, b in OPPOSITE:
        if a in keys and b in keys:
            return f"{BETS[a][0]}·{BETS[b][0]} 양방 베팅은 할 수 없습니다."
    if keys and all(any(BETS[k][1](o) for k in keys) for o in OUTCOMES):
        return "어떤 결과가 나와도 맞는 조합(양방 베팅)은 걸 수 없습니다."
    return None


class LadderError(ValueError):
    pass


@dataclass
class LadderTable:
    wallet: Wallet
    rtp: float = 0.95
    min_bet: int = 1_000
    max_bet: int = 1_000_000
    client_seed: str = field(default_factory=lambda: secrets.token_hex(8))
    round: int = 0            # 마지막으로 추첨한 회차 번호
    results: list[dict] = field(default_factory=list)   # 추첨한 회차 (오래된 것부터)

    def __post_init__(self):
        self._next_seed()

    def _next_seed(self) -> None:
        self.server_seed = secrets.token_hex(32)
        self.commit = seed_hash(self.server_seed)  # 추첨 전에 공개하는 약속값

    # ── 설정 ────────────────────────────────────────────────────────
    def payouts(self) -> dict[str, float]:
        return {key: odds_for(self.rtp, prob) for key, (_, _, prob) in BETS.items()}

    def set_client_seed(self, seed: str) -> None:
        seed = seed.strip()
        if not seed:
            raise LadderError("시드를 입력하세요.")
        self.client_seed = seed

    # ── 베팅 → 추첨 → 정산 ──────────────────────────────────────────
    def play(self, bets: dict[str, int]) -> dict:
        """베팅을 받고 바로 추첨해 정산한다. 돌려주는 값은 기록(ledger 형식)."""
        clean = {key: int(v) for key, v in bets.items() if int(v or 0) > 0}
        if not clean:
            raise LadderError("베팅이 없습니다.")
        for key, v in clean.items():
            if key not in BETS:
                raise LadderError("없는 베팅입니다.")
            if not self.min_bet <= v <= self.max_bet:
                raise LadderError(f"{BETS[key][0]}: 베팅은 {self.min_bet:,} ~ {self.max_bet:,} 사이여야 합니다.")
        msg = hedge_error(clean)
        if msg:
            raise LadderError(msg)
        total = sum(clean.values())
        if total > self.wallet.balance:
            raise LadderError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")

        self.wallet.debit(total)
        self.round += 1
        k = self.round
        res = {"round": k, **draw(self.server_seed, self.client_seed, k), "seed": self.server_seed,
               "commit": self.commit, "client_seed": self.client_seed}
        self.results.append(res)
        self.results = self.results[-HISTORY_KEEP:]
        self._next_seed()
        odds = self.payouts()
        return self._settle(res, [{"key": key, "amount": v, "odds": odds[key]} for key, v in clean.items()])

    def _settle(self, res: dict, bets: list[dict]) -> dict:
        settlements = []
        for b in bets:
            win = BETS[b["key"]][1](res)
            returned = math.floor(b["amount"] * b["odds"]) if win else 0
            if returned:
                self.wallet.credit(returned)
            settlements.append({"bet": f"ld_{b['key']}", "stake": b["amount"], "returned": returned,
                                "outcome": "win" if win else "lose", "detail": f"{b['odds']:.2f}x"})
        stake = sum(s["stake"] for s in settlements)
        returned = sum(s["returned"] for s in settlements)
        return {
            "game": "ladder",
            "round_no": res["round"],
            "result": res["text"],
            "code": res["code"],
            "bets": {s["bet"]: s["stake"] for s in settlements},
            "settlements": settlements,
            "fair": {k: res[k] for k in ("seed", "commit", "client_seed")},
            "total_stake": stake,
            "total_returned": returned,
            "net": returned - stake,
            "balance_after": self.wallet.balance,
        }

    # ── 화면 ────────────────────────────────────────────────────────
    def stats(self, n: int = 50) -> dict:
        recent = self.results[-n:]
        total = len(recent) or 1
        count = lambda f: sum(1 for r in recent if f(r))  # noqa: E731
        return {
            "n": len(recent),
            "left": count(lambda r: r["side"] == "L") / total,
            "three": count(lambda r: r["lines"] == 3) / total,
            "odd": count(lambda r: r["finish"] == "odd") / total,
        }

    def to_view(self) -> dict:
        return {
            "round": self.round + 1,   # 다음에 추첨할 회차
            "commit": self.commit,
            "client_seed": self.client_seed,
            "rtp": self.rtp,
            "payouts": self.payouts(),
            "last": self.results[-1] if self.results else None,
            "recent": [{"round": r["round"], "text": r["text"], "code": r["code"], "finish": r["finish"]}
                       for r in self.results[-20:]][::-1],
            "finishes": [r["finish"] for r in self.results[-120:]],
            "stats": self.stats(),
        }
