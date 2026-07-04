"""Roster tab stat mode helpers — minimal deps."""

from __future__ import annotations

from datetime import date
from typing import Any

from bangerforge.roster_constants import DEFAULT_ROLLING_GAMES, DEFAULT_SEASON_START


def resolve_roster_stat_mode(settings: dict[str, Any]) -> str:
    """Resolve active roster display mode from settings (auto flips on season start)."""
    mode = str(settings.get("roster_stat_mode", "auto"))
    if mode in ("prior_season", "rolling_25"):
        return mode
    season_start = str(settings.get("season_start_date", DEFAULT_SEASON_START))
    if date.today().isoformat() < season_start:
        return "prior_season"
    return "rolling_25"


def roster_stat_label(mode: str, settings: dict[str, Any]) -> str:
    """Human-readable label for roster-tab stat source."""
    if mode == "prior_season":
        return "2024-25 full season (per-game)"
    sample = int(settings.get("rolling_games_sample", DEFAULT_ROLLING_GAMES))
    return f"Last {sample} GP — 2025-26 (per-game)"