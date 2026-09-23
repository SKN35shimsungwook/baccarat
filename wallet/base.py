"""칩 지갑 인터페이스.

게임 엔진은 이 인터페이스만 사용한다. 칩 시스템을 바꿀 때는 구현체만 교체한다.
(가상 포인트 전용. 실제 돈 충전/환전은 지원하지 않는다.)
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class InsufficientChips(ValueError):
    pass


class Wallet(ABC):
    @property
    @abstractmethod
    def balance(self) -> int: ...

    @abstractmethod
    def _set_balance(self, value: int) -> None: ...

    def debit(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("음수 금액은 차감할 수 없습니다.")
        if amount > self.balance:
            raise InsufficientChips(f"칩 부족: 필요 {amount:,}, 보유 {self.balance:,}")
        self._set_balance(self.balance - amount)

    def credit(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("음수 금액은 지급할 수 없습니다.")
        self._set_balance(self.balance + amount)
