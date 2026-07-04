"""Add/drop and weekly planning optimizers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bangerforge.models import MoveRecommendation, PlayerProfile, RosterEntry
from bangerforge.nhl_client import count_team_games_in_week, resolve_player
from bangerforge.stats import build_player_profile


def parse_name_list(text: str) -> list[str]:
    """Parse newline or comma separated player names."""
    raw = text.replace(",", "\n").split("\n")
    return [n.strip() for n in raw if n.strip()]


def rank_waiver_targets(
    names: list[str],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
    limit: int = 5,
) -> list[PlayerProfile]:
    """Rank free agents by banger score with schedule boost."""
    from bangerforge.projections import schedule_boost

    weights = settings.get("banger_weights", {})
    recent_window = int(settings.get("recent_games_window", 10))
    w_tuple = tuple(weights.items())
    profiles: list[PlayerProfile] = []

    for name in names:
        hit = resolve_player(name)
        if not hit:
            continue
        games = count_team_games_in_week(hit["team"], week_start, week_end)
        boost = schedule_boost(games, settings)
        profiles.append(build_player_profile(
            hit["player_id"],
            hit["name"],
            hit["pos"],
            hit["team"],
            recent_window=recent_window,
            projected_games=games,
            weights=w_tuple,
            schedule_boost=boost,
        ))

    return sorted(profiles, key=lambda p: p.banger_score, reverse=True)[:limit]


def suggest_five_moves(
    my_profiles: list[PlayerProfile],
    opp_profiles: list[PlayerProfile],
    waiver_profiles: list[PlayerProfile],
    matchups: list[Any],
    week_start: str,
) -> list[MoveRecommendation]:
    """Generate up to 5 add/drop moves targeting weakest categories."""
    weak_cats = [m.category for m in matchups if m.status == "lose"][:3]
    cat_weights = {
        "hits_pg": 3.0, "blocks_pg": 3.0, "pim_pg": 2.0,
        "shots_pg": 1.5, "points_pg": 1.0, "goals_pg": 1.0,
    }

    droppable = sorted(my_profiles, key=lambda p: p.banger_score)
    adds = sorted(
        waiver_profiles,
        key=lambda p: sum(
            p.season.get(c) * cat_weights.get(c, 1.0) for c in weak_cats
        ),
        reverse=True,
    )

    moves: list[MoveRecommendation] = []
    start = datetime.strptime(week_start, "%Y-%m-%d")
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    for i in range(min(5, len(adds), len(droppable))):
        add_p = adds[i]
        drop_p = droppable[i]
        day = days[min(i, 6)]
        move_date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        reason = (
            f"Boost {', '.join(weak_cats) or 'volume'} — "
            f"{add_p.name} ({add_p.projected_games_week}G, BS {add_p.banger_score}) "
            f"over {drop_p.name} (BS {drop_p.banger_score})"
        )
        moves.append(MoveRecommendation(
            day=f"{day} ({move_date})",
            add_name=add_p.name,
            drop_name=drop_p.name,
            reason=reason,
            lineup_note=f"Start {add_p.name} in {add_p.pos} slot",
        ))
    return moves


def daily_lineup_suggestion(profiles: list[PlayerProfile]) -> dict[str, list[str]]:
    """Best active lineup by position for today."""
    from bangerforge.projections import select_best_lineup

    lineup = select_best_lineup(profiles)
    grouped: dict[str, list[str]] = {"C": [], "LW": [], "RW": [], "D": [], "G": []}
    for p in lineup:
        grouped.setdefault(p.pos, []).append(
            f"{p.name} ({p.projected_games_week}G, {p.banger_score:.1f} BS)"
        )
    return grouped


def build_week_plan_text(moves: list[MoveRecommendation], lineup: dict[str, list[str]]) -> str:
    """Exportable weekly plan."""
    lines = ["# BangerForge Weekly Plan", ""]
    for m in moves:
        lines.append(f"## {m.day}")
        lines.append(f"- ADD: {m.add_name}")
        lines.append(f"- DROP: {m.drop_name}")
        lines.append(f"- Reason: {m.reason}")
        lines.append(f"- Lineup: {m.lineup_note}")
        lines.append("")
    lines.append("## Optimal Lineup")
    for pos, players in lineup.items():
        lines.append(f"**{pos}**: " + ", ".join(players) if players else f"**{pos}**: —")
    lines.append("")
    lines.append("*Projections use current-season per-game rates × scheduled games. Variance exists.*")
    return "\n".join(lines)