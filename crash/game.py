"""비행기(크래시) 게임 엔진.

- 배당은 시간에 따라 m(t) = e^(K·t) 로 오른다 (2배 ≈ 8.2초, 10배 ≈ 27초).
- 추락 지점 X 는 "x배 이상 버틸 확률 = 환수율 ÷ x" 가 되도록 뽑는다.
  → 어느 배당에서 멈추든 기대 환수는 정확히 환수율이다 (배당 확률이 환수율에 비례).
- 공정성 검증(provably fair): 판마다 서버 시드를 새로 만들고, 시작 전에 SHA-256 해시를 먼저 보여 준다.
  추락 지점 = HMAC-SHA256(서버 시드, "사용자 시드:판 번호") 에서 계산. 판이 끝나면 서버 시드를 공개한다.
- 칩은 베팅할 때 차감하고, 멈추면(캐시아웃) 바로 돌려준다. 멈추기는 서버 시계로 검증한다.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

from wallet import Wallet

K = 0.085                 # 배당 상승 속도 (1/초)
MAX_MULTIPLIER = 1000.0   # 이 배당에 닿으면 강제 추락
PANELS = (1,)             # 한 판에 베팅 1개
LATENCY_GRACE = 0.35      # 멈추기 요청이 서버에 닿기까지의 여유(초)


def multiplier_at(t: float) -> float:
    return math.exp(K * max(t, 0.0))


def time_at(m: float) -> float:
    return math.log(m) / K


def seed_hash(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


def crash_point(server_seed: str, client_seed: str, nonce: int, rtp: float,
                cap: float = MAX_MULTIPLIER) -> float:
    """추락 지점(소수 둘째 자리 내림). P(추락 지점 ≥ x) = rtp / x  (1.00 ≤ x ≤ cap)."""
    digest = hmac.new(server_seed.encode(), f"{client_seed}:{nonce}".encode(), hashlib.sha256).hexdigest()
    r = int(digest[:13], 16) / 16**13          # 52비트 → [0, 1) 균등
    x = rtp / (1 - r)
    return min(max(math.floor(x * 100) / 100, 1.00), cap)


class Phase(str, Enum):
    BETTING = "betting"
    FLYING = "flying"


class CrashError(ValueError):
    pass


@dataclass
class Bet:
    panel: int
    stake: int
    auto: float | None = None          # 자동 멈춤 배당
    cashed_at: float | None = None     # 멈춘 배당
    returned: int = 0

    def to_dict(self) -> dict:
        return {"panel": self.panel, "stake": self.stake, "auto": self.auto,
                "cashed_at": self.cashed_at, "returned": self.returned}


@dataclass
class CrashTable:
    wallet: Wallet
    rtp: float = 0.50   # 환수율 50%: 판의 약 절반은 1.00x에서 바로 추락 (고배당은 드물게: 10x 이상 5%, 100x 이상 0.5%)
    min_bet: int = 1_000
    max_bet: int = 1_000_000
    client_seed: str = field(default_factory=lambda: secrets.token_hex(8))
    phase: Phase = Phase.BETTING
    nonce: int = 0
    history: list[dict] = field(default_factory=list)     # 끝난 판 (공정성 검증 정보 포함)

    def __post_init__(self):
        self._next_seed()
        self.bets: dict[int, Bet] = {}
        self.crash: float | None = None
        self.started_at: float | None = None
        self.last_round: dict | None = None

    def _next_seed(self) -> None:
        self.server_seed = secrets.token_hex(32)
        self.commit = seed_hash(self.server_seed)   # 판 시작 전에 공개하는 약속값

    # ── 판 시작 ─────────────────────────────────────────────────────
    def start(self, bets: dict[int, dict], now: float | None = None) -> None:
        if self.phase is Phase.FLYING:
            raise CrashError("비행 중에는 새로 베팅할 수 없습니다.")
        clean: dict[int, Bet] = {}
        for panel, b in bets.items():
            panel = int(panel)
            if panel not in PANELS:
                raise CrashError("없는 베팅 패널입니다.")
            stake = int(b.get("stake") or 0)
            if not stake:
                continue
            if not self.min_bet <= stake <= self.max_bet:
                raise CrashError(f"베팅은 {self.min_bet:,} ~ {self.max_bet:,} 사이여야 합니다.")
            auto = b.get("auto")
            auto = round(float(auto), 2) if auto else None
            if auto is not None and not 1.01 <= auto <= MAX_MULTIPLIER:
                raise CrashError("자동 멈춤 배당은 1.01x 이상이어야 합니다.")
            clean[panel] = Bet(panel, stake, auto)
        if not clean:
            raise CrashError("베팅이 없습니다.")
        total = sum(b.stake for b in clean.values())
        if total > self.wallet.balance:
            raise CrashError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")
        self.wallet.debit(total)
        self.nonce += 1
        self.bets = clean
        self.crash = crash_point(self.server_seed, self.client_seed, self.nonce, self.rtp)
        self.started_at = time.time() if now is None else now
        self.phase = Phase.FLYING

    def elapsed(self, now: float | None = None) -> float:
        return (time.time() if now is None else now) - self.started_at

    # ── 멈추기 ─────────────────────────────────────────────────────
    def cash_out(self, panel: int, claimed: float, now: float | None = None) -> int:
        """화면에서 누른 순간의 배당으로 멈춘다. 서버 시계로 그 배당까지 올라왔는지, 추락 전인지 확인."""
        if self.phase is not Phase.FLYING:
            raise CrashError("비행 중이 아닙니다.")
        bet = self.bets.get(int(panel))
        if not bet or bet.cashed_at is not None:
            raise CrashError("멈출 베팅이 없습니다.")
        # 2.05 * 100 = 204.999… 같은 소수 오차로 0.01이 깎이지 않게, 먼저 둘째 자리 근처에서 반올림한 뒤 내림
        m = math.floor(round(float(claimed) * 100, 6)) / 100
        if m < 1.00:
            raise CrashError("잘못된 배당입니다.")
        if bet.auto is not None and bet.auto <= m:
            m = bet.auto  # 자동 멈춤이 먼저 걸렸다
        if m > self.crash:
            raise CrashError(f"이미 {self.crash:.2f}x에서 추락했습니다.")
        if m > multiplier_at(self.elapsed(now) + LATENCY_GRACE):
            raise CrashError("아직 그 배당까지 올라가지 않았습니다.")
        bet.cashed_at = m
        bet.returned = math.floor(bet.stake * m)
        self.wallet.credit(bet.returned)
        return bet.returned

    # ── 추락 / 정산 ─────────────────────────────────────────────────
    def finish(self) -> dict:
        """판을 끝낸다. 자동 멈춤이 추락 지점 이하이면 그 배당으로 지급하고, 나머지는 잃는다."""
        if self.phase is not Phase.FLYING:
            raise CrashError("비행 중이 아닙니다.")
        for bet in self.bets.values():
            if bet.cashed_at is None and bet.auto is not None and bet.auto <= self.crash:
                bet.cashed_at = bet.auto
                bet.returned = math.floor(bet.stake * bet.auto)
                self.wallet.credit(bet.returned)
        stake = sum(b.stake for b in self.bets.values())
        returned = sum(b.returned for b in self.bets.values())
        rnd = {
            "nonce": self.nonce, "crash": self.crash, "server_seed": self.server_seed, "commit": self.commit,
            "client_seed": self.client_seed, "rtp": self.rtp,
            "bets": [b.to_dict() for b in self.bets.values()],
            "stake": stake, "returned": returned, "net": returned - stake,
        }
        self.history.append(rnd)
        self.last_round = rnd
        self.phase = Phase.BETTING
        self._next_seed()
        return rnd

    def set_client_seed(self, seed: str) -> None:
        if self.phase is Phase.FLYING:
            raise CrashError("비행 중에는 시드를 바꿀 수 없습니다.")
        seed = seed.strip()
        if not seed:
            raise CrashError("시드를 입력하세요.")
        self.client_seed = seed

    # ── 화면 / 기록 ─────────────────────────────────────────────────
    def to_view(self) -> dict:
        flying = self.phase is Phase.FLYING
        return {
            "phase": self.phase.value,
            "nonce": self.nonce,
            "commit": self.commit if not flying else seed_hash(self.server_seed),
            "client_seed": self.client_seed,
            "k": K,
            "cap": MAX_MULTIPLIER,
            "rtp": self.rtp,
            # 브라우저가 매끄럽게 연출하도록 추락 지점을 미리 보낸다 (가상 칩 1인 게임이라 허용한 선택)
            "crash": self.crash if flying else None,
            "elapsed": self.elapsed() if flying else None,
            "bets": {b.panel: b.to_dict() for b in self.bets.values()} if flying else {},
            "recent": [r["crash"] for r in self.history[-20:]][::-1],
            "last": self.last_round,
        }

    def round_record(self, rnd: dict) -> dict:
        """베팅 기록(ledger)에 남길 한 판."""
        settlements = [{
            "bet": f"crash_{b['panel']}", "stake": b["stake"], "returned": b["returned"],
            "outcome": "win" if b["cashed_at"] else "lose",
            "detail": f"{b['cashed_at']:.2f}x" if b["cashed_at"] else None,
        } for b in rnd["bets"]]
        return {
            "game": "crash",
            "bets": {f"crash_{b['panel']}": b["stake"] for b in rnd["bets"]},
            "settlements": settlements,
            "crash": rnd["crash"],
            "cashouts": {b["panel"]: b["cashed_at"] for b in rnd["bets"]},
            "fair": {k: rnd[k] for k in ("server_seed", "commit", "client_seed", "nonce", "rtp")},
            "total_stake": rnd["stake"],
            "total_returned": rnd["returned"],
            "net": rnd["net"],
            "balance_after": self.wallet.balance,
            "round_no": rnd["nonce"],
        }


def success_table(rtp: float, targets=(1.2, 1.5, 2, 3, 5, 10, 20, 50, 100)) -> list[dict]:
    """목표 배당별 성공 확률 (= 환수율 ÷ 배당) 과 기대 환수."""
    return [{"목표": f"{x:g}x", "성공 확률": rtp / x, "기대 환수": rtp} for x in targets]
