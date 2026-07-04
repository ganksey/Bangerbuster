"""JSON persistence for rosters, settings, and opponent history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bangerforge.config import DATA_DIR, DEFAULT_KEEPERS, DEFAULT_SETTINGS
from bangerforge.roster_constants import LEAGUE_ROSTER_SIZE
from bangerforge.models import RosterEntry
from bangerforge.opponents import (
    get_active_opponent_id,
    get_opponent_roster,
    migrate_legacy_opponent_file,
    save_opponent_roster,
)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_settings() -> dict[str, Any]:
    data = _read_json(DATA_DIR / "settings.json", DEFAULT_SETTINGS.copy())
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data)
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(DATA_DIR / "settings.json", settings)


def load_my_roster() -> list[RosterEntry]:
    raw = _read_json(DATA_DIR / "my_roster.json", None)
    if raw is None:
        return [RosterEntry.from_dict(k) for k in DEFAULT_KEEPERS]
    return [RosterEntry.from_dict(r) for r in raw]


def save_my_roster(roster: list[RosterEntry]) -> None:
    capped = roster[:LEAGUE_ROSTER_SIZE]
    _write_json(DATA_DIR / "my_roster.json", [r.to_dict() for r in capped])


def load_opponent_current() -> list[RosterEntry]:
    migrate_legacy_opponent_file()
    oid = get_active_opponent_id()
    if oid:
        return get_opponent_roster(oid)
    raw = _read_json(DATA_DIR / "opponent_roster.json", [])
    return [RosterEntry.from_dict(r) for r in raw[:LEAGUE_ROSTER_SIZE]]


def save_opponent_current(roster: list[RosterEntry]) -> None:
    migrate_legacy_opponent_file()
    oid = get_active_opponent_id()
    if oid:
        save_opponent_roster(oid, roster)
        return
    _write_json(
        DATA_DIR / "opponent_roster.json",
        [r.to_dict() for r in roster[:LEAGUE_ROSTER_SIZE]],
    )


def load_opponent_history() -> dict[str, list[dict[str, Any]]]:
    return _read_json(DATA_DIR / "opponent_weeks.json", {})


def save_opponent_week(week_label: str, roster: list[RosterEntry]) -> None:
    history = load_opponent_history()
    history[week_label] = [r.to_dict() for r in roster]
    _write_json(DATA_DIR / "opponent_weeks.json", history)


def load_waiver_agents() -> list[str]:
    return _read_json(DATA_DIR / "waiver_agents.json", [])


def save_waiver_agents(names: list[str]) -> None:
    _write_json(DATA_DIR / "waiver_agents.json", names)


def load_weekly_plan() -> str:
    return _read_json(DATA_DIR / "weekly_plan.json", {}).get("plan", "")


def save_weekly_plan(plan_text: str) -> None:
    _write_json(DATA_DIR / "weekly_plan.json", {"plan": plan_text})