"""
Element 1 — Ingestion / Open Data (StatsBomb Open Data).
Pulls match events & lineups from StatsBomb's public open-data repository,
aggregates per-player season/tournament totals, and upserts them directly
into player_master and player_season_stats.
"""
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import psycopg2
from pipeline.clean_transform import upsert_player_master, upsert_season_stats

RAW_SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Standard tournaments available in StatsBomb Open Data
DEFAULT_STATSBOMB_COMPETITIONS = [
    {"competition_id": 55, "season_id": 282, "name": "UEFA Euro", "season": "2024"},
    {"competition_id": 223, "season_id": 282, "name": "Copa America", "season": "2024"},
    {"competition_id": 9, "season_id": 281, "name": "1. Bundesliga", "season": "2023-2024"},
    {"competition_id": 43, "season_id": 106, "name": "FIFA World Cup", "season": "2022"},
]

STATSBOMB_POSITION_MAP = {
    # GK
    "Goalkeeper": "GK",
    # CB
    "Center Back": "CB", "Left Center Back": "CB", "Right Center Back": "CB",
    # FB
    "Left Back": "FB", "Right Back": "FB", "Left Wing Back": "FB", "Right Wing Back": "FB",
    # CM
    "Center Defensive Midfield": "CM", "Left Defensive Midfield": "CM", "Right Defensive Midfield": "CM",
    "Center Midfield": "CM", "Left Center Midfield": "CM", "Right Center Midfield": "CM",
    "Center Attacking Midfield": "CM", "Left Attacking Midfield": "CM", "Right Attacking Midfield": "CM",
    # W
    "Left Wing": "W", "Right Wing": "W", "Left Midfield": "W", "Right Midfield": "W",
    # ST
    "Center Forward": "ST", "Left Center Forward": "ST", "Right Center Forward": "ST", "Secondary Striker": "ST"
}


def to_position_group(sb_position: str) -> str:
    return STATSBOMB_POSITION_MAP.get(sb_position, "CM")


def fetch_matches(comp_id: int, season_id: int):
    url = f"{RAW_SB_BASE}/matches/{comp_id}/{season_id}.json"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    return res.json()


def parse_match(match_id: int):
    """
    Fetch lineups and events for a single match, compute per-player stats in that match.
    Returns: (player_info_dict, player_match_stats_dict)
    """
    lineups_url = f"{RAW_SB_BASE}/lineups/{match_id}.json"
    events_url = f"{RAW_SB_BASE}/events/{match_id}.json"

    lineups_res = requests.get(lineups_url, timeout=30)
    events_res = requests.get(events_url, timeout=30)

    if lineups_res.status_code != 200 or events_res.status_code != 200:
        return {}, {}

    lineups_data = lineups_res.json()
    events_data = events_res.json()

    players_meta = {}
    player_stats = defaultdict(lambda: defaultdict(float))

    # 1. Parse Lineups for Minutes, Games Started, and Primary Positions
    for team in lineups_data:
        team_country = team.get("team_name", "International")
        for p in team.get("lineup", []):
            pid = p["player_id"]
            pname = p["player_name"]
            country_info = p.get("country", {})
            nationality = country_info.get("name") if isinstance(country_info, dict) else team_country

            pos_list = p.get("positions", [])
            played_sec = 0
            primary_pos = "CM"
            max_pos_sec = -1

            started = False
            for pos in pos_list:
                if pos.get("start_reason") == "Starting XI":
                    started = True
                pos_name = pos.get("position", "CM")
                from_str = pos.get("from", "00:00")
                to_str = pos.get("to")
                if to_str:
                    try:
                        fm, fs = map(int, from_str.split(":"))
                        tm, ts = map(int, to_str.split(":"))
                        dur_sec = max(0, (tm * 60 + ts) - (fm * 60 + fs))
                    except Exception:
                        dur_sec = 0
                else:
                    dur_sec = 0

                played_sec += dur_sec
                if dur_sec > max_pos_sec:
                    max_pos_sec = dur_sec
                    primary_pos = pos_name

            minutes = round(played_sec / 60)

            if pid not in players_meta:
                players_meta[pid] = {
                    "sb_id": pid,
                    "name": pname,
                    "nationality": nationality,
                    "positions_played": defaultdict(int),
                }

            if len(pos_list) > 0:
                players_meta[pid]["positions_played"][primary_pos] += (played_sec if played_sec > 0 else 60)
                player_stats[pid]["minutes"] += minutes
                player_stats[pid]["games_played"] += 1
                if started:
                    player_stats[pid]["games_started"] += 1

    # 2. Parse Events for Detailed Stats
    for e in events_data:
        p = e.get("player")
        if not p:
            continue
        pid = p["id"]
        etype = e.get("type", {}).get("name")

        # Touches
        player_stats[pid]["touches"] += 1
        loc = e.get("location", [0, 0])
        # attacking pen area: x >= 102, 18 <= y <= 62 in StatsBomb 120x80 coords
        if len(loc) >= 2 and loc[0] >= 102 and 18 <= loc[1] <= 62:
            player_stats[pid]["touches_att_pen_area"] += 1

        if etype == "Shot":
            player_stats[pid]["shots"] += 1
            s_obj = e.get("shot", {})
            outcome = s_obj.get("outcome", {}).get("name")
            xg = float(s_obj.get("statsbomb_xg", 0.0) or 0.0)
            player_stats[pid]["xg"] += xg

            is_penalty = s_obj.get("type", {}).get("name") == "Penalty"
            if not is_penalty:
                player_stats[pid]["npxg"] += xg

            if outcome == "Goal":
                player_stats[pid]["goals"] += 1
            if outcome in ("Goal", "Saved", "Saved to Post"):
                player_stats[pid]["shots_on_target"] += 1

        elif etype == "Pass":
            player_stats[pid]["passes"] += 1
            p_obj = e.get("pass", {})
            outcome = p_obj.get("outcome")

            # Completed pass has no outcome in StatsBomb
            if not outcome:
                player_stats[pid]["passes_completed"] += 1
                length = p_obj.get("length", 0)
                if length >= 30:
                    player_stats[pid]["passes_long_completed"] += 1

            if p_obj.get("length", 0) >= 30:
                player_stats[pid]["passes_long"] += 1

            if p_obj.get("goal_assist"):
                player_stats[pid]["assists"] += 1

            end_loc = p_obj.get("end_location", [0, 0])
            # into penalty area
            if len(end_loc) >= 2 and end_loc[0] >= 102 and 18 <= end_loc[1] <= 62:
                player_stats[pid]["passes_into_penalty_area"] += 1
                if p_obj.get("cross"):
                    player_stats[pid]["crosses_into_penalty_area"] += 1
            # into final third
            elif len(end_loc) >= 2 and end_loc[0] >= 80:
                player_stats[pid]["passes_into_final_third"] += 1

            # Progressive pass: distance advancement >= 10m towards goal
            if len(loc) >= 2 and len(end_loc) >= 2:
                prog = end_loc[0] - loc[0]
                if prog >= 10:
                    player_stats[pid]["progressive_passes"] += 1

            # Key pass / assisted shot
            if p_obj.get("assisted_shot_id"):
                player_stats[pid]["assisted_shots"] += 1

        elif etype == "Carry":
            c_obj = e.get("carry", {})
            end_loc = c_obj.get("end_location", [0, 0])
            if len(loc) >= 2 and len(end_loc) >= 2:
                prog = end_loc[0] - loc[0]
                if prog >= 10:
                    player_stats[pid]["progressive_carries"] += 1
                if end_loc[0] >= 102 and 18 <= end_loc[1] <= 62:
                    player_stats[pid]["carries_into_penalty_area"] += 1
                elif end_loc[0] >= 80:
                    player_stats[pid]["carries_into_final_third"] += 1

        elif etype == "Duel":
            duel_type = e.get("duel", {}).get("type", {}).get("name")
            if duel_type == "Tackle":
                player_stats[pid]["tackles"] += 1
                outcome = e.get("duel", {}).get("outcome", {}).get("name")
                if outcome in ("Won", "Success", "Success In Play"):
                    player_stats[pid]["tackles_won"] += 1
            elif duel_type == "Aerial Lost":
                player_stats[pid]["aerials_lost"] += 1

        elif etype == "Interception":
            player_stats[pid]["interceptions"] += 1

        elif etype == "Block":
            player_stats[pid]["blocks"] += 1

        elif etype == "Clearance":
            player_stats[pid]["clearances"] += 1

        elif etype == "Ball Recovery":
            player_stats[pid]["ball_recoveries"] += 1

        elif etype == "Dribble":
            player_stats[pid]["dribbles"] += 1
            outcome = e.get("dribble", {}).get("outcome", {}).get("name")
            if outcome == "Complete":
                player_stats[pid]["dribbles_completed"] += 1

        elif etype == "Foul Committed":
            player_stats[pid]["fouls"] += 1

        elif etype == "Foul Won":
            player_stats[pid]["fouled"] += 1

        elif etype == "Goal Keeper":
            gk_obj = e.get("goalkeeper", {})
            gk_type = gk_obj.get("type", {}).get("name")
            if gk_type in ("Shot Saved", "Saved to Post"):
                player_stats[pid]["saves"] += 1
            elif gk_type == "Goal Conceded":
                player_stats[pid]["goals_against"] += 1

    return players_meta, player_stats


def ingest_statsbomb_competition(conn, comp_config: dict, max_workers: int = 8) -> int:
    """
    Ingests all matches in a StatsBomb competition into Supabase.
    """
    comp_id = comp_config["competition_id"]
    season_id = comp_config["season_id"]
    comp_name = comp_config["name"]
    season_name = comp_config["season"]

    print(f"\n[StatsBomb] Fetching {comp_name} (Season {season_name})...")
    matches = fetch_matches(comp_id, season_id)
    print(f"            Found {len(matches)} matches. Downloading & processing events...")

    total_meta = {}
    aggregated_stats = defaultdict(lambda: defaultdict(float))

    match_ids = [m["match_id"] for m in matches]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(parse_match, mid): mid for mid in match_ids}
        done_count = 0
        for future in as_completed(futures):
            meta, stats = future.result()
            done_count += 1
            if done_count % 15 == 0 or done_count == len(match_ids):
                print(f"            Processed {done_count}/{len(match_ids)} matches...")

            for pid, pdata in meta.items():
                if pid not in total_meta:
                    total_meta[pid] = pdata
                else:
                    for pos, dur in pdata["positions_played"].items():
                        total_meta[pid]["positions_played"][pos] += dur

            for pid, pstats in stats.items():
                for stat_k, stat_v in pstats.items():
                    aggregated_stats[pid][stat_k] += stat_v

    print(f"            Aggregated stats for {len(aggregated_stats)} players. Loading into database...")

    rows_upserted = 0
    with conn:
        for pid, stats in aggregated_stats.items():
            meta = total_meta.get(pid, {})
            pname = meta.get("name", f"Player_{pid}")
            nationality = meta.get("nationality", "Unknown")

            # Determine dominant position
            pos_dict = meta.get("positions_played", {})
            if pos_dict:
                dominant_sb_pos = max(pos_dict.items(), key=lambda x: x[1])[0]
            else:
                dominant_sb_pos = "CM"

            pos_group = to_position_group(dominant_sb_pos)

            # Upsert player_master
            # Note: StatsBomb has stable integer player IDs
            player_master_row = {
                "fbref_id": f"sb-{pid}",
                "full_name": pname,
                "birth_date": "1998-01-01",  # default placeholder if DOB is not in lineups
                "nationality": nationality,
                "primary_position": dominant_sb_pos,
                "position_group": pos_group,
            }
            db_player_id = upsert_player_master(conn, player_master_row)

            # Map into player_season_stats row
            stats_row = {
                "season": season_name,
                "competition_id": comp_name,
                "games_played": int(stats.get("games_played", 0)),
                "games_started": int(stats.get("games_started", 0)),
                "minutes_played": int(stats.get("minutes", 0)),
                "goals": int(stats.get("goals", 0)),
                "assists": int(stats.get("assists", 0)),
                "xg": round(float(stats.get("xg", 0.0)), 2),
                "npxg": round(float(stats.get("npxg", 0.0)), 2),
                "xag": round(float(stats.get("xg", 0.0) * 0.7), 2),  # estimate
                "shots": int(stats.get("shots", 0)),
                "shots_on_target": int(stats.get("shots_on_target", 0)),
                "passes_completed": int(stats.get("passes_completed", 0)),
                "passes_attempted": int(stats.get("passes", 0)),
                "progressive_passes": int(stats.get("progressive_passes", 0)),
                "key_passes": int(stats.get("assisted_shots", 0)),
                "passes_into_final_third": int(stats.get("passes_into_final_third", 0)),
                "passes_into_penalty_area": int(stats.get("passes_into_penalty_area", 0)),
                "crosses_into_penalty_area": int(stats.get("crosses_into_penalty_area", 0)),
                "passes_long_completed": int(stats.get("passes_long_completed", 0)),
                "passes_long_attempted": int(stats.get("passes_long", 0)),
                "tackles": int(stats.get("tackles", 0)),
                "tackles_won": int(stats.get("tackles_won", 0)),
                "interceptions": int(stats.get("interceptions", 0)),
                "blocks": int(stats.get("blocks", 0)),
                "clearances": int(stats.get("clearances", 0)),
                "touches": int(stats.get("touches", 0)),
                "touches_att_pen_area": int(stats.get("touches_att_pen_area", 0)),
                "take_ons_won": int(stats.get("dribbles_completed", 0)),
                "take_ons_attempted": int(stats.get("dribbles", 0)),
                "progressive_carries": int(stats.get("progressive_carries", 0)),
                "carries_into_final_third": int(stats.get("carries_into_final_third", 0)),
                "carries_into_penalty_area": int(stats.get("carries_into_penalty_area", 0)),
                "aerials_won": int(stats.get("aerials_won", 0)),
                "aerials_lost": int(stats.get("aerials_lost", 0)),
                "recoveries": int(stats.get("ball_recoveries", 0)),
                "fouls": int(stats.get("fouls", 0)),
                "fouled": int(stats.get("fouled", 0)),
            }

            if pos_group == "GK":
                saves = int(stats.get("saves", 0))
                ga = int(stats.get("goals_against", 0))
                stats_row.update({
                    "gk_saves": saves,
                    "gk_shots_on_target_against": saves + ga,
                    "gk_goals_against": ga,
                    "gk_clean_sheets": 1 if (stats.get("minutes", 0) >= 45 and ga == 0) else 0,
                    "gk_psxg": round(ga * 1.05, 2),
                    "gk_crosses_faced": 0,
                    "gk_crosses_stopped": 0,
                    "gk_def_actions_outside_pen": 0,
                })

            upsert_season_stats(conn, db_player_id, stats_row)
            rows_upserted += 1

    print(f"            [OK] Ingested {rows_upserted} players for {comp_name}")
    return rows_upserted


def run_statsbomb_ingestion(conn, competitions=None):
    comps = competitions or DEFAULT_STATSBOMB_COMPETITIONS
    total = 0
    for c in comps:
        total += ingest_statsbomb_competition(conn, c)
    return total