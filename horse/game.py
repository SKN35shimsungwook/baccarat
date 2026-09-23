"""경마 게임 엔진 (단승식, 6마리, 버튼으로 바로 출발).

- 말 50마리(가상) 중 경주마다 6마리를 뽑는다. 말마다 숨은 실력(rating)과 최근 5경주 성적이 있다.
- 말마다 고유한 달리기 특성(선행 / 중간 / 추입)이 있어 경주 연출에 반영된다.
- 6마리의 1등 확률을 등급별로 정한다 (기본 환수율 96% 기준 배당):
    강자 S: 2~4배 · 중간 A: 5~16배 · 복병 O: 18~90배
  실력이 좋은 말일수록 높은 확률을 받는다. 배당 = 환수율 ÷ 1등 확률 (소수 둘째 자리 내림).
- 베팅은 1등 말 맞히기(단승)만. 여러 마리에 걸 수 있지만 6마리 전부는 양방이라 막는다.
- 공정성 검증: 경주마다 서버 시드를 새로 만들어 출전표와 함께 SHA-256 해시를 보여 주고, 경주 후 공개한다.
  순위 = HMAC-SHA256(서버 시드, "사용자 시드:경주 번호:i") 로 i번째 자리를 남은 말 중 확률 비례로 뽑는다.
- 화면용 "경주 대본"(시간별 위치)도 같은 시드로 만든다. 대본은 정해진 순위대로 결승선을 통과한다.
- 팁스터: 지난 100경주 기록으로 출전마별 성적과 RTP(그 말에 매번 같은 금액을 걸었다면 돌려받은 비율),
  팁스터 추천(RTP가 가장 높은 출전마), 최다 우승마를 보여 준다 (참고용, 미래를 보장하지 않음).
"""
from __future__ import annotations

import hashlib
import hmac
import math
import random
import secrets
from dataclasses import dataclass, field

from wallet import Wallet

LANES = 6
RACE_SECONDS = 12.0      # 1등이 결승선을 통과하는 시각 (출발 후)
SCRIPT_DT = 0.2          # 대본 간격(초)
SCRIPT_END = 14.4        # 대본 길이(초): 꼴찌가 들어오고 조금 더
HISTORY_KEEP = 200

RTP_REF = 0.96          # 기본 환수율. 이 값에서 등급별 배당이 아래 범위가 되도록 확률을 정한다
TIPSTER_RACES = 100     # 팁스터가 분석하는 지난 경주 수
# 등급: 이름, 1등 확률 범위(기본 환수율에서 배당 2~4 / 5~16 / 18~90배), 뽑을 때의 원시 가중치 범위
TIERS = {
    "S": ("강자", (RTP_REF / 4, RTP_REF / 2), (0.25, 0.45)),
    "A": ("중간", (RTP_REF / 16, RTP_REF / 5), (0.07, 0.18)),
    "O": ("복병", (RTP_REF / 90, RTP_REF / 18), (0.013, 0.05)),
}
STYLES = {"front": "선행", "mid": "중간", "closer": "추입"}
LINEUPS = ("SSAAAO", "SAAAAO", "SAAAOO", "SSAAOO")

NAMES = (
    "번개질주", "은빛바람", "붉은태양", "천둥발굽", "푸른초원", "황금갈기", "새벽별", "질풍노도", "바람의아들", "흑진주",
    "들불", "폭풍전야", "달빛기사", "불꽃심장", "청룡", "백호", "주작", "현무", "강철다리", "구름위로",
    "한라의별", "백두의꿈", "남풍", "북극성", "은하수", "무지개", "파도타기", "초승달", "해오름", "노을빛",
    "눈꽃송이", "들국화", "소나기", "돌풍", "산들바람", "광야의별", "대장군", "행운편지", "금빛화살", "은화살",
    "번쩍번쩍", "천리마", "적토마", "한걸음더", "끝까지간다", "막판스퍼트", "여름바다", "가을하늘", "겨울나그네", "봄날의꿈",
)
# 털색(몸, 갈기) · 기수 옷 색
COATS = (("#8b4a2b", "#3b1d10"), ("#b5652d", "#6b3413"), ("#5a3220", "#24120a"),
         ("#b9b3a8", "#6e6962"), ("#2e2824", "#0f0c0a"), ("#d9a856", "#f3e3b8"))
SILKS = ("#e53935", "#fdd835", "#1e88e5", "#43a047", "#8e24aa", "#fb8c00", "#00acc1", "#f06292",
         "#ffffff", "#6d4c41", "#3949ab", "#c0ca33")


def odds_for(rtp: float, prob: float) -> float:
    return math.floor(rtp / prob * 100 + 1e-9) / 100


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _unit(server_seed: str, client_seed: str, race_no: int, i: int) -> float:
    d = hmac.new(server_seed.encode(), f"{client_seed}:{race_no}:{i}".encode(), hashlib.sha256).digest()
    return int.from_bytes(d[:8], "big") / 2 ** 64


def race_order(server_seed: str, client_seed: str, race_no: int, probs: list[float]) -> list[int]:
    """1등부터 순서대로 레인 번호(1~6). i번째 자리는 남은 말 중 확률 비례로 뽑는다."""
    left = list(range(1, len(probs) + 1))
    order = []
    for i in range(len(probs) - 1):
        u = _unit(server_seed, client_seed, race_no, i) * sum(probs[k - 1] for k in left)
        acc = 0.0
        pick = left[-1]
        for k in left:
            acc += probs[k - 1]
            if u < acc:
                pick = k
                break
        order.append(pick)
        left.remove(pick)
    return order + left


def race_script(server_seed: str, client_seed: str, race_no: int, order: list[int],
                styles: list[str] | None = None) -> dict:
    """화면용 경주 대본: 레인별 시간에 따른 진행률(0 → 결승선 1). 순위대로 결승선을 통과한다.
    styles: 레인별 달리기 특성 (선행은 초반에 앞서고, 추입은 막판에 치고 올라온다)."""
    seed = hmac.new(server_seed.encode(), f"{client_seed}:{race_no}:script".encode(), hashlib.sha256).digest()
    rng = random.Random(int.from_bytes(seed, "big"))
    finish = {}
    t = RACE_SECONDS
    for rank, lane in enumerate(order):
        if rank:
            t += rng.choice((rng.uniform(0.04, 0.15), rng.uniform(0.15, 0.55)))  # 가끔 코 차이 접전
        finish[lane] = t
    steps = int(round(SCRIPT_END / SCRIPT_DT)) + 1
    pos = []
    for lane in range(1, LANES + 1):
        T = finish[lane]
        style = styles[lane - 1] if styles else rng.choice(tuple(STYLES))
        v, speeds = 1.0, []
        for k in range(steps):
            tt = k * SCRIPT_DT
            v += rng.gauss(0, 0.07) - 0.18 * (v - 1)
            v = min(1.35, max(0.7, v))
            frac = min(1.0, tt / RACE_SECONDS)
            shape = {"front": 1.18 - 0.36 * frac, "mid": 1.0, "closer": 0.84 + 0.32 * frac}[style]
            accel = min(1.0, (tt + 0.1) / 0.9)             # 게이트에서 가속
            speeds.append(v * shape * accel)
        # 결승선(T)까지 간 거리가 1이 되도록 맞춘다
        dist = [0.0]
        for k in range(1, steps):
            dist.append(dist[-1] + speeds[k - 1] * SCRIPT_DT)
        kT = T / SCRIPT_DT
        i = int(kT)
        at_T = dist[i] + (dist[min(i + 1, steps - 1)] - dist[i]) * (kT - i)
        scale = 1.0 / at_T
        row = []
        for k in range(steps):
            tt = k * SCRIPT_DT
            if tt <= T:
                row.append(dist[k] * scale)
            else:  # 결승선을 지나면 천천히 멈춘다
                over = tt - T
                row.append(1.0 + 0.06 * (1 - math.exp(-over / 0.9)))
        pos.append([round(p, 4) for p in row])
    return {"dt": SCRIPT_DT, "pos": pos, "finish": [round(finish[l], 3) for l in range(1, LANES + 1)]}


class HorseError(ValueError):
    pass


@dataclass
class HorseTable:
    wallet: Wallet
    rtp: float = RTP_REF
    min_bet: int = 1_000
    max_bet: int = 1_000_000
    client_seed: str = field(default_factory=lambda: secrets.token_hex(8))
    race_no: int = 0                 # 마지막으로 달린 경주 번호
    results: list[dict] = field(default_factory=list)

    def __post_init__(self):
        rnd = random.SystemRandom()
        self._rnd = rnd
        silks = list(SILKS)
        self.pool = []
        for i, name in enumerate(NAMES):
            rating = rnd.uniform(40, 100)
            self.pool.append({
                "id": i, "name": name, "rating": rating,
                "coat": COATS[i % len(COATS)], "silk": silks[(i * 5) % len(silks)],
                "style": rnd.choice(tuple(STYLES)),
                "starts": 0, "wins": 0,
                # 처음 보여 줄 최근 5경주 성적 (실력대로 대략)
                "form": [min(6, max(1, round(6 - (rating - 40) / 12 + rnd.gauss(0, 1.2)))) for _ in range(5)],
            })
        self._next_race()

    # ── 다음 경주 준비: 출전마 6마리, 확률, 시드 ─────────────────────
    def _tier_probs(self) -> list[tuple[str, float]]:
        rnd = self._rnd
        while True:
            tiers = list(rnd.choice(LINEUPS))
            raw = [rnd.uniform(*TIERS[t][2]) for t in tiers]
            total = sum(raw)
            probs = [r / total for r in raw]
            if all(TIERS[t][1][0] <= p <= TIERS[t][1][1] for t, p in zip(tiers, probs)):
                return sorted(zip(tiers, probs), key=lambda tp: -tp[1])

    def _next_race(self) -> None:
        rnd = self._rnd
        horses = rnd.sample(self.pool, LANES)
        horses.sort(key=lambda h: -(h["rating"] + rnd.gauss(0, 12)))   # 실력 좋은 말이 높은 확률
        assigned = list(zip(horses, self._tier_probs()))
        rnd.shuffle(assigned)                                          # 게이트 번호는 무작위
        self.lineup = [{"lane": i + 1, "id": h["id"], "tier": t, "prob": p} for i, (h, (t, p)) in enumerate(assigned)]
        self.server_seed = secrets.token_hex(32)
        self.commit = seed_hash(self.server_seed)

    def lineup_view(self, lineup: list[dict] | None = None, rtp: float | None = None) -> list[dict]:
        rtp = self.rtp if rtp is None else rtp
        out = []
        for e in lineup or self.lineup:
            h = self.pool[e["id"]]
            out.append({
                "lane": e["lane"], "id": h["id"], "name": h["name"], "tier": e["tier"], "tier_name": TIERS[e["tier"]][0],
                "prob": round(e["prob"], 5), "odds": e.get("odds") or odds_for(rtp, e["prob"]),
                "coat": h["coat"][0], "mane": h["coat"][1], "silk": h["silk"],
                "form": h["form"][-5:], "starts": h["starts"], "wins": h["wins"],
                "style": h["style"], "style_name": STYLES[h["style"]],
            })
        return out

    def payouts(self) -> dict[str, float]:
        return {str(e["lane"]): odds_for(self.rtp, e["prob"]) for e in self.lineup}

    def set_client_seed(self, seed: str) -> None:
        seed = seed.strip()
        if not seed:
            raise HorseError("시드를 입력하세요.")
        self.client_seed = seed

    # ── 베팅 → 경주 → 정산 ──────────────────────────────────────────
    def play(self, bets: dict[str, int]) -> dict:
        clean = {str(k): int(v) for k, v in bets.items() if int(v or 0) > 0}
        if not clean:
            raise HorseError("베팅이 없습니다.")
        for lane, v in clean.items():
            if lane not in {str(i) for i in range(1, LANES + 1)}:
                raise HorseError("없는 말입니다.")
            if not self.min_bet <= v <= self.max_bet:
                raise HorseError(f"{lane}번: 베팅은 {self.min_bet:,} ~ {self.max_bet:,} 사이여야 합니다.")
        if len(clean) == LANES:
            raise HorseError("6마리 모두에 거는 양방 베팅은 할 수 없습니다.")
        total = sum(clean.values())
        if total > self.wallet.balance:
            raise HorseError(f"칩이 부족합니다. (베팅 {total:,} / 보유 {self.wallet.balance:,})")

        self.wallet.debit(total)
        self.race_no += 1
        k = self.race_no
        odds = self.payouts()
        lineup = [{**e, "odds": odds[str(e["lane"])]} for e in self.lineup]
        probs = [e["prob"] for e in lineup]
        order = race_order(self.server_seed, self.client_seed, k, probs)
        styles = [self.pool[e["id"]]["style"] for e in lineup]
        script = race_script(self.server_seed, self.client_seed, k, order, styles)
        view = self.lineup_view(lineup)          # 이번 경주 전의 성적으로 보여 준다
        winner = view[order[0] - 1]

        # 말 기록 갱신
        for rank, lane in enumerate(order, start=1):
            h = self.pool[lineup[lane - 1]["id"]]
            h["starts"] += 1
            h["wins"] += rank == 1
            h["form"] = (h["form"] + [rank])[-5:]

        res = {
            "race_no": k, "lineup": view, "order": order, "winner": order[0], "script": script,
            "text": f"{winner['lane']}번 {winner['name']}", "tier": winner["tier"], "odds": winner["odds"],
            "seed": self.server_seed, "commit": self.commit, "client_seed": self.client_seed,
        }
        self.results.append(res)
        self.results = self.results[-HISTORY_KEEP:]

        settlements = []
        for lane, stake in clean.items():
            e = view[int(lane) - 1]
            win = int(lane) == order[0]
            returned = math.floor(stake * e["odds"]) if win else 0
            if returned:
                self.wallet.credit(returned)
            settlements.append({"bet": f"hr_{e['tier']}", "stake": stake, "returned": returned,
                                "outcome": "win" if win else "lose",
                                "detail": f"{lane}번 {e['name']} {e['odds']:.2f}x"})
        by_tier: dict[str, int] = {}
        for st in settlements:
            by_tier[st["bet"]] = by_tier.get(st["bet"], 0) + st["stake"]
        returned = sum(st["returned"] for st in settlements)
        self._next_race()
        return {
            "game": "horse",
            "round_no": k,
            "result": res["text"],
            "order": order,
            "bets": by_tier,
            "lanes": clean,
            "settlements": settlements,
            "fair": {key: res[key] for key in ("seed", "commit", "client_seed")},
            "total_stake": total,
            "total_returned": returned,
            "net": returned - total,
            "balance_after": self.wallet.balance,
        }

    # ── 팁스터 (지난 100경주 분석, 참고용) ──────────────────────────
    def tipster(self) -> dict:
        recent = self.results[-TIPSTER_RACES:]
        per: dict[int, dict] = {}
        for r in recent:
            for rank, lane in enumerate(r["order"], start=1):
                hid = r["lineup"][lane - 1]["id"]
                a = per.setdefault(hid, {"starts": 0, "wins": 0, "top3": 0, "rank_sum": 0, "ret": 0.0})
                a["starts"] += 1
                a["ret"] += r["lineup"][lane - 1]["odds"] if rank == 1 else 0
                a["wins"] += rank == 1
                a["top3"] += rank <= 3
                a["rank_sum"] += rank

        def row(hid: int) -> dict:
            a = per.get(hid, {"starts": 0, "wins": 0, "top3": 0, "rank_sum": 0, "ret": 0.0})
            n = a["starts"]
            return {"starts": n, "wins": a["wins"], "top3": a["top3"],
                    "avg": round(a["rank_sum"] / n, 2) if n else None,
                    "rtp": round(a["ret"] / n * 100) if n else None}

        top = sorted(per, key=lambda hid: (-per[hid]["wins"], per[hid]["rank_sum"] / per[hid]["starts"]))[:8]
        lineup = {str(e["lane"]): row(e["id"]) for e in self.lineup}
        rated = [(r["rtp"], int(lane)) for lane, r in lineup.items() if r["starts"]]
        return {
            "n": len(recent),
            "lineup": lineup,
            "pick": max(rated)[1] if rated else None,   # 팁스터 추천: 지난 기록 RTP가 가장 높은 출전마
            "top": [{"id": hid, "name": self.pool[hid]["name"], **row(hid)} for hid in top if per[hid]["wins"]],
        }

    # ── 화면 ────────────────────────────────────────────────────────
    def to_view(self) -> dict:
        recent = self.results[-TIPSTER_RACES:]
        return {
            "race_no": self.race_no + 1,
            "commit": self.commit,
            "client_seed": self.client_seed,
            "rtp": self.rtp,
            "lineup": self.lineup_view(),
            "last": self.results[-1] if self.results else None,
            "recent": [{"race_no": r["race_no"], "text": r["text"], "tier": r["tier"], "odds": r["odds"],
                        "lane": r["winner"]} for r in self.results[-12:]][::-1],
            "tier_wins": {t: sum(r["tier"] == t for r in recent) for t in TIERS},
            "n": len(recent),
            "tipster": self.tipster(),
        }
