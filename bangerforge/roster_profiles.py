"""Roster tab NHL profile loading — standalone module for app.py."""

from __future__ import annotations

from typing import Any

from bangerforge.models import PlayerProfile, RosterEntry
from bangerforge.nhl_client import count_team_games_in_week
from bangerforge.roster_stat_mode import resolve_roster_stat_mode, roster_stat_label
from bangerforge.stats import build_roster_player_profile


def _schedule_boost(games: int, settings: dict[str, Any]) -> float:
    if games >= 4:
        return float(settings.get("schedule_boost_4g", 1.08))
    if games >= 3:
        return float(settings.get("schedule_boost_3g", 1.03))
    return 1.0


def enrich_roster_tab_profiles(
    roster: list[RosterEntry],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
) -> list[PlayerProfile]:
    """Build roster-tab profiles; NHL data fetched per player on roster."""
    weights = settings.get("banger_weights", {})
    w_tuple = tuple(weights.items())
    stat_mode = resolve_roster_stat_mode(settings)
    label = roster_stat_label(stat_mode, settings)
    rolling_n = int(settings.get("rolling_games_sample", 25))

    profiles: list[PlayerProfile] = []
    for entry in roster:
        if not entry.player_id:
            continue
        games = count_team_games_in_week(entry.team, week_start, week_end)
        boost = _schedule_boost(games, settings)
        profiles.append(build_roster_player_profile(
            entry.player_id,
            entry.name,
            entry.pos,
            entry.team,
            projected_games=games,
            weights=w_tuple,
            schedule_boost=boost,
            notes=entry.notes,
            stat_mode=stat_mode,
            rolling_n=rolling_n,
            stat_label=label,
        ))
    return profiles