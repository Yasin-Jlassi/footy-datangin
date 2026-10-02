import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from db import search_players, get_player, get_similar_players, get_player_percentiles, get_player_stats, config

def render():
    st.title("Player Search & Similarity")
    
    query = st.text_input("Search Player by Name", value="", placeholder="e.g. Lionel Messi")
    
    if query:
        results = search_players(query)
        if results.empty:
            st.warning("No players found.")
        else:
            st.dataframe(results, use_container_width=True, hide_index=True)
            
            selected_id = st.selectbox(
                "Select a player to view details", 
                results['player_id'].tolist(),
                format_func=lambda x: results[results['player_id'] == x]['full_name'].iloc[0]
            )
            
            if selected_id:
                st.session_state['selected_player_id'] = selected_id
    
    if 'selected_player_id' in st.session_state:
        player_id = st.session_state['selected_player_id']
        player = get_player(player_id)
        
        if not player:
            st.error("Player not found in database.")
            return
            
        st.header(player['full_name'])
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Nationality", player['nationality'])
        col2.metric("Position", player['position_group'])

        # Calculate Age from birth date, guarding against dummy placeholder
        dob = player.get('birth_date')
        if dob and str(dob) != '1998-01-01':
            from datetime import date
            age = (date.today() - dob).days // 365
            col3.metric("Birth Date", str(dob), delta=f"Age {age}")
        else:
            col3.metric("Birth Date", "N/A")
        
        # Get Latest Stats for competition/season
        stats = get_player_stats(player_id)
        if stats.empty:
            st.warning("No stats available for this player.")
            return
            
        latest_season = stats.iloc[0]['season']
        latest_comp = stats.iloc[0]['competition_id']
        col4.metric("Latest Season", f"{latest_season} ({latest_comp})")
        
        st.subheader("Top Similar Players")
        top_n = config.get("dashboard", {}).get("search_top_n", 10)
        similar_players = get_similar_players(player_id, top_n)
        
        if similar_players.empty:
            st.info("No similar players found.")
        else:
            st.dataframe(similar_players, use_container_width=True, hide_index=True)
            
            top_similar_id = similar_players.iloc[0]['player_id']
            top_similar_name = similar_players.iloc[0]['full_name']
            
            # Percentiles for radar
            p1_pct = get_player_percentiles(player_id, latest_season, latest_comp)
            # Find the same season/comp for the similar player
            p2_pct = get_player_percentiles(top_similar_id, latest_season, latest_comp)
            
            if p1_pct:
                features = list(p1_pct.keys())
                # clean feature names
                labels = [f.replace('_pct', '').replace('_', ' ').title() for f in features]
                
                v1 = [p1_pct.get(f, 0) for f in features]
                
                st.subheader(f"Comparison vs {top_similar_name}")
                
                col_radar, col_bar = st.columns(2)
                
                with col_radar:
                    fig = go.Figure()
                    fig.add_trace(go.Scatterpolar(
                        r=v1,
                        theta=labels,
                        fill='toself',
                        name=player['full_name']
                    ))
                    if p2_pct:
                        v2 = [p2_pct.get(f, 0) for f in features]
                        fig.add_trace(go.Scatterpolar(
                            r=v2,
                            theta=labels,
                            fill='toself',
                            name=top_similar_name
                        ))
                    
                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                        showlegend=True,
                        title="Percentile Radar"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                with col_bar:
                    fig_bar = go.Figure(go.Bar(
                        x=v1,
                        y=labels,
                        orientation='h',
                        name=player['full_name']
                    ))
                    fig_bar.update_layout(title="Percentiles (Horizontal)", xaxis=dict(range=[0, 100]))
                    st.plotly_chart(fig_bar, use_container_width=True)
