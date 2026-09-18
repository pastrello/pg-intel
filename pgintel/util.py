from __future__ import annotations

import hashlib
from typing import Optional


def delta(current: Optional[int | float], previous: Optional[int | float]) -> int | float:
    """Return counter delta; if the counter was reset, treat current as the interval value."""
    if current is None:
        return 0
    if previous is None:
        return 0
    if current >= previous:
        return current - previous
    return current


def sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return part / whole


def human_bytes(n: int | float) -> str:
    value = float(n)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TiB"
