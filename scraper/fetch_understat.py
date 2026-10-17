"""
Element 1 — Ingestion / Understat source.
Pulls xG, npxG, xA (xAG), key_passes, shots, xGBuildup, and xGChain
from Understat JSON API across the top 5 leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1)
and updates player_season_stats with high-accuracy shot/chance/buildup creation metrics.
"""
import os
import re
import json
import gzip
import logging
import unicodedata
import urllib.request
import urllib.parse
from typing import Dict, List, Tuple
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

UNDERSTAT_LEAGUES = {
    "ENG-Premier League": "EPL",
    "ESP-La Liga": "La_liga",
    "GER-Bundesliga": "Bundesliga",
    "ITA-Serie A": "Serie_A",
    "FRA-Ligue 1": "Ligue_1",
}

# Season mapping: short code (DB) -> Understat year string
SEASON_MAP = {
    "2223": "2022",
    "2324": "2023",
    "2425": "2024",
}


def normalize_name(s: str) -> str:
    if not s:
        return ""
    # Strip accents / diacritics
    nfkd = unicodedata.normalize("NFD", s)
    no_accent = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    # Clean non-alphabet characters
    cleaned = re.sub(r"[^a-zA-Z\s]", "", no_accent).lower()
    return " ".join(cleaned.split())


def get_db_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if dsn.startswith("DATABASE_URL="):
        dsn = dsn.split("=", 1)[1].strip()
    dsn = dsn.strip("'\"")
    if not dsn:
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                for line in f:
                    if line.strip().startswith("DATABASE_URL="):
                        dsn = line.strip().split("=", 1)[1].strip().strip("'\"")
                        break
    if not dsn:
        raise ValueError("DATABASE_URL environment variable is not set")
    os.environ["DATABASE_URL"] = dsn
    return dsn


def fetch_understat_players(u_league: str, u_season: str) -> List[dict]:
    url = "https://understat.com/main/getPlayersStats/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": f"https://understat.com/league/{u_league}/{u_season}",
        "X-Requested-With": "XMLHttpRequest",
    }
    params = urllib.parse.urlencode({"league": u_league, "season": u_season}).encode("utf-8")
    req = urllib.request.Request(url, data=params, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read()
            try:
                decomp = gzip.decompress(raw).decode("utf-8")
            except Exception:
                decomp = raw.decode("utf-8")
            data = json.loads(decomp)
            return data.get("players", [])
    except Exception as e:
        logger.warning(f"Failed to fetch Understat for {u_league} {u_season}: {e}")
        return []


def load_player_master_map(conn) -> Tuple[Dict[str, int], Dict[Tuple[str, str], int]]:
    """
    Returns:
      1. full_name_map: normalized_name -> player_id
      2. name_team_map: (normalized_name, normalized_team) -> player_id
    """
    with conn.cursor() as cur:
        cur.execute("SELECT player_id, full_name FROM player_master;")
        rows = cur.fetchall()

    full_name_map = {}
    for pid, fname in rows:
        n = normalize_name(fname)
        if n and n not in full_name_map:
            full_name_map[n] = pid

    return full_name_map


def run_understat_ingestion(conn=None, seasons: List[str] = None) -> int:
    """
    Ingests xG, npxG, xA, key_passes, xGBuildup, xGChain from Understat
    and enriches matching player_season_stats rows.
    """
    close_conn = False
    if conn is None:
        conn = psycopg2.connect(get_db_dsn())
        close_conn = True

    if seasons is None:
        seasons = ["2223", "2324", "2425"]

    total_updated = 0
    try:
        full_name_map = load_player_master_map(conn)
        logger.info(f"Loaded {len(full_name_map)} player names from player_master for matching.")

        for db_league, u_league in UNDERSTAT_LEAGUES.items():
            for db_season in seasons:
                if db_season not in SEASON_MAP:
                    continue
                u_season = SEASON_MAP[db_season]
                logger.info(f"Fetching Understat: {db_league} ({u_season})...")

                u_players = fetch_understat_players(u_league, u_season)
                if not u_players:
                    continue

                update_tuples = []
                for p in u_players:
                    pname = p.get("player_name", "")
                    norm_pname = normalize_name(pname)
                    pid = full_name_map.get(norm_pname)

                    if not pid:
                        # Try matching on last name + first initial or partial tokens
                        parts = norm_pname.split()
                        if len(parts) >= 2:
                            # e.g. "moises caicedo" -> check if any player ends with last name
                            for candidate_name, candidate_id in full_name_map.items():
                                if candidate_name.endswith(parts[-1]) and candidate_name.startswith(parts[0][:3]):
                                    pid = candidate_id
                                    break

                    if not pid:
                        continue

                    def safe_f(val):
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return 0.0

                    xg = safe_f(p.get("xG"))
                    npxg = safe_f(p.get("npxG"))
                    xag = safe_f(p.get("xA"))
                    key_passes = int(safe_f(p.get("key_passes")))
                    xg_buildup = safe_f(p.get("xGBuildup"))
                    xg_chain = safe_f(p.get("xGChain"))
                    minutes = int(safe_f(p.get("time")))
                    games = int(safe_f(p.get("games")))
                    shots = int(safe_f(p.get("shots")))
                    goals = int(safe_f(p.get("goals")))
                    assists = int(safe_f(p.get("assists")))

                    update_tuples.append((
                        xg, npxg, xag, key_passes, xg_buildup, xg_chain,
                        minutes, games, shots, goals, assists,
                        pid, db_season, db_league
                    ))

                if update_tuples:
                    with conn.cursor() as cur:
                        update_sql = """
                            UPDATE player_season_stats SET
                                xg = %s,
                                npxg = %s,
                                xag = %s,
                                key_passes = GREATEST(key_passes, %s),
                                xg_buildup = %s,
                                xg_chain = %s,
                                minutes_played = GREATEST(minutes_played, %s),
                                games_played = GREATEST(games_played, %s),
                                shots = GREATEST(shots, %s),
                                goals = GREATEST(goals, %s),
                                assists = GREATEST(assists, %s),
                                tackles = GREATEST(tackles, tackles_won),
                                updated_at = now()
                            WHERE player_id = %s AND season = %s AND competition_id = %s;
                        """
                        cur.executemany(update_sql, update_tuples)
                        total_updated += len(update_tuples)
                    conn.commit()
                    logger.info(f"Updated {len(update_tuples)} player stats for {db_league} {db_season}.")

        # Recompute denormalized per90 columns in player_season_stats
        with conn.cursor() as cur:
            recompute_sql = """
                UPDATE player_season_stats SET
                    goals_per90   = ROUND((COALESCE(goals, 0)::numeric / minutes_played) * 90, 3),
                    assists_per90 = ROUND((COALESCE(assists, 0)::numeric / minutes_played) * 90, 3),
                    xg_per90      = ROUND((COALESCE(xg, 0)::numeric / minutes_played) * 90, 3),
                    npxg_per90    = ROUND((COALESCE(npxg, 0)::numeric / minutes_played) * 90, 3),
                    xag_per90     = ROUND((COALESCE(xag, 0)::numeric / minutes_played) * 90, 3),
                    shots_per90   = ROUND((COALESCE(shots, 0)::numeric / minutes_played) * 90, 3),
                    tackles_per90 = ROUND((COALESCE(tackles, 0)::numeric / minutes_played) * 90, 3)
                WHERE minutes_played > 0;
            """
            cur.execute(recompute_sql)
        conn.commit()
        logger.info(f"Understat ingestion complete: {total_updated} records enriched and per90 metrics recomputed.")
        return total_updated
    finally:
        if close_conn:
            conn.close()


if __name__ == "__main__":
    conn = psycopg2.connect(get_db_dsn())
    updated = run_understat_ingestion(conn)
    print(f"Total updated: {updated}")
    conn.close()
