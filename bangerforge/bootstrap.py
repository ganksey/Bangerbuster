"""Startup-safe imports and install verification for BangerForge.

Heavy or frequently-renamed modules (especially projections) are loaded lazily
so app.py can import this thin module without triggering partial/stale chains.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent

# Files that must exist alongside app.py (stale sync often leaves app.py new, libs old).
REQUIRED_FILES = (
    "app.py",
    "bangerforge/__init__.py",
    "bangerforge/bootstrap.py",
    "bangerforge/config.py",
    "bangerforge/projections.py",
    "bangerforge/roster_constants.py",
    "bangerforge/roster_profiles.py",
    "bangerforge/roster_stat_mode.py",
)

# module_name -> symbols that must be importable (catches renamed/missing exports).
REQUIRED_SYMBOLS: dict[str, tuple[str, ...]] = {
    "bangerforge.roster_constants": (
        "LEAGUE_ROSTER_SIZE",
        "DEFAULT_ROLLING_GAMES",
        "DEFAULT_SEASON_START",
    ),
    "bangerforge.roster_stat_mode": (
        "resolve_roster_stat_mode",
        "roster_stat_label",
    ),
    "bangerforge.roster_profiles": (
        "enrich_roster_tab_profiles",
    ),
    "bangerforge.projections": (
        "schedule_boost",
        "enrich_roster_profiles",
        "enrich_roster_display_profiles",
        "enrich_roster_window_profiles",
        "project_category_totals",
        "category_matchups",
        "attack_and_protect_plans",
        "select_best_lineup",
    ),
    "bangerforge.config": (
        "CATEGORY_LABELS",
        "DEFAULT_BANGER_WEIGHTS",
        "DEFAULT_OPPONENT_DEMO",
        "GOALIE_CATEGORIES",
        "SKATER_CATEGORIES",
    ),
}

_PROJECTIONS_MODULE: Any | None = None


def _missing_files() -> list[str]:
    return [
        rel for rel in REQUIRED_FILES
        if not (ROOT_DIR / rel).is_file()
    ]


def _check_module_symbols(module_name: str, symbols: tuple[str, ...]) -> list[str]:
    issues: list[str] = []
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        issues.append(f"{module_name}: import failed — {exc}")
        return issues

    for sym in symbols:
        if not hasattr(mod, sym):
            issues.append(f"{module_name}: missing symbol '{sym}'")
    return issues


def verify_install() -> list[str]:
    """Return human-readable install issues (empty list = OK)."""
    issues: list[str] = []

    missing = _missing_files()
    if missing:
        issues.append(
            "Missing files (repo may be partially synced): "
            + ", ".join(missing)
        )

    for module_name, symbols in REQUIRED_SYMBOLS.items():
        issues.extend(_check_module_symbols(module_name, symbols))

    if issues and (ROOT_DIR / ".git").is_dir():
        issues.append(
            "Fix: open a terminal in the project folder and run "
            "`git pull origin main`, then `python scripts/verify_install.py`."
        )

    return issues


def format_install_report(issues: list[str]) -> str:
    """Single block of text suitable for Streamlit or console."""
    if not issues:
        return "BangerForge install OK — all required modules and symbols found."
    lines = ["BangerForge install check FAILED:", ""]
    lines.extend(f"  • {item}" for item in issues)
    return "\n".join(lines)


def _load_projections_module() -> Any:
    """Import projections once, with clear errors for stale copies."""
    global _PROJECTIONS_MODULE
    if _PROJECTIONS_MODULE is not None:
        return _PROJECTIONS_MODULE

    try:
        mod = importlib.import_module("bangerforge.projections")
    except Exception as exc:  # noqa: BLE001
        hint = (
            "Could not import bangerforge.projections. "
            "Your copy may be out of date — run `git pull origin main` "
            "and `python scripts/verify_install.py`."
        )
        raise ImportError(f"{hint} Original error: {exc}") from exc

    missing = [
        sym for sym in REQUIRED_SYMBOLS["bangerforge.projections"]
        if not hasattr(mod, sym)
    ]
    if missing:
        proj_path = PACKAGE_DIR / "projections.py"
        hint = (
            f"Stale projections.py at {proj_path} — missing: {', '.join(missing)}. "
            "Run `git pull origin main` to sync."
        )
        raise ImportError(hint)

    _PROJECTIONS_MODULE = mod
    return mod


class _LazyProjections:
    """Deferred access to bangerforge.projections (loads on first attribute use)."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_load_projections_module(), name)


projections = _LazyProjections()


def __getattr__(name: str) -> Any:
    """Allow `from bangerforge.bootstrap import enrich_roster_profiles` at runtime."""
    if name == "projections":
        return projections
    if name in REQUIRED_SYMBOLS["bangerforge.projections"]:
        return getattr(_load_projections_module(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")