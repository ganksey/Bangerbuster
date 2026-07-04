"""Weekly projection and matchup analysis."""

from __future__ import annotations

from typing import Any

from bangerforge.config import CATEGORY_LABELS, LOWER_IS_BETTER, ROSTER_SLOTS
from bangerforge.models import CategoryMatchup, PlayerProfile, RosterEntry
from bangerforge.nhl_client import count_team_games_in_week
from bangerforge.stats import (
    build_player_profile,
    build_roster_player_profile,
    resolve_roster_stat_mode,
    roster_stat_label,
)


def schedule_boost(games: int, settings: dict[str, Any]) -> float:
    """Volume boost for players with heavy schedules."""
    if games >= 4:
        return float(settings.get("schedule_boost_4g", 1.08))
    if games >= 3:
        return float(settings.get("schedule_boost_3g", 1.03))
    return 1.0


def enrich_roster_profiles(
    roster: list[RosterEntry],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
) -> list[PlayerProfile]:
    """Build full profiles for a roster list."""
    weights = settings.get("banger_weights", {})
    recent_window = int(settings.get("recent_games_window", 10))
    min_recent = int(settings.get("min_games_for_recent", 3))
    w_tuple = tuple(weights.items())

    profiles: list[PlayerProfile] = []
    for entry in roster:
        if not entry.player_id:
            continue
        games = count_team_games_in_week(entry.team, week_start, week_end)
        boost = schedule_boost(games, settings)
        profile = build_player_profile(
            entry.player_id,
            entry.name,
            entry.pos,
            entry.team,
            recent_window=recent_window,
            min_recent=min_recent,
            projected_games=games,
            weights=w_tuple,
            schedule_boost=boost,
            notes=entry.notes,
        )
        profiles.append(profile)
    return profiles


def enrich_roster_display_profiles(
    roster: list[RosterEntry],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
) -> list[PlayerProfile]:
    """Roster-tab profiles — NHL data fetched per loaded player only."""
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
        boost = schedule_boost(games, settings)
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


def enrich_roster_window_profiles(
    roster: list[RosterEntry],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
) -> list[PlayerProfile]:
    """Backward-compatible alias for roster display enrichment."""
    return enrich_roster_display_profiles(roster, week_start, week_end, settings)


def project_category_totals(
    profiles: list[PlayerProfile],
    categories: list[str],
    use_active_lineup: bool = False,
) -> dict[str, float]:
    """Sum projected week totals per category from per-game rates × games."""
    totals: dict[str, float] = {c: 0.0 for c in categories}
    active = profiles
    if use_active_lineup:
        active = select_best_lineup(profiles)

    for p in active:
        rates = p.recent if p.recent.games_played >= 3 else p.season
        g = max(p.projected_games_week, 0)
        for cat in categories:
            if cat in ("save_pct", "gaa"):
                totals[cat] += rates.get(cat)
            else:
                totals[cat] += rates.get(cat) * g
    if "save_pct" in totals and active:
        goalies = [p for p in active if p.is_goalie]
        if goalies:
            totals["save_pct"] = sum(
                (g.recent if g.recent.games_played >= 2 else g.season).save_pct
                for g in goalies
            ) / len(goalies)
    if "gaa" in totals and active:
        goalies = [p for p in active if p.is_goalie]
        if goalies:
            totals["gaa"] = sum(
                (g.recent if g.recent.games_played >= 2 else g.season).gaa
                for g in goalies
            ) / len(goalies)
    return totals


def category_matchups(
    mine: dict[str, float],
    theirs: dict[str, float],
    categories: list[str],
    tossup_pct: float = 0.05,
) -> list[CategoryMatchup]:
    """Compare category projections."""
    results: list[CategoryMatchup] = []
    for cat in categories:
        m = mine.get(cat, 0.0)
        t = theirs.get(cat, 0.0)
        lower_better = cat in LOWER_IS_BETTER
        if lower_better:
            delta = t - m
            win = m < t
        else:
            delta = m - t
            win = m > t
        denom = max(abs(m), abs(t), 0.01)
        tossup = abs(delta) / denom < tossup_pct
        status = "tossup" if tossup else ("win" if win else "lose")
        results.append(CategoryMatchup(
            category=cat,
            label=CATEGORY_LABELS.get(cat, cat),
            mine=m,
            theirs=t,
            delta=delta,
            status=status,
            lower_is_better=lower_better,
        ))
    return results


def attack_and_protect_plans(
    matchups: list[CategoryMatchup],
) -> tuple[list[str], list[str]]:
    """Recommend categories to attack vs protect."""
    losses = sorted(
        [m for m in matchups if m.status == "lose"],
        key=lambda x: abs(x.delta),
        reverse=True,
    )
    tossups = [m for m in matchups if m.status == "tossup"]
    wins = [m for m in matchups if m.status == "win"]

    attack = [
        f"**{m.label}** — you're down {abs(m.delta):.1f} projected. "
        f"Target streamers who boost this per-game rate."
        for m in losses[:5]
    ]
    protect = [
        f"**{m.label}** — slim {m.delta:+.1f} edge. Hold steady, prioritize starts."
        for m in tossups[:3]
    ] + [
        f"**{m.label}** — winning by {m.delta:.1f}. Don't chase marginal gains here."
        for m in sorted(wins, key=lambda x: x.delta, reverse=True)[:2]
    ]
    return attack, protect


def select_best_lineup(profiles: list[PlayerProfile]) -> list[PlayerProfile]:
    """Greedy lineup respecting 3C/3LW/3RW/5D/2G by banger score."""
    by_pos: dict[str, list[PlayerProfile]] = {k: [] for k in ROSTER_SLOTS}
    for p in profiles:
        pos = p.pos if p.pos in ROSTER_SLOTS else "C"
        if p.is_goalie:
            pos = "G"
        by_pos.setdefault(pos, []).append(p)

    lineup: list[PlayerProfile] = []
    for pos, limit in ROSTER_SLOTS.items():
        ranked = sorted(by_pos.get(pos, []), key=lambda x: x.banger_score, reverse=True)
        lineup.extend(ranked[:limit])
    return lineup