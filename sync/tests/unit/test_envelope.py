"""
sync/tests/unit/test_envelope.py — Layer 1 unit tests for wire envelopes.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §4
"""
import pytest
from sync.envelope import (
    CounterEnvelope,
    ReconcileEnvelope,
    parse,
    serialize_reconcile,
    EnvelopeError,
)


def test_parse_counter_envelope_roundtrip():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":29620586,'
        b'"region":"us","value":47,"ts_ms":1714060800123}'
    )
    env = parse(raw)
    assert isinstance(env, CounterEnvelope)
    assert env.tier == "free"
    assert env.user_id == "u_123"
    assert env.window_id == 29620586
    assert env.region == "us"
    assert env.value == 47
    assert env.ts_ms == 1714060800123


def test_parse_counter_rejects_missing_field():
    raw = b'{"tier":"free","user_id":"u_123","window_id":1,"region":"us","value":1}'
    with pytest.raises(EnvelopeError):
        parse(raw)


def test_parse_counter_rejects_bad_region():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":1,'
        b'"region":"mars","value":1,"ts_ms":1}'
    )
    with pytest.raises(EnvelopeError):
        parse(raw)


def test_parse_counter_rejects_negative_value():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":1,'
        b'"region":"us","value":-1,"ts_ms":1}'
    )
    with pytest.raises(EnvelopeError):
        parse(raw)
