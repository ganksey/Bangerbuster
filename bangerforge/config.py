"""BangerForge configuration and league constants."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# NHL API
NHL_WEB_BASE = "https://api-web.nhle.com/v1"
NHL_STATS_BASE = "https://api.nhle.com/stats/rest/en"
CURRENT_SEASON = 20252026
CURRENT_SEASON_STR = "20252026"

# Fantasy roster slots
ROSTER_SLOTS = {
    "C": 3,
    "LW": 3,
    "RW": 3,
    "D": 5,
    "G": 2,
}

NHL_TEAMS = [
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI", "NYR", "OTT",
    "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
    "WSH", "WPG",
]

SKATER_CATEGORIES = [
    "goals_pg",
    "assists_pg",
    "points_pg",
    "ppp_pg",
    "shots_pg",
    "hits_pg",
    "blocks_pg",
    "pim_pg",
]

GOALIE_CATEGORIES = [
    "wins_pg",
    "saves_pg",
    "save_pct",
    "gaa",
    "shutouts_pg",
]

CATEGORY_LABELS: dict[str, str] = {
    "goals_pg": "Goals/GP",
    "assists_pg": "Assists/GP",
    "points_pg": "Points/GP",
    "ppp_pg": "PPP/GP",
    "shots_pg": "Shots/GP",
    "hits_pg": "Hits/GP",
    "blocks_pg": "Blocks/GP",
    "pim_pg": "PIM/GP",
    "wins_pg": "Wins/GP",
    "saves_pg": "Saves/GP",
    "save_pct": "Save%",
    "gaa": "GAA",
    "shutouts_pg": "Shutouts/GP",
}

# Lower is better for GAA
LOWER_IS_BETTER = {"gaa"}

DEFAULT_BANGER_WEIGHTS: dict[str, float] = {
    "goals_pg": 1.0,
    "assists_pg": 1.0,
    "points_pg": 1.2,
    "ppp_pg": 1.1,
    "shots_pg": 0.9,
    "hits_pg": 2.5,
    "blocks_pg": 3.0,
    "pim_pg": 0.6,
    "wins_pg": 2.0,
    "saves_pg": 0.05,
    "save_pct": 50.0,
    "gaa": -3.0,
    "shutouts_pg": 4.0,
}

DEFAULT_SETTINGS: dict = {
    "recent_games_window": 10,
    "min_games_for_recent": 3,
    "schedule_boost_4g": 1.08,
    "schedule_boost_3g": 1.03,
    "active_skater_categories": SKATER_CATEGORIES.copy(),
    "active_goalie_categories": GOALIE_CATEGORIES.copy(),
    "banger_weights": DEFAULT_BANGER_WEIGHTS.copy(),
    "fantasy_week_start_dow": 0,  # Monday
    "theme": "dark",
    "current_week_number": 13,
    "demo_mode": False,
}


class KeeperSpec(TypedDict):
    name: str
    player_id: int
    pos: str
    team: str
    notes: str


DEFAULT_KEEPERS: list[KeeperSpec] = [
    {"name": "Jack Hughes", "player_id": 8481559, "pos": "C", "team": "NJD", "notes": "Elite per-game offense"},
    {"name": "Macklin Celebrini", "player_id": 8484801, "pos": "C", "team": "SJS", "notes": "PP1 volume monster"},
    {"name": "Dylan Guenther", "player_id": 8482699, "pos": "RW", "team": "UTA", "notes": "Shooter with PP touch"},
    {"name": "Cutter Gauthier", "player_id": 8483445, "pos": "LW", "team": "ANA", "notes": "Goals + shots edge"},
    {"name": "Jimmy Snuggerud", "player_id": 8483516, "pos": "RW", "team": "STL", "notes": "Banger king — hits/blocks bump"},
    {"name": "Matthew Schaefer", "player_id": 8485366, "pos": "D", "team": "NYI", "notes": "Rookie D with upside"},
    {"name": "Mikhail Sergachev", "player_id": 8479410, "pos": "D", "team": "UTA", "notes": "PP QB + blocks"},
    {"name": "Jackson LaCombe", "player_id": 8481605, "pos": "D", "team": "ANA", "notes": "Offensive D pairing"},
    {"name": "Pyotr Kochetkov", "player_id": 8481611, "pos": "G", "team": "CAR", "notes": "Starter — fill 2nd G"},
    {"name": "Connor Hellebuyck", "player_id": 8476945, "pos": "G", "team": "WPG", "notes": "Elite ratios"},
]

DEFAULT_OPPONENT_DEMO = [
    {"name": "Will Smith", "player_id": 8484227, "pos": "C", "team": "SJS", "notes": "Skill > bangers"},
    {"name": "Macklin Celebrini", "player_id": 8484801, "pos": "C", "team": "SJS", "notes": ""},
    {"name": "Tyler Toffoli", "player_id": 8475726, "pos": "C", "team": "SJS", "notes": ""},
    {"name": "Kiefer Sherwood", "player_id": 8480748, "pos": "LW", "team": "SJS", "notes": "Physical streamer"},
    {"name": "William Eklund", "player_id": 8482667, "pos": "LW", "team": "SJS", "notes": ""},
    {"name": "Collin Graf", "player_id": 8484911, "pos": "RW", "team": "SJS", "notes": ""},
    {"name": "Adam Gaudette", "player_id": 8478874, "pos": "RW", "team": "SJS", "notes": ""},
    {"name": "Dmitry Orlov", "player_id": 8475200, "pos": "D", "team": "SJS", "notes": ""},
    {"name": "Michael Kesselring", "player_id": 8480891, "pos": "D", "team": "SJS", "notes": ""},
    {"name": "Shakir Mukhamadullin", "player_id": 8482166, "pos": "D", "team": "SJS", "notes": ""},
    {"name": "Sam Dickinson", "player_id": 8484806, "pos": "D", "team": "SJS", "notes": ""},
    {"name": "Vincent Desharnais", "player_id": 8479576, "pos": "D", "team": "SJS", "notes": ""},
    {"name": "Alex Nedeljkovic", "player_id": 8477968, "pos": "G", "team": "SJS", "notes": ""},
    {"name": "Yaroslav Askarov", "player_id": 8482137, "pos": "G", "team": "SJS", "notes": ""},
]