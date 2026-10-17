"""
Footy DataNgin — FotMob Enrichment Engine
Enriches player_season_stats with Opta event metrics pulled from FotMob's CDN:
- Accurate passes completed & attempted
- Long balls completed
- Clearances
- Blocks
- Take-ons won & attempted (dribbles)
- Recoveries
"""

import os
import re
import json
import gzip
import logging
import unicodedata
import urllib.request
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras as pgx

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# FotMob Tournament / Season IDs for the Big 5 Leagues
FOTMOB_LEAGUE_MAP = {
    "ENG-Premier League": {
        "league_id": 47,
        "seasons": {"2223": 17664, "2324": 20720, "2425": 23685},
    },
    "ESP-La Liga": {
        "league_id": 87,
        "seasons": {"2223": 17852, "2324": 21053, "2425": 23686},
    },
    "FRA-Ligue 1": {
        "league_id": 53,
        "seasons": {"2223": 17810, "2324": 20868, "2425": 23724},
    },
    "GER-Bundesliga": {
        "league_id": 54,
        "seasons": {"2223": 17801, "2324": 20946, "2425": 23794},
    },
    "ITA-Serie A": {
        "league_id": 55,
        "seasons": {"2223": 17866, "2324": 20956, "2425": 23819},
    },
}

STAT_FILES = [
    "accurate_pass",
    "accurate_long_balls",
    "effective_clearance",
    "outfielder_block",
    "won_contest",
    "ball_recovery",
]

COMMON_ALIASES = {
    "dan burn": "daniel burn",
    "daniel burn": "dan burn",
    "savio": "savinho",
    "savinho": "savio",
    "amad diallo": "amad",
    "amad": "amad diallo",
    "tino livramento": "valentino livramento",
    "valentino livramento": "tino livramento",
    "pape matar sarr": "pape sarr",
    "pape sarr": "pape matar sarr",
    "heung min son": "son heung min",
    "son heung min": "heung min son",
    "hwang hee chan": "hee chan hwang",
}


def normalize_name(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFD", s)
    no_accent = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    cleaned = re.sub(r"[^a-zA-Z\s]", "", no_accent).lower()
    norm = " ".join(cleaned.split())
    return COMMON_ALIASES.get(norm, norm)


def fetch_fotmob_stat(league_id: int, tournament_id: int, stat_name: str) -> List[dict]:
    url = f"https://data.fotmob.com/stats/{league_id}/season/{tournament_id}/{stat_name}.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept-Encoding": "gzip",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read()
            try:
                content = gzip.decompress(raw).decode("utf-8")
            except Exception:
                content = raw.decode("utf-8")
            data = json.loads(content)
            top_lists = data.get("TopLists", [])
            if top_lists and "StatList" in top_lists[0]:
                return top_lists[0]["StatList"]
    except Exception as e:
        logger.debug(f"Failed to fetch FotMob stat {stat_name} ({url}): {e}")
    return []


def load_player_index(conn) -> Tuple[Dict[str, int], Dict[str, List[Tuple[int, str]]]]:
    exact_map = {}
    last_name_map = {}

    with conn.cursor() as cur:
        cur.execute("SELECT player_id, full_name, nationality FROM player_master;")
        for pid, name, nat in cur.fetchall():
            norm = normalize_name(name)
            exact_map[norm] = pid
            parts = norm.split()
            if parts:
                last_name = parts[-1]
                last_name_map.setdefault(last_name, []).append((pid, norm))

    return exact_map, last_name_map


def match_player_id(raw_name: str, exact_map: dict, last_name_map: dict) -> Optional[int]:
    norm = normalize_name(raw_name)
    if norm in exact_map:
        return exact_map[norm]

    # Try last name matching if unique or closest match
    parts = norm.split()
    if parts:
        last_name = parts[-1]
        candidates = last_name_map.get(last_name, [])
        if len(candidates) == 1:
            return candidates[0][0]
        # Multi-word substring match
        for pid, cand_norm in candidates:
            if parts[0] in cand_norm:
                return pid

    return None


def enrich_fotmob_season(conn, competition_id: str, season: str, exact_map: dict, last_name_map: dict) -> int:
    cfg = FOTMOB_LEAGUE_MAP.get(competition_id)
    if not cfg:
        return 0

    league_id = cfg["league_id"]
    tournament_id = cfg["seasons"].get(season)
    if not tournament_id:
        return 0

    player_stats: Dict[int, dict] = {}

    for stat_name in STAT_FILES:
        stat_list = fetch_fotmob_stat(league_id, tournament_id, stat_name)
        for item in stat_list:
            p_name = item.get("ParticipantName", "")
            pid = match_player_id(p_name, exact_map, last_name_map)
            if not pid:
                continue

            if pid not in player_stats:
                player_stats[pid] = {
                    "player_id": pid,
                    "season": season,
                    "competition_id": competition_id,
                    "passes_completed": 0,
                    "passes_attempted": 0,
                    "passes_long_completed": 0,
                    "clearances": 0,
                    "blocks": 0,
                    "take_ons_won": 0,
                    "take_ons_attempted": 0,
                    "recoveries": 0,
                }

            rec = player_stats[pid]
            try:
                stat_val = float(item.get("StatValue") or 0.0)
                sub_stat = float(item.get("SubStatValue") or 0.0)
                mins = float(item.get("MinutesPlayed") or 0.0)
            except (ValueError, TypeError):
                continue

            if stat_name == "accurate_pass":
                # StatValue = accurate passes per 90, SubStatValue = pass accuracy %
                passes_cmp = round(stat_val * (mins / 90.0))
                rec["passes_completed"] = passes_cmp
                if sub_stat > 0:
                    rec["passes_attempted"] = round(passes_cmp / (sub_stat / 100.0))
                else:
                    rec["passes_attempted"] = passes_cmp

            elif stat_name == "accurate_long_balls":
                # StatValue = accurate long balls per 90
                rec["passes_long_completed"] = round(stat_val * (mins / 90.0))

            elif stat_name == "effective_clearance":
                # SubStatValue is total clearances
                rec["clearances"] = round(sub_stat) if sub_stat > 0 else round(stat_val * (mins / 90.0))

            elif stat_name == "outfielder_block":
                # SubStatValue is total blocks
                rec["blocks"] = round(sub_stat) if sub_stat > 0 else round(stat_val * (mins / 90.0))

            elif stat_name == "won_contest":
                # StatValue = dribbles per 90, SubStatValue = success %
                won = round(stat_val * (mins / 90.0))
                rec["take_ons_won"] = won
                if sub_stat > 0:
                    rec["take_ons_attempted"] = round(won / (sub_stat / 100.0))
                else:
                    rec["take_ons_attempted"] = won

            elif stat_name == "ball_recovery":
                rec["recoveries"] = round(sub_stat) if sub_stat > 0 else round(stat_val * (mins / 90.0))

    if not player_stats:
        return 0

    records = list(player_stats.values())
    update_sql = """
        UPDATE player_season_stats
        SET
            passes_completed = GREATEST(player_season_stats.passes_completed, %(passes_completed)s),
            passes_attempted = GREATEST(player_season_stats.passes_attempted, %(passes_attempted)s),
            passes_long_completed = GREATEST(player_season_stats.passes_long_completed, %(passes_long_completed)s),
            clearances = GREATEST(player_season_stats.clearances, %(clearances)s),
            blocks = GREATEST(player_season_stats.blocks, %(blocks)s),
            take_ons_won = GREATEST(player_season_stats.take_ons_won, %(take_ons_won)s),
            take_ons_attempted = GREATEST(player_season_stats.take_ons_attempted, %(take_ons_attempted)s),
            recoveries = GREATEST(player_season_stats.recoveries, %(recoveries)s),
            updated_at = now()
        WHERE player_id = %(player_id)s
          AND season = %(season)s
          AND competition_id = %(competition_id)s;
    """

    with conn.cursor() as cur:
        pgx.execute_batch(cur, update_sql, records, page_size=500)
    conn.commit()

    logger.info(f"Updated FotMob metrics for {len(records)} players in {competition_id} ({season})")
    return len(records)


def run_fotmob_enrichment(conn, leagues: Optional[List[str]] = None, seasons: Optional[List[str]] = None) -> int:
    target_leagues = leagues or list(FOTMOB_LEAGUE_MAP.keys())
    target_seasons = seasons or ["2223", "2324", "2425"]

    exact_map, last_name_map = load_player_index(conn)
    logger.info(f"Loaded {len(exact_map)} player identities for FotMob matching.")

    total_enriched = 0
    for league in target_leagues:
        for season in target_seasons:
            enriched = enrich_fotmob_season(conn, league, season, exact_map, last_name_map)
            total_enriched += enriched

    return total_enriched


if __name__ == "__main__":
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from pipeline.clean_transform import get_db_dsn

    conn = psycopg2.connect(get_db_dsn())
    count = run_fotmob_enrichment(conn)
    print(f"[OK] FotMob enrichment complete: {count} player seasons updated.")
    conn.close()
