import os
import tomllib
import psycopg2
import psycopg2.extras
import pandas as pd
import streamlit as st
from datetime import date

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'settings.toml')
with open(CONFIG_PATH, "rb") as f:
    config = tomllib.load(f)

CACHE_TTL = config.get("dashboard", {}).get("cache_ttl", 3600)

@st.cache_resource
def get_connection():
    # Streamlit Cloud uses st.secrets; local/CI uses env var
    db_url = None
    try:
        db_url = st.secrets["DATABASE_URL"]
    except (KeyError, FileNotFoundError):
        db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not found in st.secrets or environment variables")
    return psycopg2.connect(db_url)

@st.cache_data(ttl=CACHE_TTL)
def search_players(query: str) -> pd.DataFrame:
    conn = get_connection()
    sql = """
        SELECT player_id, full_name, nationality, position_group, birth_date
        FROM player_master
        WHERE full_name ILIKE %s
        ORDER BY full_name
        LIMIT 50
    """
    df = pd.read_sql_query(sql, conn, params=(f"%{query}%",))
    if not df.empty:
        df["player_id"] = df["player_id"].astype(int)
    return df

@st.cache_data(ttl=CACHE_TTL)
def get_player(player_id: int) -> dict:
    player_id = int(player_id)
    conn = get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT * FROM player_master WHERE player_id = %s", (player_id,))
        row = cur.fetchone()
        return dict(row) if row else {}

@st.cache_data(ttl=CACHE_TTL)
def get_player_stats(player_id: int) -> pd.DataFrame:
    player_id = int(player_id)
    conn = get_connection()
    sql = """
        SELECT *
        FROM player_season_stats
        WHERE player_id = %s
        ORDER BY season DESC, competition_id
    """
    return pd.read_sql_query(sql, conn, params=(player_id,))

@st.cache_data(ttl=CACHE_TTL)
def get_similar_players(player_id: int, top_n: int = 10) -> pd.DataFrame:
    player_id = int(player_id)
    conn = get_connection()
    sql = """
        WITH sim AS (
            SELECT player_id_b AS similar_id, similarity_score
            FROM similarity_matrix
            WHERE player_id_a = %s
            UNION ALL
            SELECT player_id_a AS similar_id, similarity_score
            FROM similarity_matrix
            WHERE player_id_b = %s
        )
        SELECT p.player_id, p.full_name, p.nationality, p.position_group, s.similarity_score
        FROM sim s
        JOIN player_master p ON p.player_id = s.similar_id
        ORDER BY s.similarity_score DESC
        LIMIT %s
    """
    return pd.read_sql_query(sql, conn, params=(player_id, player_id, top_n))

@st.cache_data(ttl=CACHE_TTL)
def get_pairwise_similarity(player_id_a: int, player_id_b: int) -> float | None:
    player_id_a, player_id_b = int(player_id_a), int(player_id_b)
    if player_id_a > player_id_b:
        player_id_a, player_id_b = player_id_b, player_id_a
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT similarity_score
            FROM similarity_matrix
            WHERE player_id_a = %s AND player_id_b = %s
            LIMIT 1;
            """,
            (player_id_a, player_id_b),
        )
        row = cur.fetchone()
        return float(row[0]) if row else None

@st.cache_data(ttl=CACHE_TTL)
def get_player_percentiles(player_id: int, season: str, competition_id: str) -> dict:
    player_id = int(player_id)
    player = get_player(player_id)
    if not player:
        return {}
    pos = player.get("position_group")
    if not pos:
        return {}
    
    table_name = f"feature_{pos.lower()}"
    conn = get_connection()
    sql = f"""
        SELECT *
        FROM {table_name}
        WHERE player_id = %s AND season = %s AND competition_id = %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(sql, (player_id, season, competition_id))
        row = cur.fetchone()
        if not row:
            return {}
        return {k: v for k, v in row.items() if k.endswith("_pct")}

@st.cache_data(ttl=CACHE_TTL)
def browse_players(position_group: str | None, competition_id: str | None, min_age: int | None, max_age: int | None, page: int, page_size: int) -> tuple[pd.DataFrame, int]:
    conn = get_connection()
    
    where_clauses = ["1=1"]
    params = []
    
    if position_group and position_group != "All":
        where_clauses.append("p.position_group = %s")
        params.append(position_group)
    
    if min_age is not None:
        min_date = date.today().replace(year=date.today().year - min_age)
        where_clauses.append("p.birth_date <= %s")
        params.append(min_date)
        
    if max_age is not None:
        max_date = date.today().replace(year=date.today().year - max_age - 1)
        where_clauses.append("p.birth_date > %s")
        params.append(max_date)

    if competition_id and competition_id != "All":
        where_clauses.append("EXISTS (SELECT 1 FROM player_season_stats s WHERE s.player_id = p.player_id AND s.competition_id = %s)")
        params.append(competition_id)
        
    where_sql = " AND ".join(where_clauses)
    
    count_sql = f"SELECT COUNT(*) FROM player_master p WHERE {where_sql}"
    with conn.cursor() as cur:
        cur.execute(count_sql, tuple(params))
        total = cur.fetchone()[0]
        
    offset = (page - 1) * page_size
    
    # We join with current stats if possible, else just return master data
    data_sql = f"""
        SELECT p.player_id, p.full_name, p.nationality, p.position_group, p.birth_date,
               (SELECT season FROM player_season_stats WHERE player_id = p.player_id ORDER BY season DESC LIMIT 1) as latest_season
        FROM player_master p
        WHERE {where_sql}
        ORDER BY p.full_name
        LIMIT %s OFFSET %s
    """
    
    params.extend([page_size, offset])
    df = pd.read_sql_query(data_sql, conn, params=tuple(params))
    
    return df, total

@st.cache_data(ttl=CACHE_TTL)
def get_competitions() -> list[str]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT competition_id FROM player_season_stats ORDER BY competition_id")
        return [row[0] for row in cur.fetchall()]

@st.cache_data(ttl=CACHE_TTL)
def get_seasons() -> list[str]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT season FROM player_season_stats ORDER BY season DESC")
        return [row[0] for row in cur.fetchall()]
