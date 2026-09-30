import streamlit as st
from views import search, detail, browse

st.set_page_config(
    page_title="Footy DataNgin",
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.sidebar.title("Footy DataNgin")
    view = st.sidebar.radio("Navigation", ["Search", "Detail", "Browse"])
    
    if view == "Search":
        search.render()
    elif view == "Detail":
        detail.render()
    elif view == "Browse":
        browse.render()

if __name__ == "__main__":
    main()
