"""Simple JSON checkpoint store for resumable VLR scrapes."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable


class CheckpointStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._done: set[str] = set()
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._done = set(payload.get("done") or [])

    def is_done(self, key: str) -> bool:
        with self._lock:
            return str(key) in self._done

    def mark_done(self, key: str) -> None:
        with self._lock:
            self._done.add(str(key))
            self._flush_unlocked()

    def mark_many(self, keys: Iterable[str]) -> None:
        with self._lock:
            self._done.update(str(k) for k in keys)
            self._flush_unlocked()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        self.path.write_text(
            json.dumps({"done": sorted(self._done)}, indent=2),
            encoding="utf-8",
        )

    @property
    def done_count(self) -> int:
        with self._lock:
            return len(self._done)
