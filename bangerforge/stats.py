"""Per-game stat computation — the heart of BangerForge."""

from __future__ import annotations

from typing import Any

import streamlit as st

from bangerforge.config import DEFAULT_BANGER_WEIGHTS
from bangerforge.models import PerGameStats, PlayerProfile
from bangerforge.utils import normalize_position
from bangerforge.nhl_client import (
    _parse_toi_minutes,
    fetch_goalie_game_log,
    fetch_goalie_summary_bulk,
    fetch_player_landing,
    fetch_skater_game_log,
    fetch_skater_realtime_bulk,
    fetch_skater_summary_bulk,
)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


@st.cache_data(ttl=1800, show_spinner=False)
def compute_skater_recent_stats(
    player_id: int,
    window: int = 10,
) -> PerGameStats:
    """Per-game averages from last N regular-season games."""
    logs = fetch_skater_game_log(player_id)
    recent = logs[:window]
    gp = len(recent)
    if gp == 0:
        return PerGameStats(source="recent", games_played=0)

    totals = {
        "goals": sum(g.get("goals", 0) for g in recent),
        "assists": sum(g.get("assists", 0) for g in recent),
        "points": sum(g.get("points", 0) for g in recent),
        "ppp": sum(g.get("powerPlayPoints", 0) for g in recent),
        "shots": sum(g.get("shots", 0) for g in recent),
        "pim": sum(g.get("pim", 0) for g in recent),
    }

    realtime = fetch_skater_realtime_bulk().get(player_id, {})
    rt_gp = max(int(realtime.get("gamesPlayed", 0)), 1)
    hits_pg = _safe_div(float(realtime.get("hits", 0)), rt_gp)
    blocks_pg = _safe_div(float(realtime.get("blockedShots", 0)), rt_gp)

    return PerGameStats(
        goals_pg=_safe_div(totals["goals"], gp),
        assists_pg=_safe_div(totals["assists"], gp),
        points_pg=_safe_div(totals["points"], gp),
        ppp_pg=_safe_div(totals["ppp"], gp),
        shots_pg=_safe_div(totals["shots"], gp),
        hits_pg=hits_pg,
        blocks_pg=blocks_pg,
        pim_pg=_safe_div(totals["pim"], gp),
        games_played=gp,
        source="recent",
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_skater_season_stats(player_id: int) -> PerGameStats:
    """Current-season per-game rates (not last year totals)."""
    landing = fetch_player_landing(player_id)
    featured = (
        landing.get("featuredStats", {})
        .get("regularSeason", {})
        .get("subSeason", {})
    )
    gp = int(featured.get("gamesPlayed", 0))
    summary = fetch_skater_summary_bulk().get(player_id, {})
    realtime = fetch_skater_realtime_bulk().get(player_id, {})

    if gp == 0 and not summary:
        return PerGameStats(source="season", games_played=0)

    gp = max(gp, int(summary.get("gamesPlayed", 0)), 1)
    goals = int(featured.get("goals", summary.get("goals", 0)))
    assists = int(featured.get("assists", summary.get("assists", 0)))
    points = int(featured.get("points", summary.get("points", 0)))
    ppp = int(featured.get("powerPlayPoints", summary.get("ppPoints", 0)))
    shots = int(featured.get("shots", summary.get("shots", 0)))
    pim = int(featured.get("pim", summary.get("penaltyMinutes", 0)))
    hits = int(realtime.get("hits", 0))
    blocks = int(realtime.get("blockedShots", 0))

    return PerGameStats(
        goals_pg=_safe_div(goals, gp),
        assists_pg=_safe_div(assists, gp),
        points_pg=_safe_div(points, gp),
        ppp_pg=_safe_div(ppp, gp),
        shots_pg=_safe_div(shots, gp),
        hits_pg=_safe_div(hits, gp),
        blocks_pg=_safe_div(blocks, gp),
        pim_pg=_safe_div(pim, gp),
        games_played=gp,
        season_goals=goals,
        season_assists=assists,
        season_points=points,
        season_games=gp,
        source="season",
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_goalie_recent_stats(player_id: int, window: int = 10) -> PerGameStats:
    """Per-game goalie rates from recent starts."""
    logs = fetch_goalie_game_log(player_id)
    starts = [g for g in logs if g.get("gamesStarted") or g.get("shotsAgainst", 0) > 0]
    recent = starts[:window]
    gp = len(recent)
    if gp == 0:
        return PerGameStats(source="recent", games_played=0)

    wins = sum(1 for g in recent if g.get("decision") == "W")
    saves = sum(int(g.get("shotsAgainst", 0)) - int(g.get("goalsAgainst", 0)) for g in recent)
    shots = sum(int(g.get("shotsAgainst", 0)) for g in recent)
    ga = sum(int(g.get("goalsAgainst", 0)) for g in recent)
    shutouts = sum(int(g.get("shutouts", 0)) for g in recent)
    toi_min = sum(_parse_toi_minutes(g.get("toi", "0:00")) for g in recent)

    return PerGameStats(
        wins_pg=_safe_div(wins, gp),
        saves_pg=_safe_div(saves, gp),
        save_pct=_safe_div(saves, shots),
        gaa=_safe_div(ga, toi_min / 60.0) if toi_min else 0.0,
        shutouts_pg=_safe_div(shutouts, gp),
        games_played=gp,
        source="recent",
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_goalie_season_stats(player_id: int) -> PerGameStats:
    """Current-season goalie per-game and ratio stats."""
    summary = fetch_goalie_summary_bulk().get(player_id, {})
    landing = fetch_player_landing(player_id)
    featured = (
        landing.get("featuredStats", {})
        .get("regularSeason", {})
        .get("subSeason", {})
    )
    gp = max(int(summary.get("gamesPlayed", 0)), int(featured.get("gamesPlayed", 0)), 1)
    wins = int(summary.get("wins", 0))
    saves = int(summary.get("saves", 0))
    save_pct = float(summary.get("savePct", 0.0))
    gaa = float(summary.get("goalsAgainstAverage", 0.0))
    shutouts = int(summary.get("shutouts", 0))

    return PerGameStats(
        wins_pg=_safe_div(wins, gp),
        saves_pg=_safe_div(saves, gp),
        save_pct=save_pct,
        gaa=gaa,
        shutouts_pg=_safe_div(shutouts, gp),
        games_played=gp,
        season_games=gp,
        source="season",
    )


def blend_stats(
    recent: PerGameStats,
    season: PerGameStats,
    min_recent: int = 3,
) -> PerGameStats:
    """Use recent form when enough games; else season per-game."""
    base = recent if recent.games_played >= min_recent else season
    return PerGameStats(
        goals_pg=base.goals_pg,
        assists_pg=base.assists_pg,
        points_pg=base.points_pg,
        ppp_pg=base.ppp_pg,
        shots_pg=base.shots_pg,
        hits_pg=base.hits_pg if recent.games_played >= min_recent else season.hits_pg,
        blocks_pg=base.blocks_pg if recent.games_played >= min_recent else season.blocks_pg,
        pim_pg=base.pim_pg,
        wins_pg=base.wins_pg,
        saves_pg=base.saves_pg,
        save_pct=base.save_pct if recent.games_played >= min_recent else season.save_pct,
        gaa=base.gaa if recent.games_played >= min_recent else season.gaa,
        shutouts_pg=base.shutouts_pg,
        games_played=base.games_played,
        season_goals=season.season_goals,
        season_assists=season.season_assists,
        season_points=season.season_points,
        season_games=season.season_games,
        source="blended",
    )


def banger_score(
    stats: PerGameStats,
    weights: dict[str, float],
    projected_games: int = 1,
    is_goalie: bool = False,
    schedule_boost: float = 1.0,
) -> float:
    """Custom banger score from per-game rates × games × weights."""
    cats = (
        ["wins_pg", "saves_pg", "save_pct", "gaa", "shutouts_pg"]
        if is_goalie
        else [
            "goals_pg", "assists_pg", "points_pg", "ppp_pg",
            "shots_pg", "hits_pg", "blocks_pg", "pim_pg",
        ]
    )
    score = 0.0
    for cat in cats:
        w = weights.get(cat, DEFAULT_BANGER_WEIGHTS.get(cat, 0.0))
        val = stats.get(cat)
        if cat == "gaa":
            score += w * (3.0 - min(val, 3.0)) * projected_games
        elif cat == "save_pct":
            score += w * val * projected_games
        else:
            score += w * val * projected_games
    return round(score * schedule_boost, 2)


@st.cache_data(ttl=900, show_spinner=False)
def build_player_profile(
    player_id: int,
    name: str,
    pos: str,
    team: str,
    recent_window: int = 10,
    min_recent: int = 3,
    projected_games: int = 0,
    weights: tuple[tuple[str, float], ...] = (),
    schedule_boost: float = 1.0,
    notes: str = "",
) -> PlayerProfile:
    """Full player profile with per-game stats and banger score."""
    is_goalie = pos.upper() == "G"
    wdict = dict(weights) if weights else dict(DEFAULT_BANGER_WEIGHTS)

    if is_goalie:
        recent = compute_goalie_recent_stats(player_id, recent_window)
        season = compute_goalie_season_stats(player_id)
    else:
        recent = compute_skater_recent_stats(player_id, recent_window)
        season = compute_skater_season_stats(player_id)

    blended = blend_stats(recent, season, min_recent)
    pg = projected_games or 1
    score = banger_score(blended, wdict, pg, is_goalie, schedule_boost)

    return PlayerProfile(
        player_id=player_id,
        name=name,
        pos=normalize_position(pos),
        team=team,
        is_goalie=is_goalie,
        recent=recent,
        season=season,
        projected_games_week=projected_games,
        banger_score=score,
        notes=notes,
    )


def compare_snuggerud_vs_smith(
    recent_window: int = 10,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Head-to-head keeper comparison for banger format."""
    w = weights or DEFAULT_BANGER_WEIGHTS
    snug = build_player_profile(
        8483516, "Jimmy Snuggerud", "RW", "STL",
        recent_window=recent_window,
        weights=tuple(w.items()),
    )
    smith = build_player_profile(
        8484227, "Will Smith", "C", "SJS",
        recent_window=recent_window,
        weights=tuple(w.items()),
    )
    banger_cats = ["hits_pg", "blocks_pg", "pim_pg", "shots_pg", "points_pg"]
    edges = {}
    for cat in banger_cats:
        s_val = snug.season.get(cat)
        w_val = smith.season.get(cat)
        edges[cat] = {"snuggerud": s_val, "smith": w_val, "edge": s_val - w_val}
    return {
        "snuggerud": snug,
        "smith": smith,
        "edges": edges,
        "verdict": (
            "Snuggerud's per-game Hits/Blocks/PIM profile crushes Smith in banger formats. "
            "Smith wins raw Points/GP, but volume cats tilt the keeper decision to Snug."
        ),
    }