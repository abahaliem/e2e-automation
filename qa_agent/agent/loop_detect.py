from __future__ import annotations

from collections import Counter
from typing import Literal


class LoopDetector:
    """Hitung kombinasi (layar, aksi, target). Ke-3 → peringatan, ke-4 → blocked."""

    def __init__(self, warn_at: int = 3, block_at: int = 4) -> None:
        self.warn_at = warn_at
        self.block_at = block_at
        self._counts: Counter[tuple[str, str, str]] = Counter()

    def record(self, fingerprint: str, action: str, target: str) -> Literal["ok", "warn", "block"]:
        key = (fingerprint, action, target)
        self._counts[key] += 1
        n = self._counts[key]
        if n >= self.block_at:
            return "block"
        if n >= self.warn_at:
            return "warn"
        return "ok"
