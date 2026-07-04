"""Named opponent registry — you manage names, we manage fetched stats."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bangerforge.config import DATA_DIR
from bangerforge.roster_constants import LEAGUE_ROSTER_SIZE
from bangerforge.models import RosterEntry
from bangerforge.nhl_client import resolve_player
from bangerforge.utils import normalize_position


def _registry_path() -> Path:
    return DATA_DIR / "opponents_registry.json"


def _empty_registry() -> dict[str, Any]:
    return {"active_id": "", "opponents": {}}


def _read_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("opponents", {})
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_registry()


def _write_registry(data: dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "opponent"
    return base[:40]


def list_opponents() -> list[dict[str, Any]]:
    """All saved opponents with metadata."""
    reg = _read_registry()
    items: list[dict[str, Any]] = []
    for oid, opp in reg.get("opponents", {}).items():
        roster = opp.get("roster", [])
        items.append({
            "id": oid,
            "name": opp.get("name", oid),
            "player_count": len(roster),
            "updated": opp.get("updated", ""),
            "is_active": oid == reg.get("active_id"),
        })
    return sorted(items, key=lambda x: x.get("updated", ""), reverse=True)


def get_active_opponent_id() -> str:
    return _read_registry().get("active_id", "")


def get_opponent_roster(opponent_id: str) -> list[RosterEntry]:
    reg = _read_registry()
    opp = reg.get("opponents", {}).get(opponent_id)
    if not opp:
        return []
    return [RosterEntry.from_dict(r) for r in opp.get("roster", [])]


def set_active_opponent(opponent_id: str) -> None:
    reg = _read_registry()
    if opponent_id and opponent_id not in reg.get("opponents", {}):
        raise ValueError(f"Unknown opponent: {opponent_id}")
    reg["active_id"] = opponent_id
    _write_registry(reg)


def create_opponent(display_name: str) -> str:
    """Create empty 10-slot opponent profile."""
    reg = _read_registry()
    base = _slugify(display_name)
    oid = base
    suffix = 1
    while oid in reg["opponents"]:
        oid = f"{base}_{suffix}"
        suffix += 1
    now = datetime.now(timezone.utc).isoformat()
    reg["opponents"][oid] = {
        "name": display_name.strip(),
        "roster": [],
        "created": now,
        "updated": now,
    }
    reg["active_id"] = oid
    _write_registry(reg)
    return oid


def save_opponent_roster(opponent_id: str, roster: list[RosterEntry]) -> None:
    reg = _read_registry()
    if opponent_id not in reg.get("opponents", {}):
        raise ValueError(f"Unknown opponent: {opponent_id}")
    reg["opponents"][opponent_id]["roster"] = [r.to_dict() for r in roster[:LEAGUE_ROSTER_SIZE]]
    reg["opponents"][opponent_id]["updated"] = datetime.now(timezone.utc).isoformat()
    reg["active_id"] = opponent_id
    _write_registry(reg)


def delete_opponent(opponent_id: str) -> None:
    reg = _read_registry()
    reg.get("opponents", {}).pop(opponent_id, None)
    if reg.get("active_id") == opponent_id:
        remaining = list(reg.get("opponents", {}).keys())
        reg["active_id"] = remaining[0] if remaining else ""
    _write_registry(reg)


def names_to_roster(names: list[str], max_size: int = LEAGUE_ROSTER_SIZE) -> list[RosterEntry]:
    """Resolve pasted names to roster entries (no stats fetch yet)."""
    roster: list[RosterEntry] = []
    for raw in names[:max_size]:
        hit = resolve_player(raw.strip())
        if not hit:
            continue
        roster.append(RosterEntry(
            name=hit["name"],
            player_id=int(hit["player_id"]),
            pos=normalize_position(hit["pos"]),
            team=hit["team"],
        ))
    return roster


def migrate_legacy_opponent_file() -> None:
    """Import old opponent_roster.json into registry if registry is empty."""
    reg = _read_registry()
    if reg.get("opponents"):
        return
    legacy = DATA_DIR / "opponent_roster.json"
    if not legacy.exists():
        return
    try:
        rows = json.loads(legacy.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not rows:
        return
    oid = create_opponent("Imported Opponent")
    save_opponent_roster(oid, [RosterEntry.from_dict(r) for r in rows])