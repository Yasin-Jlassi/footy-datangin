import streamlit as st
from views import search, detail, browse, compare

st.set_page_config(
    page_title="Footy DataNgin",
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.sidebar.title("Footy DataNgin")
    view = st.sidebar.radio("Navigation", ["Search", "Compare (1v1)", "Detail", "Browse"])
    
    if view == "Search":
        search.render()
    elif view == "Compare (1v1)":
        compare.render()
    elif view == "Detail":
        detail.render()
    elif view == "Browse":
        browse.render()

if __name__ == "__main__":
    main()
