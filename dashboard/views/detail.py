import streamlit as st
import plotly.express as px
from db import get_player, get_player_stats, search_players

def render():
    st.title("Player Details & Trends")
    
    # Player selector
    query = st.text_input("Search Player by Name to view details", value="")
    if query:
        results = search_players(query)
        if not results.empty:
            selected_id = st.selectbox(
                "Select Player",
                results['player_id'].tolist(),
                format_func=lambda x: results[results['player_id'] == x]['full_name'].iloc[0]
            )
            if selected_id:
                st.session_state['detail_player_id'] = selected_id
                
    if 'selected_player_id' in st.session_state and 'detail_player_id' not in st.session_state:
        st.session_state['detail_player_id'] = st.session_state['selected_player_id']
        
    if 'detail_player_id' in st.session_state:
        player_id = st.session_state['detail_player_id']
        player = get_player(player_id)
        
        if not player:
            st.session_state.pop('detail_player_id', None)
            st.session_state.pop('selected_player_id', None)
            st.info("Please search and select a player above.")
            return
            
        st.header(f"{player['full_name']} - Stats")
        
        stats = get_player_stats(player_id)
        if stats.empty:
            st.warning("No stats available.")
            return
            
        st.subheader("Season Stats")
        st.dataframe(stats, use_container_width=True, hide_index=True)
        
        st.subheader("Trends")
        # Define some key stats depending on position
        if player['position_group'] == 'GK':
            metrics = ['gk_saves', 'gk_clean_sheets', 'gk_psxg']
        else:
            metrics = ['goals_per90', 'assists_per90', 'xg_per90', 'tackles_per90']
            
        available_metrics = [m for m in metrics if m in stats.columns]
        
        if available_metrics:
            selected_metric = st.selectbox("Select Metric", available_metrics)
            
            # Simple trend plot
            fig = px.line(
                stats, 
                x="season", 
                y=selected_metric, 
                color="competition_id",
                markers=True,
                title=f"{selected_metric} over Seasons"
            )
            fig.update_xaxes(type='category')
            st.plotly_chart(fig, use_container_width=True)
