"""사다리 게임 엔진 (베팅형, 자동 회차).

- 회차마다 출발(좌/우)과 가로줄 수(3/4)를 각각 1/2 확률로 뽑는다. 도착은 이 둘로 정해진다.
    좌3 → 짝, 좌4 → 홀, 우3 → 홀, 우4 → 짝   (아래 왼쪽 칸이 홀, 오른쪽 칸이 짝)
- 배당 = 환수율 ÷ 맞힐 확률 (단일 1/2, 조합 1/4). 베팅할 때의 배당으로 정산한다.
- 자동 회차: 서버 시계로 period 초마다 추첨. 추첨 lock 초 전부터는 베팅 마감.
  결과는 추첨 시각이 지난 뒤에만 계산하므로 화면(브라우저)에서도 미리 알 수 없다.
- 공정성 검증: 회차 시드 = HMAC(비밀 마스터 키, 회차 번호). 회차 전에 SHA-256 해시를 보여 주고,
  추첨 후 회차 시드를 공개한다. 결과 = HMAC(회차 시드, "사용자 시드:회차 번호") 의 첫 바이트.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
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
HISTORY_KEEP = 200      # 결과 기록은 최근 200회차까지만
CATCH_UP_LIMIT = 200    # 오래 비웠다 돌아오면 최근 회차만 계산


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


class LadderError(ValueError):
    pass


@dataclass
class LadderTable:
    wallet: Wallet
    rtp: float = 0.95
    period: int = 60          # 회차 간격(초)
    lock: int = 10            # 추첨 몇 초 전에 베팅 마감
    min_bet: int = 1_000
    max_bet: int = 1_000_000
    client_seed: str = field(default_factory=lambda: secrets.token_hex(8))
    epoch: float = field(default_factory=time.time)
    base: int = 0             # 간격을 바꿔도 회차 번호가 이어지도록 더하는 값
    results: list[dict] = field(default_factory=list)   # 추첨이 끝난 회차 (오래된 것부터)
    pending: dict[int, list[dict]] = field(default_factory=dict)  # 회차 → [{key, amount, odds}]

    def __post_init__(self):
        self._master = secrets.token_hex(32)  # 비밀 마스터 키 (공개하지 않는다)
        self.resolved_upto = self.round_at(self.epoch) - 1

    # ── 시간표 ──────────────────────────────────────────────────────
    def round_at(self, t: float) -> int:
        """t 시각에 베팅을 받고 있는(아직 추첨 전인) 회차 번호."""
        return self.base + int((t - self.epoch) // self.period) + 1

    def draw_time(self, k: int) -> float:
        return self.epoch + (k - self.base) * self.period

    def lock_time(self, k: int) -> float:
        return self.draw_time(k) - self.lock

    def round_seed(self, k: int) -> str:
        return hmac.new(self._master.encode(), f"round:{k}".encode(), hashlib.sha256).hexdigest()

    def commit(self, k: int) -> str:
        return seed_hash(self.round_seed(k))

    # ── 설정 ────────────────────────────────────────────────────────
    def payouts(self) -> dict[str, float]:
        return {key: odds_for(self.rtp, prob) for key, (_, _, prob) in BETS.items()}

    def set_period(self, period: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if period == self.period:
            return
        if any(self.pending.values()):
            raise LadderError("걸어 둔 베팅이 정산된 뒤에 간격을 바꿀 수 있습니다.")
        self.resolve(now)
        current = self.round_at(now)
        self.period = period
        self.epoch = now
        self.base = current - 1   # 지금 회차 번호를 그대로 두고, 추첨은 now + period 로

    def set_client_seed(self, seed: str) -> None:
        seed = seed.strip()
        if not seed:
            raise LadderError("시드를 입력하세요.")
        if any(self.pending.values()):
            raise LadderError("걸어 둔 베팅이 정산된 뒤에 시드를 바꿀 수 있습니다.")
        self.client_seed = seed

    # ── 베팅 ────────────────────────────────────────────────────────
    def place(self, bets: dict[str, int], now: float | None = None) -> int:
        """지금 베팅을 받는 회차에 건다. 돌려주는 값은 회차 번호."""
        now = time.time() if now is None else now
        k = self.round_at(now)
        if now >= self.lock_time(k):
            raise LadderError(f"{k}회차는 베팅이 마감되었습니다. 다음 회차에 걸어 주세요.")
        clean = {key: int(v) for key, v in bets.items() if int(v or 0) > 0}
        if not clean:
            raise LadderError("베팅이 없습니다.")
        for key, v in clean.items():
            if key not in BETS:
                raise LadderError("없는 베팅입니다.")
            already = sum(b["amount"] for b in self.pending.get(k, []) if b["key"] == key)
            if not self.min_bet <= v or already + v > self.max_bet:
                raise LadderError(f"{BETS[key][0]}: 베팅은 {self.min_bet:,} ~ {self.max_bet:,} 사이여야 합니다.")
        total = sum(clean.values())
        if total > self.wallet.balance:
            raise LadderError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")
        self.wallet.debit(total)
        odds = self.payouts()
        self.pending.setdefault(k, []).extend({"key": key, "amount": v, "odds": odds[key]} for key, v in clean.items())
        return k

    # ── 추첨 / 정산 ─────────────────────────────────────────────────
    def resolve(self, now: float | None = None) -> list[dict]:
        """추첨 시각이 지난 회차를 모두 추첨하고, 걸린 베팅을 정산한다. 정산한 회차 기록을 돌려준다."""
        now = time.time() if now is None else now
        last_done = self.round_at(now) - 1          # 추첨 시각이 지난 마지막 회차
        if last_done <= self.resolved_upto:
            return []
        start = max(self.resolved_upto + 1, last_done - CATCH_UP_LIMIT + 1)
        todo = set(range(start, last_done + 1)) | {k for k in self.pending if k <= last_done}
        settled = []
        for k in sorted(todo):
            seed = self.round_seed(k)
            res = {"round": k, **draw(seed, self.client_seed, k), "seed": seed, "commit": seed_hash(seed),
                   "client_seed": self.client_seed, "draw_at": self.draw_time(k)}
            if k >= start:
                self.results.append(res)
            bets = self.pending.pop(k, None)
            if bets:
                settled.append(self._settle(res, bets))
        self.results = self.results[-HISTORY_KEEP:]
        self.resolved_upto = last_done
        return settled

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

    def to_view(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        k = self.round_at(now)
        mine = {}
        for b in self.pending.get(k, []):
            mine[b["key"]] = mine.get(b["key"], 0) + b["amount"]
        last = self.results[-1] if self.results else None
        return {
            "now": now,
            "round": k,
            "draw_at": self.draw_time(k),
            "lock_at": self.lock_time(k),
            "period": self.period,
            "commit": self.commit(k),
            "client_seed": self.client_seed,
            "rtp": self.rtp,
            "payouts": self.payouts(),
            "mine": mine,   # 이번 회차에 확정한 베팅
            "waiting": {str(r): sum(b["amount"] for b in bs) for r, bs in self.pending.items() if r != k},
            "last": last,
            "recent": [{"round": r["round"], "text": r["text"], "code": r["code"], "finish": r["finish"]}
                       for r in self.results[-20:]][::-1],
            "finishes": [r["finish"] for r in self.results[-120:]],
            "stats": self.stats(),
        }
