import math
import secrets

import pytest

from crash.game import (CrashError, CrashTable, Phase, crash_point, multiplier_at, seed_hash,
                        success_table, time_at)
from wallet import SessionWallet


def samples(n, rtp, seed="server"):
    return [crash_point(seed, "client", i, rtp) for i in range(n)]


def test_growth_curve():
    assert multiplier_at(0) == 1
    assert time_at(2) == pytest.approx(8.15, abs=0.01)
    assert time_at(10) == pytest.approx(27.09, abs=0.01)


@pytest.mark.parametrize("rtp", [0.50, 0.95, 0.97, 0.99])
def test_survival_is_rtp_over_x(rtp):
    xs = samples(200_000, rtp)
    for target in (1.5, 2, 5, 10):
        p = sum(x >= target for x in xs) / len(xs)
        assert p == pytest.approx(rtp / target, abs=0.004), target
    assert min(xs) == 1.00 and max(xs) <= 1000


def test_expected_return_equals_rtp_for_any_target():
    xs = samples(300_000, 0.97)
    for target in (1.2, 2, 3, 10):
        ret = sum(target if x >= target else 0 for x in xs) / len(xs)
        assert ret == pytest.approx(0.97, abs=0.015), target


def test_provably_fair_is_reproducible():
    seed = secrets.token_hex(32)
    assert crash_point(seed, "abc", 7, 0.97) == crash_point(seed, "abc", 7, 0.97)
    assert len({crash_point(seed, "abc", n, 0.97) for n in range(50)}) > 10  # 판 번호마다 다른 값
    t = CrashTable(SessionWallet({}, initial=100_000))
    commit, server_seed = t.commit, t.server_seed
    assert commit == seed_hash(server_seed)
    t.start({1: {"stake": 1_000}}, now=0)
    rnd = t.finish()
    assert rnd["server_seed"] == server_seed and rnd["commit"] == commit
    assert rnd["crash"] == crash_point(server_seed, t.client_seed, rnd["nonce"], t.rtp)
    assert t.commit != commit  # 다음 판은 새 시드


def table_with_crash(crash, balance=100_000):
    """추락 지점이 정해진 테이블 (서버 시드를 찾아서 맞춘다)."""
    t = CrashTable(SessionWallet({}, initial=balance), client_seed="test")
    for _ in range(20_000):
        if crash_point(t.server_seed, "test", 1, t.rtp) == crash:
            return t
        t._next_seed()
    pytest.skip("원하는 추락 지점을 찾지 못함")


def test_cash_out_rules():
    t = table_with_crash(1.00)
    t.start({1: {"stake": 1_000}}, now=100)
    with pytest.raises(CrashError, match="추락"):
        t.cash_out(1, 1.01, now=100.5)
    assert t.finish()["net"] == -1_000

    t = CrashTable(SessionWallet({}, initial=100_000))
    t.start({1: {"stake": 10_000}, 2: {"stake": 5_000, "auto": 1.5}}, now=0)
    t.crash = 3.00  # 테스트용으로 고정
    with pytest.raises(CrashError, match="아직"):
        t.cash_out(1, 2.0, now=1.0)  # 1초 뒤에는 약 1.09x
    paid = t.cash_out(1, 2.0, now=time_at(2.0))
    assert paid == 20_000
    with pytest.raises(CrashError, match="멈출 베팅"):
        t.cash_out(1, 2.5, now=time_at(2.5))
    rnd = t.finish()  # 2번 패널은 자동 멈춤 1.5x
    assert {b["panel"]: b["cashed_at"] for b in rnd["bets"]} == {1: 2.0, 2: 1.5}
    assert rnd["returned"] == 20_000 + 7_500
    assert t.wallet.balance == 100_000 - 15_000 + 27_500
    assert t.phase is Phase.BETTING


def test_auto_above_crash_loses_and_validation():
    t = CrashTable(SessionWallet({}, initial=5_000))
    with pytest.raises(CrashError, match="칩이 부족"):
        t.start({1: {"stake": 3_000}, 2: {"stake": 3_000}})
    with pytest.raises(CrashError, match="1.01x"):
        t.start({1: {"stake": 1_000, "auto": 1.0}})
    t.start({1: {"stake": 1_000, "auto": 5}}, now=0)
    t.crash = 2.0
    rnd = t.finish()
    assert rnd["returned"] == 0 and t.wallet.balance == 4_000
    rec = t.round_record(rnd)
    assert rec["game"] == "crash" and rec["net"] == -1_000
    assert rec["settlements"][0]["bet"] == "crash_1"


def test_success_table_is_proportional_to_rtp():
    for rtp in (0.50, 0.95, 0.97):
        for row in success_table(rtp):
            x = float(row["목표"].rstrip("x"))
            assert math.isclose(row["성공 확률"] * x, rtp)


def test_default_rtp_is_50_percent():
    t = CrashTable(SessionWallet({}, initial=100_000))
    assert t.rtp == 0.50
    xs = samples(100_000, t.rtp)
    instant = sum(x == 1.00 for x in xs) / len(xs)
    assert instant == pytest.approx(1 - 0.50 / 1.01, abs=0.01)   # 약 50%는 뜨자마자 추락
