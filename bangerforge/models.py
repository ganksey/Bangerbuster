"""Data models for BangerForge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerGameStats:
    """All stats expressed per game — the primary display unit."""

    goals_pg: float = 0.0
    assists_pg: float = 0.0
    points_pg: float = 0.0
    ppp_pg: float = 0.0
    shots_pg: float = 0.0
    hits_pg: float = 0.0
    blocks_pg: float = 0.0
    pim_pg: float = 0.0
    wins_pg: float = 0.0
    saves_pg: float = 0.0
    save_pct: float = 0.0
    gaa: float = 0.0
    shutouts_pg: float = 0.0
    games_played: int = 0
    source: str = "season"  # recent | season | blended

    # Season totals footnote only
    season_goals: int = 0
    season_assists: int = 0
    season_points: int = 0
    season_games: int = 0

    def get(self, cat: str) -> float:
        return float(getattr(self, cat, 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class PlayerProfile:
    """Cached player bio + stats bundle."""

    player_id: int
    name: str
    pos: str
    team: str
    is_goalie: bool = False
    recent: PerGameStats = field(default_factory=PerGameStats)
    season: PerGameStats = field(default_factory=PerGameStats)
    window: PerGameStats = field(default_factory=PerGameStats)  # Feb 25 – end reg (roster only)
    projected_games_week: int = 0
    banger_score: float = 0.0
    notes: str = ""

    def active_rates(self, prefer_recent: bool = True) -> PerGameStats:
        """Blend recent form with season fallback."""
        if prefer_recent and self.recent.games_played >= 3:
            return self.recent
        return self.season


@dataclass
class CategoryMatchup:
    """Head-to-head category comparison."""

    category: str
    label: str
    mine: float
    theirs: float
    delta: float
    status: str  # win | lose | tossup
    lower_is_better: bool = False


@dataclass
class MoveRecommendation:
    """Single add/drop suggestion."""

    day: str
    add_name: str
    drop_name: str
    reason: str
    lineup_note: str = ""


@dataclass
class RosterEntry:
    """Editable roster row."""

    name: str
    player_id: int
    pos: str
    team: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "player_id": self.player_id,
            "pos": self.pos,
            "team": self.team,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RosterEntry:
        return cls(
            name=str(data.get("name", "")),
            player_id=int(data.get("player_id", 0)),
            pos=str(data.get("pos", "C")),
            team=str(data.get("team", "")),
            notes=str(data.get("notes", "")),
        )