"""
sync/tests/unit/test_crdt.py — Layer 1 unit tests for the G-Counter primitive.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §3 CRDT model
"""
from sync.crdt import GCounter


def test_empty_counter_value_is_zero():
    c = GCounter("us")
    assert c.value() == 0
    assert c.slots() == {}


def test_increment_writes_only_own_slot():
    c = GCounter("us")
    c.increment(3)
    assert c.value() == 3
    assert c.slots() == {"us": 3}


def test_increment_default_is_one():
    c = GCounter("us")
    c.increment()
    assert c.slots()["us"] == 1


def test_value_sums_all_slots():
    c = GCounter.from_slots("us", {"us": 5, "eu": 7, "asia": 2})
    assert c.value() == 14
