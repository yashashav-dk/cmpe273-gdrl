from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DEFAULT_LOG = Path(__file__).parent / "decisions.jsonl"


class DecisionLog:
    def __init__(self, path: Path = _DEFAULT_LOG) -> None:
        self._path = path

    def append(self, decision: dict[str, Any]) -> None:
        if "created_at" not in decision:
            decision = {**decision, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with self._path.open("a") as fh:
            fh.write(json.dumps(decision) + "\n")
