"""
sync/tests/unit/test_buffer.py — Layer 1 unit tests for the bounded FIFO
failover buffer.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.buffer.py
"""
from sync.buffer import FailoverBuffer


def test_push_and_drain_fifo_order():
    b = FailoverBuffer(max_entries_per_kind=10)
    for i in range(5):
        b.push("relay_apply", i)
    assert list(b.drain("relay_apply")) == [0, 1, 2, 3, 4]


def test_drain_empties_queue():
    b = FailoverBuffer(max_entries_per_kind=10)
    b.push("relay_apply", "x")
    list(b.drain("relay_apply"))
    assert b.size("relay_apply") == 0


def test_overflow_drops_oldest_and_returns_false():
    b = FailoverBuffer(max_entries_per_kind=3)
    for i in range(3):
        assert b.push("k", i) is True
    assert b.push("k", 99) is False  # over cap; oldest dropped
    assert list(b.drain("k")) == [1, 2, 99]


def test_size_per_kind_independent():
    b = FailoverBuffer(max_entries_per_kind=10)
    b.push("a", 1)
    b.push("b", 2)
    b.push("b", 3)
    assert b.size("a") == 1
    assert b.size("b") == 2


def test_size_unknown_kind_is_zero():
    b = FailoverBuffer()
    assert b.size("nope") == 0
