"""NHL API client with caching and error handling."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from bangerforge.config import (
    CURRENT_SEASON_STR,
    DATA_DIR,
    NHL_STATS_BASE,
    NHL_TEAMS,
    NHL_WEB_BASE,
)
from bangerforge.utils import normalize_position

REQUEST_TIMEOUT = 25
MAX_RETRIES = 3
RETRY_DELAY = 1.5

# Shipped with repo so first run does not hit 32 roster endpoints
BUNDLED_PLAYER_CACHE = Path(__file__).resolve().parent / "player_cache_seed.json"


class NHLAPIError(Exception):
    """Raised when NHL API calls fail after retries."""


def _request_json(url: str) -> Any:
    """GET JSON with retries and rate-limit backoff."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                time.sleep(RETRY_DELAY * (attempt + 2))
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(RETRY_DELAY * (attempt + 1))
    raise NHLAPIError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_err


def _load_disk_cache(filename: str) -> dict[str, Any] | None:
    path = DATA_DIR / filename
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") == CURRENT_SEASON_STR:
            return payload.get("data")
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    return None


def _save_disk_cache(filename: str, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    path.write_text(
        json.dumps({"version": CURRENT_SEASON_STR, "data": data}, indent=2),
        encoding="utf-8",
    )


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_player_landing(player_id: int) -> dict[str, Any]:
    """Player bio and featured season stats."""
    return _request_json(f"{NHL_WEB_BASE}/player/{player_id}/landing")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_skater_game_log(player_id: int, season: str = CURRENT_SEASON_STR) -> list[dict[str, Any]]:
    """Regular-season skater game log."""
    data = _request_json(f"{NHL_WEB_BASE}/player/{player_id}/game-log/{season}/2")
    return data.get("gameLog", [])


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_goalie_game_log(player_id: int, season: str = CURRENT_SEASON_STR) -> list[dict[str, Any]]:
    """Regular-season goalie game log."""
    data = _request_json(f"{NHL_WEB_BASE}/player/{player_id}/game-log/{season}/2")
    return data.get("gameLog", [])


def _fetch_bulk_stats(endpoint: str, cache_file: str, season: int = 20252026) -> dict[int, dict[str, Any]]:
    """Fetch skater/goalie bulk stats with disk persistence."""
    cached = _load_disk_cache(cache_file)
    if cached is not None:
        return {int(k): v for k, v in cached.items()}

    url = (
        f"{NHL_STATS_BASE}/{endpoint}"
        f"?cayenneExp=seasonId={season}%20and%20gameTypeId=2"
        f"&limit=-1"
    )
    data = _request_json(url)
    result = {int(row["playerId"]): row for row in data.get("data", [])}
    _save_disk_cache(cache_file, {str(k): v for k, v in result.items()})
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_skater_realtime_bulk(season: int = 20252026) -> dict[int, dict[str, Any]]:
    """Hits/blocks season totals keyed by player_id."""
    return _fetch_bulk_stats("skater/realtime", "skater_realtime_cache.json", season)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_skater_summary_bulk(season: int = 20252026) -> dict[int, dict[str, Any]]:
    """Skater summary stats keyed by player_id."""
    return _fetch_bulk_stats("skater/summary", "skater_summary_cache.json", season)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_goalie_summary_bulk(season: int = 20252026) -> dict[int, dict[str, Any]]:
    """Goalie summary stats keyed by player_id."""
    return _fetch_bulk_stats("goalie/summary", "goalie_summary_cache.json", season)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_team_roster(team: str, season: str = CURRENT_SEASON_STR) -> list[dict[str, Any]]:
    """Active roster players for a team."""
    data = _request_json(f"{NHL_WEB_BASE}/roster/{team}/{season}")
    players: list[dict[str, Any]] = []
    for group in ("forwards", "defensemen", "goalies"):
        for p in data.get(group, []):
            first = p.get("firstName", {}).get("default", "")
            last = p.get("lastName", {}).get("default", "")
            pos = normalize_position(p.get("positionCode", "C"))
            players.append({
                "player_id": p["id"],
                "name": f"{first} {last}".strip(),
                "pos": pos,
                "team": team,
            })
    return players


def _load_player_cache_file(path: Path) -> dict[str, dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("version") == CURRENT_SEASON_STR and cached.get("players"):
            return cached["players"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def build_player_directory() -> dict[str, dict[str, Any]]:
    """Name -> player info cache from all NHL rosters."""
    cache_path = DATA_DIR / "player_cache.json"
    for path in (cache_path, BUNDLED_PLAYER_CACHE):
        loaded = _load_player_cache_file(path)
        if loaded:
            if path == BUNDLED_PLAYER_CACHE and not cache_path.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"version": CURRENT_SEASON_STR, "players": loaded}, indent=2),
                    encoding="utf-8",
                )
            return loaded

    directory: dict[str, dict[str, Any]] = {}
    for team in NHL_TEAMS:
        try:
            for p in fetch_team_roster(team):
                key = p["name"].lower()
                directory[key] = p
                directory[str(p["player_id"])] = p
        except NHLAPIError:
            continue

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"version": CURRENT_SEASON_STR, "players": directory}, indent=2),
        encoding="utf-8",
    )
    return directory


def search_players(query: str, limit: int = 15) -> list[dict[str, Any]]:
    """Fuzzy search players by name."""
    directory = build_player_directory()
    names = [k for k in directory if not k.isdigit()]
    matches = get_close_matches(query.lower(), names, n=limit, cutoff=0.45)
    if not matches:
        matches = [n for n in names if query.lower() in n][:limit]
    return [directory[m] for m in matches]


def resolve_player(name: str) -> dict[str, Any] | None:
    """Resolve a player name to directory entry."""
    if not name or not str(name).strip():
        return None
    directory = build_player_directory()
    key = name.strip().lower()
    if key in directory:
        return directory[key]
    hits = search_players(name, limit=1)
    return hits[0] if hits else None


def _parse_toi_minutes(toi: str) -> float:
    """Convert '18:28' TOI string to minutes."""
    if not toi or ":" not in str(toi):
        return 0.0
    parts = str(toi).split(":")
    try:
        return int(parts[0]) + int(parts[1]) / 60.0
    except (ValueError, IndexError):
        return 0.0


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_schedule_range(start: str, end: str) -> dict[str, list[str]]:
    """Map team abbrev -> unique game dates in [start, end]."""
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    team_dates: dict[str, set[str]] = {t: set() for t in NHL_TEAMS}
    cursor = start_d
    while cursor <= end_d:
        try:
            sched = _request_json(f"{NHL_WEB_BASE}/schedule/{cursor.isoformat()}")
            for day in sched.get("gameWeek", []):
                gdate = day.get("date")
                if not gdate or gdate < start or gdate > end:
                    continue
                for game in day.get("games", []):
                    away = game.get("awayTeam", {}).get("abbrev")
                    home = game.get("homeTeam", {}).get("abbrev")
                    if away in team_dates:
                        team_dates[away].add(gdate)
                    if home in team_dates:
                        team_dates[home].add(gdate)
        except NHLAPIError:
            pass
        cursor += timedelta(days=1)
    return {team: sorted(dates) for team, dates in team_dates.items()}


def count_team_games_in_week(team: str, start: str, end: str) -> int:
    """Games for a team during fantasy week."""
    sched = fetch_schedule_range(start, end)
    return len(sched.get(team, []))


def fantasy_week_bounds(
    week_start: date | None = None,
    start_dow: int = 0,
) -> tuple[str, str]:
    """Return (start, end) ISO dates for current fantasy week (Mon-Sun default)."""
    today = week_start or date.today()
    delta = (today.weekday() - start_dow) % 7
    start = today - timedelta(days=delta)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()