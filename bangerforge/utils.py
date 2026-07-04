"""Shared utilities."""

from __future__ import annotations

import math
from typing import Any


def normalize_position(pos: str) -> str:
    """Map NHL position codes to fantasy slots."""
    mapping = {"L": "LW", "R": "RW", "C": "C", "D": "D", "G": "G"}
    return mapping.get(str(pos).upper(), str(pos).upper())


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce value to int; handles NaN/None from pandas."""
    if value is None:
        return default
    try:
        if isinstance(value, float) and math.isnan(value):
            return default
    except TypeError:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return default