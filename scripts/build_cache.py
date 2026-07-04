"""One-time script to build shipped NHL caches. Run before committing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bangerforge.config import CURRENT_SEASON_STR, DATA_DIR, NHL_TEAMS
from bangerforge.nhl_client import (
    _fetch_bulk_stats,
    _request_json,
    fetch_team_roster,
)
from bangerforge.utils import normalize_position

BUNDLED = ROOT / "bangerforge" / "player_cache_seed.json"


def build_player_directory() -> dict[str, dict]:
    directory: dict[str, dict] = {}
    for team in NHL_TEAMS:
        print(f"Roster {team}...")
        for p in fetch_team_roster(team):
            entry = {
                "player_id": p["player_id"],
                "name": p["name"],
                "pos": normalize_position(p["pos"]),
                "team": p["team"],
            }
            directory[p["name"].lower()] = entry
            directory[str(p["player_id"])] = entry
    return directory


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Building bulk stat caches...")
    _fetch_bulk_stats("skater/realtime", "skater_realtime_cache.json")
    _fetch_bulk_stats("skater/summary", "skater_summary_cache.json")
    _fetch_bulk_stats("goalie/summary", "goalie_summary_cache.json")
    print("Building player directory...")
    players = build_player_directory()
    payload = {"version": CURRENT_SEASON_STR, "players": players}
    BUNDLED.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (DATA_DIR / "player_cache.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Done — {len([k for k in players if not k.isdigit()])} players cached.")


if __name__ == "__main__":
    main()