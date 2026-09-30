import streamlit as st
from db import browse_players, get_competitions, config

def render():
    st.title("Browse Players")
    
    col1, col2, col3 = st.columns(3)
    
    positions = ["All"] + config.get("positions", {}).get("groups", [])
    pos_group = col1.selectbox("Position Group", positions)
    
    comps = ["All"] + get_competitions()
    comp_id = col2.selectbox("Competition", comps)
    
    age_range = col3.slider("Age Range", min_value=15, max_value=45, value=(18, 35))
    
    page = st.number_input("Page", min_value=1, value=1)
    page_size = 20
    
    df, total = browse_players(
        pos_group if pos_group != "All" else None,
        comp_id if comp_id != "All" else None,
        age_range[0],
        age_range[1],
        page,
        page_size
    )
    
    st.write(f"Total results: {total} (Showing page {page})")
    
    if not df.empty:
        # Just display the DataFrame. In a real app we could use AgGrid or column configuration to make names clickable
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # Simple navigation to detail view by selection
        selected_id = st.selectbox(
            "Select a player to view details", 
            df['player_id'].tolist(),
            format_func=lambda x: df[df['player_id'] == x]['full_name'].iloc[0]
        )
        if st.button("Go to Detail View"):
            st.session_state['detail_player_id'] = selected_id
            st.success("Player selected. Switch to 'Detail' tab on the sidebar.")
    else:
        st.info("No players found matching the criteria.")
