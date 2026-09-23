"""주사위 홀짝 게임 엔진 (주사위 3개 · 식보 방식, 버튼으로 바로 굴림).

- 합계(3~18)로 판정.
  홀/짝 · 소(4~10)/대(11~17): 세 개가 모두 같은 눈(트리플)이면 모두 진다 (식보 규칙).
  더블(같은 눈 2개 이상), 트리플(세 개 모두 같은 눈).
- 배당 = 환수율 ÷ 맞힐 확률 (소수 둘째 자리 내림). 어떤 베팅이든 기대 환수 ≈ 환수율.
- 공정성 검증: 판마다 서버 시드를 새로 만들고 굴리기 전에 SHA-256 해시를 보여 준다.
  주사위 = HMAC-SHA256(서버 시드, "사용자 시드:판 번호:카운터") 의 바이트를 편향 없이 1~6으로 바꾼 값.
  굴린 뒤 서버 시드를 공개한다.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product

from wallet import Wallet


def _triple(d) -> bool:
    return d[0] == d[1] == d[2]


# 베팅 칸: 키 → (이름, 이기는 조건(주사위 3개))
BETS: dict[str, tuple[str, callable]] = {
    "odd": ("홀", lambda d: sum(d) % 2 == 1 and not _triple(d)),
    "even": ("짝", lambda d: sum(d) % 2 == 0 and not _triple(d)),
    "small": ("소", lambda d: 4 <= sum(d) <= 10 and not _triple(d)),
    "big": ("대", lambda d: 11 <= sum(d) <= 17 and not _triple(d)),
    "double": ("더블", lambda d: len(set(d)) < 3),
    "triple": ("트리플", _triple),
}
ALL_ROLLS = list(product(range(1, 7), repeat=3))
# 양방 베팅 금지: 정반대 쌍, 그리고 어떤 눈이 나와도 하나는 맞는 조합
OPPOSITE = (("odd", "even"), ("small", "big"))
RECENT_KEEP = 200


def probability(key: str) -> Fraction:
    win = BETS[key][1]
    return Fraction(sum(1 for d in ALL_ROLLS if win(d)), len(ALL_ROLLS))


def odds_for(rtp: float, key: str) -> float:
    return math.floor(rtp / float(probability(key)) * 100 + 1e-9) / 100


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def roll_dice(server_seed: str, client_seed: str, nonce: int) -> tuple[int, int, int]:
    """바이트 값 0~251 만 써서 (252 = 6 × 42) 1~6 이 정확히 같은 확률이 되게 한다."""
    counter = 0
    faces: list[int] = []
    while True:
        digest = hmac.new(server_seed.encode(), f"{client_seed}:{nonce}:{counter}".encode(), hashlib.sha256).digest()
        for byte in digest:
            if byte < 252:
                faces.append(byte % 6 + 1)
                if len(faces) == 3:
                    return faces[0], faces[1], faces[2]
        counter += 1


def describe(dice) -> dict:
    total = sum(dice)
    triple = _triple(dice)
    return {
        "sum": total,
        "triple": triple,
        "parity": "triple" if triple else ("odd" if total % 2 else "even"),
        "size": "triple" if triple else ("small" if total <= 10 else "big"),
    }


def hedge_error(keys) -> str | None:
    """양방 베팅이면 안내 문구, 아니면 None."""
    keys = set(keys)
    for a, b in OPPOSITE:
        if a in keys and b in keys:
            return f"{BETS[a][0]}·{BETS[b][0]} 양방 베팅은 할 수 없습니다."
    if keys and all(any(BETS[k][1](d) for k in keys) for d in ALL_ROLLS):
        return "어떤 결과가 나와도 맞는 조합(양방 베팅)은 걸 수 없습니다."
    return None


class DiceError(ValueError):
    pass


@dataclass
class DiceTable:
    wallet: Wallet
    rtp: float = 0.95
    min_bet: int = 1_000
    max_bet: int = 1_000_000
    client_seed: str = field(default_factory=lambda: secrets.token_hex(8))
    nonce: int = 0
    results: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self._next_seed()

    def _next_seed(self) -> None:
        self.server_seed = secrets.token_hex(32)
        self.commit = seed_hash(self.server_seed)  # 굴리기 전에 공개하는 약속값

    def payouts(self) -> dict[str, float]:
        return {key: odds_for(self.rtp, key) for key in BETS}

    def set_client_seed(self, seed: str) -> None:
        seed = seed.strip()
        if not seed:
            raise DiceError("시드를 입력하세요.")
        self.client_seed = seed

    def roll(self, bets: dict[str, int]) -> dict:
        """베팅을 받고 바로 굴려 정산한다. 돌려주는 값은 기록(ledger 형식)."""
        clean = {k: int(v) for k, v in bets.items() if int(v or 0) > 0}
        if not clean:
            raise DiceError("베팅이 없습니다.")
        for key, v in clean.items():
            if key not in BETS:
                raise DiceError("없는 베팅입니다.")
            if not self.min_bet <= v <= self.max_bet:
                raise DiceError(f"{BETS[key][0]}: 베팅은 {self.min_bet:,} ~ {self.max_bet:,} 사이여야 합니다.")
        msg = hedge_error(clean)
        if msg:
            raise DiceError(msg)
        total = sum(clean.values())
        if total > self.wallet.balance:
            raise DiceError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")

        self.wallet.debit(total)
        self.nonce += 1
        dice = roll_dice(self.server_seed, self.client_seed, self.nonce)
        odds = self.payouts()
        settlements = []
        for key, stake in clean.items():
            win = BETS[key][1](dice)
            returned = math.floor(stake * odds[key]) if win else 0
            if returned:
                self.wallet.credit(returned)
            settlements.append({"bet": f"dc_{key}", "stake": stake, "returned": returned,
                                "outcome": "win" if win else "lose", "detail": f"{odds[key]:.2f}x"})
        res = {"nonce": self.nonce, "dice": list(dice), **describe(dice),
               "server_seed": self.server_seed, "commit": self.commit, "client_seed": self.client_seed}
        self.results.append(res)
        self.results = self.results[-RECENT_KEEP:]
        self._next_seed()
        returned = sum(s["returned"] for s in settlements)
        return {
            "game": "dice",
            "round_no": self.nonce,
            "dice": list(dice),
            "sum": res["sum"],
            "bets": {s["bet"]: s["stake"] for s in settlements},
            "settlements": settlements,
            "fair": {k: res[k] for k in ("server_seed", "commit", "client_seed")},
            "total_stake": total,
            "total_returned": returned,
            "net": returned - total,
            "balance_after": self.wallet.balance,
        }

    def to_view(self) -> dict:
        recent = self.results[-100:]
        n = len(recent)
        return {
            "nonce": self.nonce,
            "commit": self.commit,
            "client_seed": self.client_seed,
            "rtp": self.rtp,
            "payouts": self.payouts(),
            "last": self.results[-1] if self.results else None,
            "recent": [{k: r[k] for k in ("nonce", "dice", "sum", "parity", "size")} for r in self.results[-20:]][::-1],
            "road": [r["parity"] for r in self.results[-120:]],
            "road_sums": [r["sum"] for r in self.results[-120:]],
            "stats": {
                "n": n,
                "odd": sum(r["parity"] == "odd" for r in recent),
                "even": sum(r["parity"] == "even" for r in recent),
                "small": sum(r["size"] == "small" for r in recent),
                "big": sum(r["size"] == "big" for r in recent),
                "triple": sum(r["triple"] for r in recent),
                "faces": [sum(r["dice"].count(f) for r in recent) for f in range(1, 7)],
            },
        }
