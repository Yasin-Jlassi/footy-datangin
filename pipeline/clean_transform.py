"""
Element 1 → 2 — Transform: dedupe, player_master matching, per-90 calc, upsert.
Identity key: full_name + birth_date + nationality (+ fbref_id as anchor).
Grain for player_season_stats: player + season + competition_id.
"""
import os
import psycopg2
import psycopg2.extras as pgx
import numpy as np

def get_db_dsn():
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise ValueError("DATABASE_URL environment variable is not set")
    return dsn

# raw counting-stat columns eligible for a *_per90 derived column (extend with schema)
PER90_COLUMNS = [
    "goals", "assists", "xg", "npxg", "xag",
    "shots", "tackles"
]

POSITION_GROUP_MAP = {
    "GK": "GK",
    "DF-CB": "CB", "CB": "CB",
    "DF-FB": "FB", "FB": "FB", "WB": "FB", "RB": "FB", "LB": "FB", "DF": "FB",
    "MF": "CM", "CM": "CM", "DM": "CM", "AM": "CM", "MF-DM": "CM", "MF-AM": "CM",
    "FW-W": "W", "W": "W", "WM": "W", "LW": "W", "RW": "W", "MF-FW": "W",
    "FW": "ST", "ST": "ST", "CF": "ST", "FW-ST": "ST"
}


def to_position_group(raw_position: str) -> str:
    return POSITION_GROUP_MAP.get(raw_position, "CM")  # default fallback, flag for manual review


def compute_per90(row: dict) -> dict:
    minutes = row.get("minutes_played") or 0
    out = {}
    for col in PER90_COLUMNS:
        raw_val = row.get(col) or 0
        out[f"{col}_per90"] = round((raw_val / minutes) * 90, 3) if minutes > 0 else None
    return out


def upsert_player_master(conn, player_row: dict) -> int:
    """
    Matches on (full_name, birth_date, nationality) per idx_player_master_dedup.
    fbref_id is the anchor source ID, kept unique.
    Returns player_id.
    """
    sql = """
        INSERT INTO player_master
            (fbref_id, full_name, birth_date, nationality, primary_position, position_group)
        VALUES (%(fbref_id)s, %(full_name)s, %(birth_date)s, %(nationality)s,
                %(primary_position)s, %(position_group)s)
        ON CONFLICT (full_name, birth_date, nationality) DO UPDATE SET
            primary_position = EXCLUDED.primary_position,
            position_group   = EXCLUDED.position_group,
            updated_at       = now()
        RETURNING player_id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, player_row)
        return cur.fetchone()[0]


def upsert_season_stats(conn, player_id: int, stats_row: dict):
    """Grain: player_id + season + competition_id. Adds per-90 columns before insert."""
    stats_row = {**stats_row, "player_id": player_id, **compute_per90(stats_row)}
    cols = list(stats_row.keys())
    sql = f"""
        INSERT INTO player_season_stats ({", ".join(cols)})
        VALUES ({", ".join(f"%({c})s" for c in cols)})
        ON CONFLICT (player_id, season, competition_id) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("player_id", "season", "competition_id"))},
            updated_at = now();
    """
    with conn.cursor() as cur:
        cur.execute(sql, stats_row)


def run_transform_and_load(fbref_df, open_data_df=None):
    """
    fbref_df: output of fetch_fbref_season, one row per player-season-competition.
    Dedupes on identity key, upserts player_master then player_season_stats per row.
    """
    conn = psycopg2.connect(get_db_dsn())
    rows_upserted = 0
    try:
        with conn:
            for _, row in fbref_df.drop_duplicates(
                subset=["player", "birth_year", "nation", "season", "league"]
            ).iterrows():
                player_row = {
                    "fbref_id": row["player_id"],
                    "full_name": row["player"],
                    "birth_date": row.get("birth_date") or f"{row['birth_year']}-01-01",
                    "nationality": row["nation"],
                    "primary_position": row.get("pos"),
                    "position_group": to_position_group(row.get("pos", "")),
                }
                pid = upsert_player_master(conn, player_row)

                def safe_int(val):
                    if val is None or (isinstance(val, float) and np.isnan(val)): return 0
                    return int(val)
                def safe_float(val):
                    if val is None or (isinstance(val, float) and np.isnan(val)): return 0.0
                    return float(val)

                stats_row = {
                    "season": row["season"],
                    "competition_id": row["league"],
                    "games_played": safe_int(row.get("games", 0)),
                    "games_started": safe_int(row.get("games_starts", 0)),
                    "minutes_played": safe_int(row.get("minutes", 0)),
                    "goals": safe_int(row.get("goals", 0)),
                    "assists": safe_int(row.get("assists", 0)),
                    "xg": safe_float(row.get("xg", 0)),
                    "npxg": safe_float(row.get("npxg", 0)),
                    "xag": safe_float(row.get("xg_assist", 0)),
                    "shots": safe_int(row.get("shots", 0)),
                    "shots_on_target": safe_int(row.get("shots_on_target", 0)),
                    "passes_completed": safe_int(row.get("passes_completed", 0)),
                    "passes_attempted": safe_int(row.get("passes", 0)),
                    "progressive_passes": safe_int(row.get("progressive_passes", 0)),
                    "key_passes": safe_int(row.get("assisted_shots", 0)),
                    "passes_into_final_third": safe_int(row.get("passes_into_final_third", 0)),
                    "passes_into_penalty_area": safe_int(row.get("passes_into_penalty_area", 0)),
                    "crosses_into_penalty_area": safe_int(row.get("crosses_into_penalty_area", 0)),
                    "passes_long_completed": safe_int(row.get("passes_long_completed", 0)),
                    "passes_long_attempted": safe_int(row.get("passes_long", 0)),
                    "tackles": safe_int(row.get("tackles", 0)),
                    "tackles_won": safe_int(row.get("tackles_won", 0)),
                    "interceptions": safe_int(row.get("interceptions", 0)),
                    "blocks": safe_int(row.get("blocks", 0)),
                    "clearances": safe_int(row.get("clearances", 0)),
                    "touches": safe_int(row.get("touches", 0)),
                    "touches_att_pen_area": safe_int(row.get("touches_att_pen_area", 0)),
                    "take_ons_won": safe_int(row.get("dribbles_completed", 0)),
                    "take_ons_attempted": safe_int(row.get("dribbles", 0)),
                    "progressive_carries": safe_int(row.get("progressive_carries", 0)),
                    "carries_into_final_third": safe_int(row.get("carries_into_final_third", 0)),
                    "carries_into_penalty_area": safe_int(row.get("carries_into_penalty_area", 0)),
                    "aerials_won": safe_int(row.get("aerials_won", 0)),
                    "aerials_lost": safe_int(row.get("aerials_lost", 0)),
                    "recoveries": safe_int(row.get("ball_recoveries", 0)),
                    "fouls": safe_int(row.get("fouls", 0)),
                    "fouled": safe_int(row.get("fouled", 0)),
                }

                if player_row["position_group"] == "GK":
                    stats_row.update({
                        "gk_saves": safe_int(row.get("saves", 0)),
                        "gk_shots_on_target_against": safe_int(row.get("shots_on_target_against", 0)),
                        "gk_goals_against": safe_int(row.get("goals_against", 0)),
                        "gk_clean_sheets": safe_int(row.get("clean_sheets", 0)),
                        "gk_psxg": safe_float(row.get("psxg", 0)),
                        "gk_crosses_faced": safe_int(row.get("crosses_faced", 0)),
                        "gk_crosses_stopped": safe_int(row.get("crosses_stopped", 0)),
                        "gk_def_actions_outside_pen": safe_int(row.get("def_actions_outside_pen_area", 0)),
                    })
                
                upsert_season_stats(conn, pid, stats_row)
                rows_upserted += 1
    finally:
        conn.close()
    return rows_upserted