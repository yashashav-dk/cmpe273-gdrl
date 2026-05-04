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


def test_merge_takes_max_per_slot():
    c = GCounter.from_slots("us", {"us": 5, "eu": 3})
    c.merge({"us": 4, "eu": 7, "asia": 2})  # us 4 < 5 keeps 5; eu 7 > 3; asia new
    assert c.slots() == {"us": 5, "eu": 7, "asia": 2}


def test_merge_is_idempotent_on_replay():
    c = GCounter.from_slots("us", {"us": 5})
    incoming = {"eu": 7, "asia": 2}
    for _ in range(100):
        c.merge(incoming)
    assert c.slots() == {"us": 5, "eu": 7, "asia": 2}


def test_merge_is_commutative():
    a = GCounter("us")
    b = GCounter("us")
    a.merge({"eu": 3})
    a.merge({"asia": 2})
    b.merge({"asia": 2})
    b.merge({"eu": 3})
    assert a.slots() == b.slots()


def test_increment_negative_raises():
    c = GCounter("us")
    import pytest
    with pytest.raises(ValueError):
        c.increment(-1)
