"""1차 구현: 사용자가 정한 시작 칩을 세션 저장소(st.session_state 또는 dict)에 보관."""
from __future__ import annotations

from collections.abc import MutableMapping

from .base import Wallet


class SessionWallet(Wallet):
    def __init__(self, store: MutableMapping, key: str = "chips", initial: int = 0):
        self._store = store
        self._key = key
        if key not in store:
            store[key] = int(initial)

    @property
    def balance(self) -> int:
        return int(self._store[self._key])

    def _set_balance(self, value: int) -> None:
        self._store[self._key] = int(value)

    def reset(self, amount: int) -> None:
        self._set_balance(amount)
