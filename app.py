"""
BangerForge — Fantasy H2H Banger Optimizer
Run: streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bangerforge.config import (
    CATEGORY_LABELS,
    DEFAULT_BANGER_WEIGHTS,
    DEFAULT_OPPONENT_DEMO,
    GOALIE_CATEGORIES,
    SKATER_CATEGORIES,
)
from bangerforge.roster_constants import (
    DEFAULT_ROLLING_GAMES,
    DEFAULT_SEASON_START,
    LEAGUE_ROSTER_SIZE,
)
from bangerforge.models import RosterEntry
from bangerforge.nhl_client import (
    NHLAPIError,
    build_player_directory,
    fantasy_week_bounds,
    search_players,
)
from bangerforge.optimizer import (
    build_week_plan_text,
    daily_lineup_suggestion,
    parse_name_list,
    rank_waiver_targets,
    suggest_five_moves,
)
from bangerforge.opponents import (
    create_opponent,
    delete_opponent,
    get_active_opponent_id,
    get_opponent_roster,
    list_opponents,
    migrate_legacy_opponent_file,
    names_to_roster,
    save_opponent_roster,
    set_active_opponent,
)
from bangerforge.persistence import (
    load_my_roster,
    load_opponent_current,
    load_opponent_history,
    load_settings,
    load_waiver_agents,
    load_weekly_plan,
    save_my_roster,
    save_opponent_current,
    save_opponent_week,
    save_settings,
    save_waiver_agents,
    save_weekly_plan,
)
from bangerforge.projections import (
    attack_and_protect_plans,
    category_matchups,
    enrich_roster_profiles,
    enrich_roster_window_profiles,
    project_category_totals,
    select_best_lineup,
)
from bangerforge.roster_stat_mode import resolve_roster_stat_mode, roster_stat_label
from bangerforge.stats import compare_snuggerud_vs_smith
from bangerforge.utils import normalize_position, safe_int
from bangerforge.nhl_client import resolve_player

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BangerForge",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .main-header {
        font-size: 2.4rem;
        font-weight: 800;
        background: linear-gradient(90deg, #ff6b35, #f7c948);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header { color: #8892a4; font-size: 1rem; margin-top: 0; }
    .win-badge { background: #1a4d2e; color: #4ade80; padding: 4px 12px;
                 border-radius: 20px; font-weight: 600; }
    .lose-badge { background: #4d1a1a; color: #f87171; padding: 4px 12px;
                  border-radius: 20px; font-weight: 600; }
    .toss-badge { background: #3d3d1a; color: #facc15; padding: 4px 12px;
                  border-radius: 20px; font-weight: 600; }
    .stat-footnote { font-size: 0.75rem; color: #6b7280; }
    div[data-testid="stMetric"] {
        background: rgba(255,107,53,0.08);
        border: 1px solid rgba(255,107,53,0.2);
        border-radius: 10px;
        padding: 12px;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def init_session() -> None:
    """Initialize session state from disk."""
    if "initialized" not in st.session_state:
        migrate_legacy_opponent_file()
        st.session_state.settings = load_settings()
        st.session_state.my_roster = load_my_roster()[:LEAGUE_ROSTER_SIZE]
        st.session_state.active_opponent_id = get_active_opponent_id()
        st.session_state.opponent_roster = load_opponent_current()
        st.session_state.waiver_agents = load_waiver_agents()
        st.session_state.confirmed_plan = load_weekly_plan()
        st.session_state.initialized = True


def league_size() -> int:
    return int(st.session_state.settings.get("league_roster_size", LEAGUE_ROSTER_SIZE))


def fetch_roster_profiles(
    roster: list[RosterEntry],
    week_start: str,
    week_end: str,
    settings: dict[str, Any],
) -> list[Any]:
    """Fetch NHL stats for each loaded roster player with visible progress."""
    if not roster:
        return []
    mode = resolve_roster_stat_mode(settings)
    label = roster_stat_label(mode, settings)
    profiles: list[Any] = []
    progress = st.progress(0.0, text=f"📡 Pulling NHL data — {label}")
    total = len([e for e in roster if e.player_id])
    done = 0
    for entry in roster:
        if not entry.player_id:
            continue
        done += 1
        progress.progress(
            done / max(total, 1),
            text=f"📡 {entry.name} ({done}/{total}) — {label}",
        )
        batch = enrich_roster_window_profiles(
            [entry], week_start, week_end, settings,
        )
        if batch:
            profiles.append(batch[0])
    progress.empty()
    return profiles


def status_badge(status: str) -> str:
    badges = {"win": "win-badge", "lose": "lose-badge", "tossup": "toss-badge"}
    labels = {"win": "✅ You Win", "lose": "❌ Vulnerable", "tossup": "⚖️ Toss-up"}
    return f'<span class="{badges.get(status, "toss-badge")}">{labels.get(status, status)}</span>'


def roster_profile_to_row(p: Any) -> dict[str, Any]:
    """Roster tab row — per-game rates from active roster stat mode."""
    stats = p.window
    row = {
        "Name": p.name,
        "Pos": p.pos,
        "Team": p.team,
        "GP": stats.games_played,
        "G/GP": round(stats.goals_pg, 2),
        "A/GP": round(stats.assists_pg, 2),
        "P/GP": round(stats.points_pg, 2),
        "PPP/GP": round(stats.ppp_pg, 2),
        "SOG/GP": round(stats.shots_pg, 2),
        "Hits/GP": round(stats.hits_pg, 2),
        "Blk/GP": round(stats.blocks_pg, 2),
        "PIM/GP": round(stats.pim_pg, 2),
        "Proj G": p.projected_games_week,
        "Banger Score": p.banger_score,
        "Notes": p.notes,
    }
    if p.is_goalie:
        row.update({
            "W/GP": round(stats.wins_pg, 2),
            "Sv/GP": round(stats.saves_pg, 1),
            "SV%": round(stats.save_pct, 3),
            "GAA": round(stats.gaa, 2),
            "SO/GP": round(stats.shutouts_pg, 2),
        })
    return row


def roster_dataframe(profiles: list[Any]) -> pd.DataFrame:
    return pd.DataFrame([roster_profile_to_row(p) for p in profiles])


def projection_profile_to_row(p: Any) -> dict[str, Any]:
    """Non-roster tabs — recent/season blended per-game rates."""
    stats = p.recent if p.recent.games_played >= 3 else p.season
    row = {
        "Name": p.name,
        "Pos": p.pos,
        "Team": p.team,
        "G/GP": round(stats.goals_pg, 2),
        "A/GP": round(stats.assists_pg, 2),
        "P/GP": round(stats.points_pg, 2),
        "PPP/GP": round(stats.ppp_pg, 2),
        "SOG/GP": round(stats.shots_pg, 2),
        "Hits/GP": round(stats.hits_pg, 2),
        "Blk/GP": round(stats.blocks_pg, 2),
        "PIM/GP": round(stats.pim_pg, 2),
        "Proj G": p.projected_games_week,
        "Banger Score": p.banger_score,
    }
    return row


def projection_dataframe(profiles: list[Any]) -> pd.DataFrame:
    return pd.DataFrame([projection_profile_to_row(p) for p in profiles])


def category_bar_chart(matchups: list[Any]) -> go.Figure:
    cats = [m.label for m in matchups]
    mine = [m.mine for m in matchups]
    theirs = [m.theirs for m in matchups]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="You", x=cats, y=mine, marker_color="#ff6b35"))
    fig.add_trace(go.Bar(name="Opponent", x=cats, y=theirs, marker_color="#4a90d9"))
    fig.update_layout(
        barmode="group",
        title="Category Projections (Week Totals)",
        template="plotly_dark",
        height=420,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def category_radar(matchups: list[Any]) -> go.Figure:
    labels = [m.label for m in matchups]
    mine = [m.mine for m in matchups]
    theirs = [m.theirs for m in matchups]
    max_vals = [max(m, t, 0.01) for m, t in zip(mine, theirs)]
    mine_n = [m / mv for m, mv in zip(mine, max_vals)]
    theirs_n = [t / mv for t, mv in zip(theirs, max_vals)]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=mine_n + [mine_n[0]], theta=labels + [labels[0]],
        fill="toself", name="You", line_color="#ff6b35",
    ))
    fig.add_trace(go.Scatterpolar(
        r=theirs_n + [theirs_n[0]], theta=labels + [labels[0]],
        fill="toself", name="Opponent", line_color="#4a90d9",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1.2])),
        title="Normalized Category Shape",
        template="plotly_dark",
        height=420,
    )
    return fig


def editor_to_roster(df: pd.DataFrame, original: list[RosterEntry]) -> list[RosterEntry]:
    """Merge data_editor output back to roster entries."""
    id_map = {r.name: r for r in original}
    result: list[RosterEntry] = []
    for _, row in df.iterrows():
        name = str(row.get("Name", "")).strip()
        if not name:
            continue
        base = id_map.get(name)
        pid = safe_int(row.get("player_id"), base.player_id if base else 0)
        if pid == 0:
            hit = resolve_player(name)
            if hit:
                pid = hit["player_id"]
        pos = normalize_position(str(row.get("Pos", base.pos if base else "C")))
        team = str(row.get("Team", base.team if base else "")).strip()
        if not team and base:
            team = base.team
        if not team:
            hit = resolve_player(name)
            if hit:
                team = hit["team"]
                pos = normalize_position(hit.get("pos", pos))
        result.append(RosterEntry(
            name=name,
            player_id=pid,
            pos=pos,
            team=team,
            notes=str(row.get("Notes", base.notes if base else "")),
        ))
    return result


def render_sidebar() -> tuple[str, str]:
    """Sidebar controls — returns week_start, week_end."""
    st.sidebar.markdown("## ⚙️ Week Control")
    settings = st.session_state.settings
    start_dow = int(settings.get("fantasy_week_start_dow", 0))
    default_start, default_end = fantasy_week_bounds(start_dow=start_dow)

    col1, col2 = st.sidebar.columns(2)
    with col1:
        week_start = st.date_input(
            "Week Start",
            value=datetime.strptime(default_start, "%Y-%m-%d").date(),
        )
    with col2:
        week_end = st.date_input(
            "Week End",
            value=datetime.strptime(default_end, "%Y-%m-%d").date(),
        )

    st.session_state.settings["current_week_number"] = st.sidebar.number_input(
        "Fantasy Week #",
        min_value=1, max_value=30,
        value=int(settings.get("current_week_number", 13)),
    )

    if st.sidebar.button("🔄 Refresh NHL Data", use_container_width=True):
        st.cache_data.clear()
        st.sidebar.success("Cache cleared — data will reload.")

    if st.sidebar.button("📦 Load Demo Week", use_container_width=True):
        demo_oid = create_opponent("Demo Opponent")
        demo_roster = [
            RosterEntry.from_dict(d) for d in DEFAULT_OPPONENT_DEMO[:league_size()]
        ]
        save_opponent_roster(demo_oid, demo_roster)
        st.session_state.active_opponent_id = demo_oid
        st.session_state.opponent_roster = demo_roster
        st.session_state.waiver_agents = [
            "Kiefer Sherwood", "Alexey Toropchenko", "Nicolas Deslauriers",
            "Jake Neighbours", "Brandon Carlo",
        ]
        save_waiver_agents(st.session_state.waiver_agents)
        st.sidebar.success("Demo opponent + waivers loaded!")

    st.sidebar.markdown("---")
    mode = resolve_roster_stat_mode(st.session_state.settings)
    st.sidebar.caption(
        f"Roster tabs: **{roster_stat_label(mode, st.session_state.settings)}**. "
        "Other tabs use current-season recent/season blend. "
        f"League roster size: **{league_size()}**."
    )
    return week_start.isoformat(), week_end.isoformat()


def tab_dashboard(week_start: str, week_end: str) -> None:
    st.markdown("### 📊 Dashboard")
    settings = st.session_state.settings
    skater_cats = settings.get("active_skater_categories", SKATER_CATEGORIES)
    goalie_cats = settings.get("active_goalie_categories", GOALIE_CATEGORIES)
    all_cats = skater_cats + goalie_cats

    try:
        with st.spinner("Loading NHL stats (cached after first run)..."):
            my_p = enrich_roster_profiles(st.session_state.my_roster, week_start, week_end, settings)
            opp_p = enrich_roster_profiles(st.session_state.opponent_roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(f"NHL API error: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Dashboard error: {exc}")
        return

    my_totals = project_category_totals(my_p, all_cats)
    opp_totals = project_category_totals(opp_p, all_cats)
    matchups = category_matchups(my_totals, opp_totals, all_cats)
    wins = sum(1 for m in matchups if m.status == "win")
    losses = sum(1 for m in matchups if m.status == "lose")

    c1, c2, c3, c4 = st.columns(4)
    my_bs = sum(p.banger_score for p in my_p)
    opp_bs = sum(p.banger_score for p in opp_p)
    c1.metric("Your Banger Score", f"{my_bs:.0f}")
    c2.metric("Opponent Banger Score", f"{opp_bs:.0f}")
    c3.metric("Categories Winning", f"{wins}/{len(matchups)}")
    c4.metric("Vulnerabilities", losses)

    st.info(
        "⚠️ **Projections** = current-season per-game rates × projected games this week. "
        "Variance exists — this is your edge, not a guarantee."
    )

    col_l, col_r = st.columns(2)
    with col_l:
        st.plotly_chart(category_bar_chart(matchups), use_container_width=True)
    with col_r:
        st.plotly_chart(category_radar(matchups), use_container_width=True)

    st.markdown("#### Top Recommendations")
    attack, protect = attack_and_protect_plans(matchups)
    rec_col1, rec_col2 = st.columns(2)
    with rec_col1:
        st.markdown("**🎯 Category Attack Plan**")
        for a in attack[:3]:
            st.markdown(f"- {a}")
    with rec_col2:
        st.markdown("**🛡️ Protect Plan**")
        for p in protect[:3]:
            st.markdown(f"- {p}")

    with st.expander("🔥 Snuggerud vs Smith — Keeper Edge"):
        comp = compare_snuggerud_vs_smith(
            recent_window=int(settings.get("recent_games_window", 10)),
            weights=settings.get("banger_weights"),
        )
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Snuggerud BS", comp["snuggerud"].banger_score)
        sc2.metric("Smith BS", comp["smith"].banger_score)
        sc3.metric("Snug Hits/GP", f"{comp['edges']['hits_pg']['snuggerud']:.2f}")
        st.markdown(comp["verdict"])
        edge_df = pd.DataFrame([
            {
                "Category": CATEGORY_LABELS.get(k, k),
                "Snuggerud/GP": round(v["snuggerud"], 3),
                "Smith/GP": round(v["smith"], 3),
                "Edge": round(v["edge"], 3),
            }
            for k, v in comp["edges"].items()
        ])
        st.dataframe(edge_df, use_container_width=True, hide_index=True)


def tab_my_roster(week_start: str, week_end: str) -> None:
    st.markdown("### 🏒 My Roster")
    settings = st.session_state.settings
    max_slots = league_size()
    roster = st.session_state.my_roster

    st.info(
        f"**{len(roster)}/{max_slots} players loaded.** "
        "NHL stats are fetched when players appear on this roster — "
        "not when you search or paste names elsewhere."
    )

    add_col1, add_col2 = st.columns([3, 1])
    with add_col1:
        search_q = st.text_input("Add player (search)", placeholder="Jimmy Snuggerud")
    with add_col2:
        if st.button("➕ Add Player") and search_q:
            if len(roster) >= max_slots:
                st.warning(f"Roster full ({max_slots} players). Drop someone first.")
            else:
                hits = search_players(search_q, limit=5)
                if hits:
                    h = hits[0]
                    roster.append(RosterEntry(
                        name=h["name"], player_id=h["player_id"],
                        pos=normalize_position(h["pos"]), team=h["team"],
                    ))
                    st.session_state.my_roster = roster[:max_slots]
                    save_my_roster(st.session_state.my_roster)
                    st.success(f"Added {h['name']} — stats will pull on next render.")
                else:
                    st.warning("No player found.")

    if not roster:
        st.warning("Roster empty — add players or reload defaults.")
        return

    mode = resolve_roster_stat_mode(settings)
    stat_caption = roster_stat_label(mode, settings)
    try:
        profiles = fetch_roster_profiles(roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(str(exc))
        return

    fetched = sum(1 for p in profiles if p.data_fetched)
    st.caption(
        f"**{fetched}/{len(profiles)}** players with NHL data. "
        f"Per-game rates: **{stat_caption}**. **GP** = games in that sample."
    )
    df = roster_dataframe(profiles)
    id_lookup = {p.name: p.player_id for p in profiles}
    df["player_id"] = df["Name"].map(id_lookup)
    stat_cols = [c for c in df.columns if not c.startswith("_") and c != "player_id"]

    edited = st.data_editor(
        df[stat_cols],
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Banger Score": st.column_config.NumberColumn(format="%.1f"),
            "G/GP": st.column_config.NumberColumn(format="%.2f"),
            "P/GP": st.column_config.NumberColumn(format="%.2f"),
            "Hits/GP": st.column_config.NumberColumn(format="%.2f"),
            "Blk/GP": st.column_config.NumberColumn(format="%.2f"),
        },
        key="my_roster_editor",
    )

    if st.button("💾 Save My Roster"):
        merged = df[["Name", "player_id"]].merge(edited, on="Name", how="right")
        st.session_state.my_roster = editor_to_roster(merged, st.session_state.my_roster)
        save_my_roster(st.session_state.my_roster)
        st.success("Roster saved!")


def tab_opponent(week_start: str, week_end: str) -> None:
    st.markdown("### 👤 Opponent Roster")
    settings = st.session_state.settings
    week_num = int(settings.get("current_week_number", 13))
    max_slots = league_size()

    st.info(
        f"Create named opponents and load up to **{max_slots}** players each week. "
        "You manage who's on the roster — BangerForge pulls NHL stats only when "
        "players are saved here."
    )

    opponents = list_opponents()
    opp_labels = {o["id"]: f"{o['name']} ({o['player_count']}/{max_slots})" for o in opponents}
    active_id = st.session_state.get("active_opponent_id", "")

    mgr1, mgr2, mgr3 = st.columns([2, 1, 1])
    with mgr1:
        if opponents:
            ids = [o["id"] for o in opponents]
            default_idx = ids.index(active_id) if active_id in ids else 0
            picked = st.selectbox(
                "Active opponent",
                ids,
                index=default_idx,
                format_func=lambda oid: opp_labels.get(oid, oid),
            )
            if picked != active_id:
                set_active_opponent(picked)
                st.session_state.active_opponent_id = picked
                st.session_state.opponent_roster = get_opponent_roster(picked)
                st.rerun()
        else:
            st.caption("No opponents yet — create one below.")

    with mgr2:
        new_name = st.text_input("New opponent name", placeholder="Week 13 — Mike")
        if st.button("➕ Create Opponent") and new_name.strip():
            oid = create_opponent(new_name.strip())
            st.session_state.active_opponent_id = oid
            st.session_state.opponent_roster = []
            st.success(f"Created '{new_name.strip()}'")
            st.rerun()

    with mgr3:
        if active_id and st.button("🗑️ Delete Active"):
            delete_opponent(active_id)
            st.session_state.active_opponent_id = get_active_opponent_id()
            st.session_state.opponent_roster = load_opponent_current()
            st.rerun()

    roster = st.session_state.opponent_roster
    st.markdown(f"**Roster: {len(roster)}/{max_slots} players**")

    paste = st.text_area(
        f"Paste opponent names (one per line, max {max_slots})",
        placeholder="Will Smith\nMacklin Celebrini\n...",
        height=120,
    )
    up_col1, up_col2 = st.columns(2)
    with up_col1:
        if st.button("📋 Load Names to Roster") and paste:
            if not active_id:
                st.warning("Create an opponent first.")
            else:
                names = parse_name_list(paste)[:max_slots]
                new_roster = names_to_roster(names, max_size=max_slots)
                if new_roster:
                    st.session_state.opponent_roster = new_roster
                    save_opponent_roster(active_id, new_roster)
                    st.success(
                        f"Loaded {len(new_roster)} players — "
                        "📡 NHL stats will pull below."
                    )
                    st.rerun()
                else:
                    st.warning("No names resolved. Check spelling.")
    with up_col2:
        uploaded = st.file_uploader("CSV upload (Name column)", type=["csv"])
        if uploaded and active_id:
            imp_df = pd.read_csv(uploaded)
            name_col = "Name" if "Name" in imp_df.columns else imp_df.columns[0]
            names = imp_df[name_col].dropna().tolist()[:max_slots]
            new_roster = names_to_roster(names, max_size=max_slots)
            if new_roster and st.button("📋 Load CSV to Roster"):
                st.session_state.opponent_roster = new_roster
                save_opponent_roster(active_id, new_roster)
                st.success(f"Loaded {len(new_roster)} from CSV.")
                st.rerun()

    save_week = st.text_input("Week snapshot label", value=f"Week {week_num} Opponent")
    if st.button("💾 Save Week Snapshot") and roster:
        save_opponent_week(save_week, roster)
        st.success(f"Saved as '{save_week}'")

    history = load_opponent_history()
    if history:
        pick = st.selectbox("Load previous snapshot", ["—"] + list(history.keys()))
        if pick != "—" and st.button("Load Snapshot"):
            loaded = [RosterEntry.from_dict(r) for r in history[pick]][:max_slots]
            st.session_state.opponent_roster = loaded
            if active_id:
                save_opponent_roster(active_id, loaded)
            st.success(f"Loaded {pick} — stats will pull below.")
            st.rerun()

    if not roster:
        st.warning("No players on this opponent — paste names and click Load.")
        return

    mode = resolve_roster_stat_mode(settings)
    try:
        profiles = fetch_roster_profiles(roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(str(exc))
        return

    if profiles:
        fetched = sum(1 for p in profiles if p.data_fetched)
        st.caption(
            f"**{fetched}/{len(profiles)}** with NHL data. "
            f"Per-game: **{roster_stat_label(mode, settings)}**. "
            f"**GP** = games in sample."
        )
        st.dataframe(roster_dataframe(profiles), use_container_width=True, hide_index=True)


def tab_waiver(week_start: str, week_end: str) -> None:
    st.markdown("### 🎯 Waiver Wire / Add-Drop Optimizer")
    settings = st.session_state.settings

    agents_text = st.text_area(
        "Free agents (one per line)",
        value="\n".join(st.session_state.waiver_agents),
        height=100,
    )
    if st.button("💾 Save Agent List"):
        st.session_state.waiver_agents = parse_name_list(agents_text)
        save_waiver_agents(st.session_state.waiver_agents)
        st.success("Saved!")

    names = parse_name_list(agents_text)
    if st.button("🔍 Rank Agents") and names:
        try:
            ranked = rank_waiver_targets(names, week_start, week_end, settings, limit=10)
        except NHLAPIError as exc:
            st.error(str(exc))
            return

        st.markdown("#### Best Adds This Week")
        for i, p in enumerate(ranked[:5], 1):
            rates = p.recent if p.recent.games_played >= 3 else p.season
            with st.expander(f"#{i} {p.name} — BS {p.banger_score} ({p.projected_games_week} games)"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Hits/GP", f"{rates.hits_pg:.2f}")
                c2.metric("Blocks/GP", f"{rates.blocks_pg:.2f}")
                c3.metric("P/GP", f"{rates.points_pg:.2f}")
                c4.metric("SOG/GP", f"{rates.shots_pg:.2f}")
                st.markdown(
                    f"**Why:** {p.projected_games_week}-game week + "
                    f"per-game banger profile (Hits {rates.hits_pg:.1f}, "
                    f"Blocks {rates.blocks_pg:.1f}, PIM {rates.pim_pg:.1f})."
                )

        st.dataframe(projection_dataframe(ranked), use_container_width=True, hide_index=True)


def tab_matchup(week_start: str, week_end: str) -> None:
    st.markdown("### ⚔️ Matchup Analyzer")
    settings = st.session_state.settings
    skater_cats = settings.get("active_skater_categories", SKATER_CATEGORIES)
    goalie_cats = settings.get("active_goalie_categories", GOALIE_CATEGORIES)
    all_cats = skater_cats + goalie_cats

    try:
        my_p = enrich_roster_profiles(st.session_state.my_roster, week_start, week_end, settings)
        opp_p = enrich_roster_profiles(st.session_state.opponent_roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(str(exc))
        return

    my_totals = project_category_totals(my_p, all_cats)
    opp_totals = project_category_totals(opp_p, all_cats)
    matchups = category_matchups(my_totals, opp_totals, all_cats)

    for m in matchups:
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{m.label}**")
        col2.markdown(f"You: **{m.mine:.1f}**")
        col3.markdown(f"Opp: **{m.theirs:.1f}**")
        col4.markdown(status_badge(m.status), unsafe_allow_html=True)
        if m.status == "lose":
            st.progress(min(abs(m.delta) / max(m.theirs, 1), 1.0))
            st.caption(f"Vulnerability: {m.delta:+.1f} projected — attack with streamers.")

    attack, protect = attack_and_protect_plans(matchups)
    ac, pc = st.columns(2)
    with ac:
        st.markdown("#### 🎯 Category Attack Plan")
        for a in attack:
            st.markdown(f"- {a}")
    with pc:
        st.markdown("#### 🛡️ Protect Plan")
        for p in protect:
            st.markdown(f"- {p}")

    export_df = pd.DataFrame([
        {
            "Category": m.label,
            "You": m.mine,
            "Opponent": m.theirs,
            "Delta": m.delta,
            "Status": m.status,
        }
        for m in matchups
    ])
    st.download_button(
        "📥 Export Projections CSV",
        export_df.to_csv(index=False),
        "bangerforge_projections.csv",
        "text/csv",
    )


def tab_planner(week_start: str, week_end: str) -> None:
    st.markdown("### 📅 Weekly Planner & 5-Move Optimizer")
    settings = st.session_state.settings

    try:
        my_p = enrich_roster_profiles(st.session_state.my_roster, week_start, week_end, settings)
        opp_p = enrich_roster_profiles(st.session_state.opponent_roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(str(exc))
        return

    skater_cats = settings.get("active_skater_categories", SKATER_CATEGORIES)
    goalie_cats = settings.get("active_goalie_categories", GOALIE_CATEGORIES)
    all_cats = skater_cats + goalie_cats
    my_totals = project_category_totals(my_p, all_cats)
    opp_totals = project_category_totals(opp_p, all_cats)
    matchups = category_matchups(my_totals, opp_totals, all_cats)

    waiver_names = st.session_state.waiver_agents or [
        "Kiefer Sherwood", "Alexey Toropchenko", "Jake Neighbours",
    ]
    try:
        waiver_p = rank_waiver_targets(waiver_names, week_start, week_end, settings, limit=10)
    except NHLAPIError:
        waiver_p = []

    if st.button("🧠 Generate 5-Move Plan"):
        moves = suggest_five_moves(my_p, opp_p, waiver_p, matchups, week_start)
        lineup = daily_lineup_suggestion(my_p)
        plan_text = build_week_plan_text(moves, lineup)
        st.session_state["_draft_plan"] = plan_text
        st.session_state["_draft_moves"] = moves

    if "_draft_moves" in st.session_state:
        for m in st.session_state["_draft_moves"]:
            st.markdown(f"**{m.day}**")
            st.markdown(f"- ADD: **{m.add_name}** | DROP: **{m.drop_name}**")
            st.markdown(f"- {m.reason}")
            st.markdown(f"- Lineup: {m.lineup_note}")
            st.divider()

    if "_draft_plan" in st.session_state:
        edited_plan = st.text_area(
            "Edit plan before confirming",
            value=st.session_state["_draft_plan"],
            height=300,
        )
        if st.button("✅ Confirm & Save Plan"):
            save_weekly_plan(edited_plan)
            st.session_state.confirmed_plan = edited_plan
            st.success("Plan saved locally!")

        st.download_button(
            "📥 Export Plan (CSV-ready text)",
            edited_plan,
            "bangerforge_weekly_plan.txt",
        )


def tab_bot_mode(week_start: str, week_end: str) -> None:
    st.markdown("### 🤖 Bot Mode")
    settings = st.session_state.settings

    try:
        my_p = enrich_roster_profiles(st.session_state.my_roster, week_start, week_end, settings)
    except NHLAPIError as exc:
        st.error(str(exc))
        return

    if st.button("📋 Suggest Daily Lineup"):
        lineup = daily_lineup_suggestion(my_p)
        for pos, players in lineup.items():
            st.markdown(f"**{pos}** ({len(players)}): " + ", ".join(players) if players else f"**{pos}**: empty")

    if st.button("🚀 Full Week Auto-Plan"):
        opp_p = enrich_roster_profiles(
            st.session_state.opponent_roster, week_start, week_end, settings,
        )
        skater_cats = settings.get("active_skater_categories", SKATER_CATEGORIES)
        goalie_cats = settings.get("active_goalie_categories", GOALIE_CATEGORIES)
        matchups = category_matchups(
            project_category_totals(my_p, skater_cats + goalie_cats),
            project_category_totals(opp_p, skater_cats + goalie_cats),
            skater_cats + goalie_cats,
        )
        waiver_p = rank_waiver_targets(
            st.session_state.waiver_agents or ["Kiefer Sherwood"],
            week_start, week_end, settings, limit=10,
        )
        moves = suggest_five_moves(my_p, opp_p, waiver_p, matchups, week_start)
        plan = build_week_plan_text(moves, daily_lineup_suggestion(my_p))
        st.session_state["_draft_plan"] = plan
        st.text_area("Generated Plan", plan, height=400)

    if st.session_state.confirmed_plan:
        with st.expander("📄 Saved Plan"):
            st.markdown(st.session_state.confirmed_plan)


def tab_settings() -> None:
    st.markdown("### ⚙️ Settings")
    settings = st.session_state.settings

    st.markdown("#### Active Categories")
    sk_sel = st.multiselect(
        "Skater categories",
        SKATER_CATEGORIES,
        default=settings.get("active_skater_categories", SKATER_CATEGORIES),
        format_func=lambda x: CATEGORY_LABELS.get(x, x),
    )
    g_sel = st.multiselect(
        "Goalie categories",
        GOALIE_CATEGORIES,
        default=settings.get("active_goalie_categories", GOALIE_CATEGORIES),
        format_func=lambda x: CATEGORY_LABELS.get(x, x),
    )

    st.markdown("#### Banger Score Weights")
    weights = settings.get("banger_weights", DEFAULT_BANGER_WEIGHTS.copy())
    new_weights: dict[str, float] = {}
    cols = st.columns(3)
    all_w = list(DEFAULT_BANGER_WEIGHTS.keys())
    for i, cat in enumerate(all_w):
        with cols[i % 3]:
            new_weights[cat] = st.number_input(
                CATEGORY_LABELS.get(cat, cat),
                value=float(weights.get(cat, DEFAULT_BANGER_WEIGHTS[cat])),
                step=0.1,
                key=f"w_{cat}",
            )

    st.markdown("#### Roster Tab Stats")
    mode_options = {
        "auto": "Auto (prior season until season starts, then rolling sample)",
        "prior_season": "2024-25 full season (per-game)",
        "rolling_25": "Rolling last N games (2025-26)",
    }
    cur_mode = settings.get("roster_stat_mode", "auto")
    roster_mode = st.selectbox(
        "Roster stat mode",
        list(mode_options.keys()),
        index=list(mode_options.keys()).index(cur_mode) if cur_mode in mode_options else 0,
        format_func=lambda k: mode_options[k],
    )
    season_start = st.date_input(
        "Season start (for auto mode)",
        value=datetime.strptime(
            str(settings.get("season_start_date", DEFAULT_SEASON_START)), "%Y-%m-%d",
        ).date(),
    )
    rolling_n = st.slider(
        "Rolling sample size (games)",
        10, 40, int(settings.get("rolling_games_sample", DEFAULT_ROLLING_GAMES)),
    )
    roster_size = st.number_input(
        "League roster size",
        min_value=6, max_value=20,
        value=int(settings.get("league_roster_size", LEAGUE_ROSTER_SIZE)),
    )
    resolved = resolve_roster_stat_mode({
        **settings,
        "roster_stat_mode": roster_mode,
        "season_start_date": season_start.isoformat(),
        "rolling_games_sample": rolling_n,
    })
    st.caption(f"Active roster display: **{roster_stat_label(resolved, settings)}**")

    st.markdown("#### Projection Tuning")
    recent_w = st.slider(
        "Recent form window (games)",
        7, 14, int(settings.get("recent_games_window", 10)),
    )
    theme = st.radio("Theme", ["dark", "light"], index=0 if settings.get("theme") == "dark" else 1)

    if st.button("💾 Save Settings"):
        settings["active_skater_categories"] = sk_sel
        settings["active_goalie_categories"] = g_sel
        settings["banger_weights"] = new_weights
        settings["roster_stat_mode"] = roster_mode
        settings["season_start_date"] = season_start.isoformat()
        settings["rolling_games_sample"] = rolling_n
        settings["league_roster_size"] = int(roster_size)
        settings["recent_games_window"] = recent_w
        settings["theme"] = theme
        st.session_state.settings = settings
        save_settings(settings)
        st.cache_data.clear()
        st.success("Settings saved!")

    with st.expander("🔌 API Health Check — Snuggerud Game Log"):
        if st.button("Test Jimmy Snuggerud fetch"):
            from bangerforge.nhl_client import fetch_skater_game_log
            try:
                logs = fetch_skater_game_log(8483516)
                if logs:
                    last = logs[0]
                    st.success(
                        f"Latest: {last.get('gameDate')} — "
                        f"{last.get('goals')}G/{last.get('assists')}A, "
                        f"{last.get('shots')} SOG, {last.get('pim')} PIM, "
                        f"TOI {last.get('toi')}"
                    )
                    st.dataframe(pd.DataFrame(logs[:5]), use_container_width=True)
                else:
                    st.warning("No game log returned.")
            except NHLAPIError as exc:
                st.error(str(exc))


def main() -> None:
    init_session()
    week_start, week_end = render_sidebar()

    st.markdown('<p class="main-header">🔥 BangerForge</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">Fantasy H2H Banger Optimizer — '
        "2025-26 per-game stats, 5 moves/week, category warfare</p>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs([
        "📊 Dashboard",
        "🏒 My Roster",
        "👤 Opponent",
        "🎯 Waiver Wire",
        "⚔️ Matchup",
        "📅 Weekly Planner",
        "🤖 Bot Mode",
        "⚙️ Settings",
    ])

    with tabs[0]:
        tab_dashboard(week_start, week_end)
    with tabs[1]:
        tab_my_roster(week_start, week_end)
    with tabs[2]:
        tab_opponent(week_start, week_end)
    with tabs[3]:
        tab_waiver(week_start, week_end)
    with tabs[4]:
        tab_matchup(week_start, week_end)
    with tabs[5]:
        tab_planner(week_start, week_end)
    with tabs[6]:
        tab_bot_mode(week_start, week_end)
    with tabs[7]:
        tab_settings()


if __name__ == "__main__":
    main()