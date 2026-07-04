# BangerForge

Fantasy NHL head-to-head **banger league** optimizer. Per-game stats from the current 2025-26 season, matchup analysis, waiver rankings, and 5-move weekly plans.

## Quick start

```powershell
cd Bangerbuster
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 — use **Load Demo Week** in the sidebar for a sample opponent.

## Features

- **Per-game stats** (G/GP, Hits/GP, Blocks/GP, etc.) — not season totals
- Live NHL API data with disk + memory caching
- Dashboard matchup charts, Snuggerud vs Smith keeper comparison
- Opponent roster versioning by fantasy week
- Waiver wire banger scoring with schedule boost
- 5-move weekly planner + bot mode lineup suggestions

## Project layout

```
app.py              # Streamlit entry point
bangerforge/        # Core logic (API, stats, projections, optimizer)
data/               # Local JSON persistence (gitignored except caches)
scripts/build_cache.py  # Rebuild NHL player/stat caches
```

## Rebuild NHL caches

```powershell
python scripts/build_cache.py
```

## League format

- Slots: 3C / 3LW / 3RW / 5D / 2G
- 5 adds per week
- Skater cats: G, A, P, PPP, SOG, Hits, Blocks, PIM (all per-game)
- Goalie cats: W, Saves, SV%, GAA, Shutouts