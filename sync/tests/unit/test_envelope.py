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


def test_parse_reconcile_envelope():
    raw = (
        b'{"kind":"reconcile","v":1,"origin":"us","window_id":29620586,'
        b'"ts_ms":1714060800123,"slots":{"free:u_123":47,"premium:u_456":1203}}'
    )
    env = parse(raw)
    assert isinstance(env, ReconcileEnvelope)
    assert env.origin == "us"
    assert env.window_id == 29620586
    assert env.slots == {("free", "u_123"): 47, ("premium", "u_456"): 1203}


def test_serialize_reconcile_roundtrip():
    original = ReconcileEnvelope(
        origin="eu",
        window_id=99,
        ts_ms=42,
        slots={("free", "u_1"): 10, ("free", "u_2"): 20},
    )
    raw = serialize_reconcile(original)
    parsed = parse(raw)
    assert parsed == original


def test_parse_reconcile_rejects_unknown_version():
    raw = b'{"kind":"reconcile","v":99,"origin":"us","window_id":1,"ts_ms":1,"slots":{}}'
    with pytest.raises(EnvelopeError, match="unknown version"):
        parse(raw)


def test_parse_reconcile_rejects_bad_slot_key():
    raw = b'{"kind":"reconcile","v":1,"origin":"us","window_id":1,"ts_ms":1,"slots":{"badkey":1}}'
    with pytest.raises(EnvelopeError, match="tier:user_id"):
        parse(raw)


def test_parse_rejects_non_object():
    with pytest.raises(EnvelopeError):
        parse(b'[1,2,3]')


def test_parse_rejects_invalid_json():
    with pytest.raises(EnvelopeError):
        parse(b'not json')
