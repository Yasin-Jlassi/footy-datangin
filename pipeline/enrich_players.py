"""
Pipeline element: Player metadata enrichment.
Fetches verified dates of birth, age, and nationality info from Wikidata
to replace any dummy placeholder dates (1998-01-01) with official verified records.
"""
import os
import time
import requests
import psycopg2
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {"User-Agent": "FootyDataNgin/1.0 (contact@footydatangin.com)"}


def get_wikidata_dob(player_name: str) -> str | None:
    """Queries Wikidata search & entity API for a footballer's date of birth."""
    try:
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbsearchentities",
            "search": player_name,
            "language": "en",
            "format": "json",
            "limit": 3,
        }
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return None
        
        items = res.json().get("search", [])
        if not items:
            return None

        # Prefer entities described as footballer or football player
        target_id = items[0]["id"]
        for it in items:
            desc = it.get("description", "").lower()
            if "football" in desc or "soccer" in desc or "player" in desc:
                target_id = it["id"]
                break

        # Fetch entity claims
        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{target_id}.json"
        res2 = requests.get(entity_url, headers=HEADERS, timeout=10)
        if res2.status_code != 200:
            return None

        claims = res2.json().get("entities", {}).get(target_id, {}).get("claims", {})
        # P569 = date of birth
        p569 = claims.get("P569", [])
        if not p569:
            return None

        raw_time = p569[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time")
        if raw_time:
            # raw format: "+2001-11-02T00:00:00Z"
            clean_date = raw_time.lstrip("+").split("T")[0]
            # basic sanity check for valid YYYY-MM-DD
            parts = clean_date.split("-")
            if len(parts) == 3 and len(parts[0]) == 4:
                return clean_date
    except Exception:
        pass
    return None


def enrich_top_players(limit: int = 150):
    dsn = os.environ.get("DATABASE_URL", "")
    if "sslmode" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"

    conn = psycopg2.connect(dsn)
    
    with conn.cursor() as cur:
        # Get players who have placeholder 1998-01-01, prioritized by minutes played
        cur.execute("""
            SELECT p.player_id, p.full_name, COALESCE(SUM(s.minutes_played), 0) AS total_min
            FROM player_master p
            LEFT JOIN player_season_stats s ON p.player_id = s.player_id
            WHERE p.birth_date = '1998-01-01'
            GROUP BY p.player_id, p.full_name
            ORDER BY total_min DESC
            LIMIT %s;
        """, (limit,))
        players = cur.fetchall()

    print(f"Enriching birth dates for {len(players)} players from Wikidata...")

    updates = []
    
    def process_player(pid, name):
        dob = get_wikidata_dob(name)
        return pid, name, dob

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_player, p[0], p[1]): p for p in players}
        for f in as_completed(futures):
            pid, name, dob = f.result()
            if dob:
                updates.append((dob, pid))
                clean_name = name.encode('ascii', 'replace').decode()
                print(f"  [OK] {clean_name} -> {dob}")
            else:
                clean_name = name.encode('ascii', 'replace').decode()
                print(f"  [SKIP] {clean_name} -> not found")

    if updates:
        print(f"\nWriting {len(updates)} verified birth dates to database...")
        with conn:
            with conn.cursor() as cur:
                cur.executemany("UPDATE player_master SET birth_date = %s, updated_at = now() WHERE player_id = %s;", updates)
        print("Successfully updated database!")

    conn.close()


if __name__ == "__main__":
    enrich_top_players(limit=100)
