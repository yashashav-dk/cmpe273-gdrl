"""
sync/buffer.py — bounded FIFO failover buffer (placeholder; full impl in Task 22).
"""
from __future__ import annotations

from collections import deque
from typing import Any


class FailoverBuffer:
    def __init__(self, max_entries_per_kind: int = 10_000) -> None:
        self._cap = max_entries_per_kind
        self._queues: dict[str, deque] = {}

    def push(self, kind: str, payload: Any) -> bool:
        q = self._queues.setdefault(kind, deque())
        if len(q) >= self._cap:
            q.popleft()
            return False
        q.append(payload)
        return True

    def drain(self, kind: str):
        q = self._queues.get(kind)
        if not q:
            return
        while q:
            yield q.popleft()

    def size(self, kind: str) -> int:
        return len(self._queues.get(kind, ()))
