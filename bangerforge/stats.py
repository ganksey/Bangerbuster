"""Per-game stat computation — the heart of BangerForge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import streamlit as st

from bangerforge.config import CURRENT_SEASON_STR, DEFAULT_BANGER_WEIGHTS
from bangerforge.roster_constants import (
    DEFAULT_ROLLING_GAMES,
    DEFAULT_SEASON_START,
    PRIOR_SEASON_INT,
    PRIOR_SEASON_STR,
)
from bangerforge.models import PerGameStats, PlayerProfile
from bangerforge.utils import normalize_position
from bangerforge.nhl_client import (
    _parse_toi_minutes,
    fetch_game_banger_stats,
    fetch_goalie_game_log,
    fetch_goalie_summary_bulk,
    fetch_player_landing,
    fetch_skater_game_log,
    fetch_skater_realtime_bulk,
    fetch_skater_summary_bulk,
)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


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


def _sum_hits_blocks_for_games(player_id: int, games: list[dict]) -> tuple[int, int]:
    """Aggregate hits/blocks from boxscores for specific games."""
    game_ids = sorted({int(g["gameId"]) for g in games if g.get("gameId")})
    if not game_ids:
        return 0, 0

    hits = 0
    blocks = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_game_banger_stats, gid): gid for gid in game_ids}
        for future in as_completed(futures):
            try:
                box = future.result()
            except Exception:  # noqa: BLE001
                continue
            row = box.get(player_id, {})
            hits += int(row.get("hits", 0))
            blocks += int(row.get("blocks", 0))
    return hits, blocks


def _skater_rates_from_logs(
    player_id: int,
    logs: list[dict],
    *,
    source: str,
    hits_blocks_from_boxscores: bool = False,
    realtime_season: int | None = None,
) -> PerGameStats:
    gp = len(logs)
    if gp == 0:
        return PerGameStats(source=source, games_played=0)

    totals = {
        "goals": sum(g.get("goals", 0) for g in logs),
        "assists": sum(g.get("assists", 0) for g in logs),
        "points": sum(g.get("points", 0) for g in logs),
        "ppp": sum(g.get("powerPlayPoints", 0) for g in logs),
        "shots": sum(g.get("shots", 0) for g in logs),
        "pim": sum(g.get("pim", 0) for g in logs),
    }

    if hits_blocks_from_boxscores:
        hits, blocks = _sum_hits_blocks_for_games(player_id, logs)
    elif realtime_season is not None:
        realtime = fetch_skater_realtime_bulk(season=realtime_season).get(player_id, {})
        rt_gp = max(int(realtime.get("gamesPlayed", 0)), gp, 1)
        hits = int(realtime.get("hits", 0))
        blocks = int(realtime.get("blockedShots", 0))
        hits = int(_safe_div(hits, rt_gp) * gp)
        blocks = int(_safe_div(blocks, rt_gp) * gp)
    else:
        hits, blocks = 0, 0

    return PerGameStats(
        goals_pg=_safe_div(totals["goals"], gp),
        assists_pg=_safe_div(totals["assists"], gp),
        points_pg=_safe_div(totals["points"], gp),
        ppp_pg=_safe_div(totals["ppp"], gp),
        shots_pg=_safe_div(totals["shots"], gp),
        hits_pg=_safe_div(hits, gp),
        blocks_pg=_safe_div(blocks, gp),
        pim_pg=_safe_div(totals["pim"], gp),
        games_played=gp,
        season_goals=totals["goals"],
        season_assists=totals["assists"],
        season_points=totals["points"],
        season_games=gp,
        source=source,
    )


def _goalie_rates_from_logs(logs: list[dict], *, source: str) -> PerGameStats:
    gp = len(logs)
    if gp == 0:
        return PerGameStats(source=source, games_played=0)

    wins = sum(1 for g in logs if g.get("decision") == "W")
    saves = sum(int(g.get("shotsAgainst", 0)) - int(g.get("goalsAgainst", 0)) for g in logs)
    shots = sum(int(g.get("shotsAgainst", 0)) for g in logs)
    ga = sum(int(g.get("goalsAgainst", 0)) for g in logs)
    shutouts = sum(int(g.get("shutouts", 0)) for g in logs)
    toi_min = sum(_parse_toi_minutes(g.get("toi", "0:00")) for g in logs)

    return PerGameStats(
        wins_pg=_safe_div(wins, gp),
        saves_pg=_safe_div(saves, gp),
        save_pct=_safe_div(saves, shots),
        gaa=_safe_div(ga, toi_min / 60.0) if toi_min else 0.0,
        shutouts_pg=_safe_div(shutouts, gp),
        games_played=gp,
        season_games=gp,
        source=source,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_skater_prior_season_stats(player_id: int) -> PerGameStats:
    """Per-game rates from full 2024-25 regular season."""
    logs = fetch_skater_game_log(player_id, season=PRIOR_SEASON_STR)
    return _skater_rates_from_logs(
        player_id,
        logs,
        source="prior_season",
        realtime_season=PRIOR_SEASON_INT,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_goalie_prior_season_stats(player_id: int) -> PerGameStats:
    """Goalie per-game rates from full 2024-25 regular season."""
    logs = fetch_goalie_game_log(player_id, season=PRIOR_SEASON_STR)
    starts = [
        g for g in logs
        if g.get("gamesStarted") or int(g.get("shotsAgainst", 0)) > 0
    ]
    return _goalie_rates_from_logs(starts, source="prior_season")


@st.cache_data(ttl=1800, show_spinner=False)
def compute_skater_rolling_stats(player_id: int, sample: int = DEFAULT_ROLLING_GAMES) -> PerGameStats:
    """Per-game rates from last N regular-season games (current season)."""
    logs = fetch_skater_game_log(player_id, season=CURRENT_SEASON_STR)
    recent = logs[:sample]
    return _skater_rates_from_logs(
        player_id,
        recent,
        source="rolling_25",
        hits_blocks_from_boxscores=True,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def compute_goalie_rolling_stats(player_id: int, sample: int = DEFAULT_ROLLING_GAMES) -> PerGameStats:
    """Goalie per-game rates from last N starts (current season)."""
    logs = fetch_goalie_game_log(player_id, season=CURRENT_SEASON_STR)
    starts = [
        g for g in logs
        if g.get("gamesStarted") or int(g.get("shotsAgainst", 0)) > 0
    ]
    return _goalie_rates_from_logs(starts[:sample], source="rolling_25")


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


def _roster_display_stats(
    player_id: int,
    is_goalie: bool,
    stat_mode: str,
    rolling_n: int,
) -> PerGameStats:
    if stat_mode == "rolling_25":
        if is_goalie:
            return compute_goalie_rolling_stats(player_id, rolling_n)
        return compute_skater_rolling_stats(player_id, rolling_n)
    if is_goalie:
        return compute_goalie_prior_season_stats(player_id)
    return compute_skater_prior_season_stats(player_id)


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


@st.cache_data(ttl=900, show_spinner=False)
def build_roster_player_profile(
    player_id: int,
    name: str,
    pos: str,
    team: str,
    projected_games: int = 0,
    weights: tuple[tuple[str, float], ...] = (),
    schedule_boost: float = 1.0,
    notes: str = "",
    stat_mode: str = "prior_season",
    rolling_n: int = DEFAULT_ROLLING_GAMES,
    stat_label: str = "",
) -> PlayerProfile:
    """Profile for roster tabs — stats from prior season or rolling sample."""
    is_goalie = pos.upper() == "G"
    wdict = dict(weights) if weights else dict(DEFAULT_BANGER_WEIGHTS)

    display = _roster_display_stats(player_id, is_goalie, stat_mode, rolling_n)

    if is_goalie:
        recent = compute_goalie_recent_stats(player_id, 10)
        season = compute_goalie_season_stats(player_id)
    else:
        recent = compute_skater_recent_stats(player_id, 10)
        season = compute_skater_season_stats(player_id)

    pg = projected_games or 1
    score = banger_score(display, wdict, pg, is_goalie, schedule_boost)

    return PlayerProfile(
        player_id=player_id,
        name=name,
        pos=normalize_position(pos),
        team=team,
        is_goalie=is_goalie,
        recent=recent,
        season=season,
        window=display,
        projected_games_week=projected_games,
        banger_score=score,
        stat_label=stat_label,
        data_fetched=display.games_played > 0,
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