"""User population generator.

Generates three fixed, reproducible user populations and persists them to a
pickle file so every simulator run sees the same user_ids.
"""
from __future__ import annotations

import pickle
import random
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_POPULATIONS_FILE = _DATA_DIR / "populations.pkl"
_SEED = 42


@dataclass(frozen=True)
class User:
    user_id: str
    tier: str  # "free" | "premium" | "internal"


def _generate() -> dict[str, list[User]]:
    random.seed(_SEED)
    free = [User(f"free_{i:05d}", "free") for i in range(10_000)]
    premium = [User(f"premium_{i:03d}", "premium") for i in range(100)]
    internal = [User(f"internal_{i}", "internal") for i in range(5)]
    return {"free": free, "premium": premium, "internal": internal}


def load() -> dict[str, list[User]]:
    """Return populations from cache, generating and persisting on first call."""
    if _POPULATIONS_FILE.exists():
        with open(_POPULATIONS_FILE, "rb") as f:
            return pickle.load(f)
    pops = _generate()
    _DATA_DIR.mkdir(exist_ok=True)
    with open(_POPULATIONS_FILE, "wb") as f:
        pickle.dump(pops, f)
    return pops
