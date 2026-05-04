"""
sync/tests/unit/test_partition_table.py — Layer 1 unit tests for the directional
partition rules used by relay.py to drop messages.
"""
from sync.partition_table import PartitionTable


def test_empty_table_blocks_nothing():
    t = PartitionTable()
    assert t.blocks("us", "eu") is False


def test_add_blocks_directional():
    t = PartitionTable()
    t.add("us", "eu")
    assert t.blocks("us", "eu") is True
    assert t.blocks("eu", "us") is False  # asymmetric


def test_remove_clears_specific_pair():
    t = PartitionTable()
    t.add("us", "eu")
    t.add("us", "asia")
    t.remove("us", "eu")
    assert t.blocks("us", "eu") is False
    assert t.blocks("us", "asia") is True


def test_clear_removes_all():
    t = PartitionTable()
    t.add("us", "eu")
    t.add("eu", "asia")
    t.clear()
    assert t.snapshot() == set()


def test_snapshot_returns_copy():
    t = PartitionTable()
    t.add("us", "eu")
    snap = t.snapshot()
    snap.add(("xx", "yy"))  # mutate the copy
    assert ("xx", "yy") not in t.snapshot()
