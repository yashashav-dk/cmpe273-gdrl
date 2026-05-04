"""
sync/partition_table.py — directional partition rules for sync's relay loop.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5, §6 Flow 4
Constitution: docs/sync-constitution.md Art VII (operational defaults)
Reads:       (in-memory only)
Writes:      (in-memory only)
Don't:       persist to Redis (state is intentionally ephemeral — restart heals).

Used to simulate cross-region partitions in tests and the demo. Asymmetric:
adding (us, eu) blocks us→eu only; eu→us still flows. Snapshots are copies
to prevent external mutation.
"""
from __future__ import annotations


class PartitionTable:
    def __init__(self) -> None:
        self._rules: set[tuple[str, str]] = set()

    def add(self, from_region: str, to_region: str) -> None:
        self._rules.add((from_region, to_region))

    def remove(self, from_region: str, to_region: str) -> None:
        self._rules.discard((from_region, to_region))

    def clear(self) -> None:
        self._rules.clear()

    def blocks(self, from_region: str, to_region: str) -> bool:
        return (from_region, to_region) in self._rules

    def snapshot(self) -> set[tuple[str, str]]:
        return set(self._rules)
