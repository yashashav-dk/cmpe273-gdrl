"""
sync/crdt.py — G-Counter primitive.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §3, §5.crdt.py
Constitution: docs/sync-constitution.md Art II §3 (monotonic within window)
Reads:       nothing (pure data structure, no I/O)
Writes:      nothing (pure data structure, no I/O)
Don't:       expose set() or decrement(); add I/O.

Lifted with attribution from python3-crdt (anshulahuja98, MIT). The primitive is
deliberately I/O-free — RegionalCounter handles persistence and atomic merge.
"""
from __future__ import annotations


class GCounter:
    def __init__(self, region: str) -> None:
        self._region = region
        self._slots: dict[str, int] = {}

    @classmethod
    def from_slots(cls, region: str, slots: dict[str, int]) -> "GCounter":
        c = cls(region)
        c._slots = dict(slots)
        return c

    def increment(self, n: int = 1) -> None:
        if n < 0:
            raise ValueError("GCounter.increment requires n >= 0; decrement is forbidden")
        self._slots[self._region] = self._slots.get(self._region, 0) + n

    def merge(self, other: dict[str, int]) -> None:
        for region, value in other.items():
            cur = self._slots.get(region, 0)
            if value > cur:
                self._slots[region] = value

    def value(self) -> int:
        return sum(self._slots.values())

    def slots(self) -> dict[str, int]:
        return dict(self._slots)

    @property
    def region(self) -> str:
        return self._region
