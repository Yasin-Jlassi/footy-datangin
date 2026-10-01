"""
Dashboard View: 1v1 Head-to-Head Player Comparison.
Allows scouts and analysts to compare any two arbitrary players side-by-side,
view their algorithmic similarity score, overlay their percentile radar charts,
and compare key performance metrics with category leaders highlighted.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from dashboard.db import (
    search_players,
    get_player,
    get_player_stats,
    get_player_percentiles,
    get_pairwise_similarity,
)

METRIC_GLOSSARY = {
    "Goals": "Total non-penalty and penalty goals scored.",
    "Assists": "Direct passes leading to a teammate's goal.",
    "xG": "Expected Goals — statistical probability that a shot results in a goal based on historical shot angles, distance, and pressure.",
    "npxG": "Non-Penalty Expected Goals — xG excluding penalty kicks.",
    "xAG": "Expected Assisted Goals — xG value of shots created directly from the player's passes.",
    "Passes Comp": "Number of successfully completed passes.",
    "Pass %": "Percentage of attempted passes completed.",
    "Prog Passes": "Progressive Passes — completed passes that advance the ball at least 10 meters toward the opponent goal.",
    "Key Passes": "Passes directly leading to a teammate taking a shot.",
    "Tackles": "Defensive tackles initiated.",
    "Tackles Won": "Tackles where the player's team won possession.",
    "Interceptions": "Passes intercepted from the opponent.",
    "Recoveries": "Loose balls recovered in play.",
    "Touches Box": "Touches inside the opponent's 18-yard penalty area.",
    "Prog Carries": "Carries that move the ball at least 10 meters toward the opponent goal.",
    "Take-ons Won": "Successful dribbles past an opponent defender.",
}


def render():
    st.title("Head-to-Head (1v1) Comparison")
    st.markdown("Select any two players to compare their statistical profiles, percentile radars, and head-to-head metrics.")

    col1, col2 = st.columns(2)

    # ── Player A Selection ───────────────────────────────────────────
    with col1:
        st.subheader("Player 1")
        query_a = st.text_input("Search Player 1", value="Lamine Yamal", key="search_comp_a")
        results_a = search_players(query_a)
        player_a_id = None
        if not results_a.empty:
            opts_a = {f"{r['full_name']} ({r['position_group']} - {r['nationality']})": r['player_id'] for _, r in results_a.iterrows()}
            selected_label_a = st.selectbox("Select Player 1", options=list(opts_a.keys()), key="select_comp_a")
            player_a_id = opts_a[selected_label_a]
        else:
            st.warning("No players found matching Player 1 search.")

    # ── Player B Selection ───────────────────────────────────────────
    with col2:
        st.subheader("Player 2")
        query_b = st.text_input("Search Player 2", value="Bukayo Saka", key="search_comp_b")
        results_b = search_players(query_b)
        player_b_id = None
        if not results_b.empty:
            opts_b = {f"{r['full_name']} ({r['position_group']} - {r['nationality']})": r['player_id'] for _, r in results_b.iterrows()}
            selected_label_b = st.selectbox("Select Player 2", options=list(opts_b.keys()), key="select_comp_b")
            player_b_id = opts_b[selected_label_b]
        else:
            st.warning("No players found matching Player 2 search.")

    if not player_a_id or not player_b_id:
        st.info("Please select both players to see comparison.")
        return

    player_a = get_player(player_a_id)
    player_b = get_player(player_b_id)
    stats_a = get_player_stats(player_a_id)
    stats_b = get_player_stats(player_b_id)

    # ── Algorithmic Similarity Banner ────────────────────────────────
    st.divider()
    sim_score = get_pairwise_similarity(player_a_id, player_b_id)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric(label=f"Position ({player_a['full_name']})", value=player_a['position_group'], delta=player_a['nationality'])
    with m2:
        if sim_score is not None:
            st.metric(label="Cosine Similarity", value=f"{sim_score:.3f}", help="PCA-reduced cosine similarity (range: -1.0 to +1.0)")
        elif player_a['position_group'] == player_b['position_group']:
            st.metric(label="Cosine Similarity", value="Pending / Low Min", help="Players share position group but need minimum minutes for PCA reduction")
        else:
            st.metric(label="Position Groups", value="Different Groups", help=f"{player_a['position_group']} vs {player_b['position_group']}")
    with m3:
        st.metric(label=f"Position ({player_b['full_name']})", value=player_b['position_group'], delta=player_b['nationality'])

    # ── Percentile Radar Chart ───────────────────────────────────────
    latest_a = stats_a.iloc[0] if not stats_a.empty else None
    latest_b = stats_b.iloc[0] if not stats_b.empty else None

    pct_a = {}
    pct_b = {}
    if latest_a is not None:
        pct_a = get_player_percentiles(player_a_id, latest_a['season'], latest_a['competition_id'])
    if latest_b is not None:
        pct_b = get_player_percentiles(player_b_id, latest_b['season'], latest_b['competition_id'])

    st.subheader("Percentile Radar Profile (0-100 Scale)")

    shared_features = [f for f in pct_a.keys() if f in pct_b]
    features_to_plot = shared_features if shared_features else list(pct_a.keys())

    if features_to_plot:
        labels = [f.replace('_pct', '').replace('_', ' ').title() for f in features_to_plot]
        v_a = [pct_a.get(f, 0) for f in features_to_plot]
        v_b = [pct_b.get(f, 0) for f in features_to_plot]

        col_radar, col_bar = st.columns([1.2, 1])

        with col_radar:
            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=v_a,
                theta=labels,
                fill='toself',
                name=player_a['full_name'],
                line_color='#1f77b4',
            ))
            fig_radar.add_trace(go.Scatterpolar(
                r=v_b,
                theta=labels,
                fill='toself',
                name=player_b['full_name'],
                line_color='#ff7f0e',
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                height=450,
                margin=dict(l=40, r=40, t=30, b=30),
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        with col_bar:
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                y=labels,
                x=v_a,
                name=player_a['full_name'],
                orientation='h',
                marker_color='#1f77b4',
            ))
            fig_bar.add_trace(go.Bar(
                y=labels,
                x=v_b,
                name=player_b['full_name'],
                orientation='h',
                marker_color='#ff7f0e',
            ))
            fig_bar.update_layout(
                barmode='group',
                xaxis=dict(range=[0, 100], title="Percentile Rank"),
                height=450,
                margin=dict(l=10, r=20, t=30, b=30),
            )
            st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("Feature percentiles not yet computed for one or both players.")

    # ── Head-to-Head Numbers Table ───────────────────────────────────
    st.subheader("Head-to-Head Statistics Breakdown")

    if latest_a is not None and latest_b is not None:
        metrics_to_compare = [
            ("Matches Played", "games_played", False),
            ("Minutes Played", "minutes_played", False),
            ("Goals", "goals", True),
            ("Goals / 90", "goals_per90", True),
            ("Expected Goals (xG)", "xg", True),
            ("xG / 90", "xg_per90", True),
            ("Assists", "assists", True),
            ("Assists / 90", "assists_per90", True),
            ("Key Passes (Assisted Shots)", "key_passes", True),
            ("Passes Completed", "passes_completed", True),
            ("Progressive Passes", "progressive_passes", True),
            ("Tackles Won", "tackles_won", True),
            ("Interceptions", "interceptions", True),
            ("Ball Recoveries", "recoveries", True),
            ("Touches in Attacking Box", "touches_att_pen_area", True),
            ("Take-ons Won (Dribbles)", "take_ons_won", True),
            ("Progressive Carries", "progressive_carries", True),
        ]

        table_rows = []
        for label, col_key, has_leader in metrics_to_compare:
            val_a = latest_a.get(col_key, 0)
            val_b = latest_b.get(col_key, 0)

            val_a_display = f"{val_a:.2f}" if isinstance(val_a, float) else f"{val_a}"
            val_b_display = f"{val_b:.2f}" if isinstance(val_b, float) else f"{val_b}"

            edge = "-"
            if has_leader and val_a is not None and val_b is not None:
                if val_a > val_b:
                    edge = f"{player_a['full_name']} (+{round(val_a - val_b, 2)})"
                elif val_b > val_a:
                    edge = f"{player_b['full_name']} (+{round(val_b - val_a, 2)})"
                else:
                    edge = "Tied"

            table_rows.append({
                "Metric": label,
                player_a['full_name']: val_a_display,
                player_b['full_name']: val_b_display,
                "Statistical Edge": edge,
            })

        df_table = pd.DataFrame(table_rows)
        st.dataframe(df_table, use_container_width=True, hide_index=True)

    # ── Metric Glossary / Scouting Legend ────────────────────────────
    with st.expander("📚 Scouting Metric Glossary & Explanations"):
        for m_name, m_desc in METRIC_GLOSSARY.items():
            st.markdown(f"- **{m_name}**: {m_desc}")
