"""
Element 1 — Ingestion entrypoint. Invoked by cron (Render/Railway) or a
Supabase Edge Function on the weekly (in-season) / monthly (off-season) schedule.

Full pipeline: scrape → transform/load → features → similarity → validate.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from pipeline.clean_transform import run_transform_and_load
from pipeline.features import run_features
from pipeline.model_similarity import run_similarity
from pipeline.validate import run_validation
from scraper.fetch_fbref import fetch_fbref_season

DB_DSN = os.environ["DATABASE_URL"]

# Load config for defaults
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

_CFG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.toml")
with open(_CFG_PATH, "rb") as f:
    _CFG = tomllib.load(f)

BACKFILL_SEASONS = _CFG["scraper"]["backfill_seasons"]
LEAGUES = _CFG["scraper"]["leagues"]


def log_run_start(conn) -> int:
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refresh_log (started_at) VALUES (%s) RETURNING run_id;",
            (datetime.now(timezone.utc),),
        )
        return cur.fetchone()[0]


def log_run_finish(
    conn,
    run_id: int,
    rows_scraped: int,
    rows_upserted: int,
    features_built: int,
    similarities_computed: int,
    silhouette_score: float | None,
    self_match_pass: bool | None,
):
    with conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE refresh_log
               SET finished_at = %s,
                   rows_scraped = %s,
                   rows_upserted = %s,
                   features_built = %s,
                   similarities_computed = %s,
                   silhouette_score = %s,
                   self_match_pass = %s
               WHERE run_id = %s;""",
            (
                datetime.now(timezone.utc),
                rows_scraped,
                rows_upserted,
                features_built,
                similarities_computed,
                silhouette_score,
                self_match_pass,
                run_id,
            ),
        )


def main():
    parser = argparse.ArgumentParser(description="Footy DataNgin — full refresh pipeline")
    parser.add_argument(
        "--seasons", nargs="*", default=None,
        help="e.g. --seasons 2425 (omit for full 3-season backfill)",
    )
    parser.add_argument("--leagues", nargs="*", default=LEAGUES)
    parser.add_argument(
        "--skip-model", action="store_true",
        help="Only scrape + transform, skip feature/similarity/validation steps",
    )
    parser.add_argument(
        "--delay", type=int, default=4,
        help="Base delay (seconds) between scraping different leagues",
    )
    args = parser.parse_args()

    seasons = args.seasons or BACKFILL_SEASONS

    conn = psycopg2.connect(DB_DSN)
    run_id = log_run_start(conn)

    # ── Step 1: Scrape ───────────────────────────────────────────────
    print(f"[1/4] Scraping FBref: leagues={args.leagues}, seasons={seasons}")
    
    import time
    import pandas as pd
    import logging
    
    all_dfs = []
    try:
        for i, league in enumerate(args.leagues):
            if i > 0:
                print(f"       Waiting {args.delay}s before next league...")
                time.sleep(args.delay)
            print(f"       Scraping {league}...")
            df = fetch_fbref_season([league], seasons)
            all_dfs.append(df)
            
        if not all_dfs:
            raise ValueError("No data scraped across any leagues.")
            
        fbref_df = pd.concat(all_dfs, ignore_index=True)
    except Exception as e:
        print(f"       [ERROR] Scraping failed entirely: {e}")
        logging.exception(e)
        log_run_finish(conn, run_id, 0, 0, 0, 0, None, None)
        conn.close()
        sys.exit(1)

    rows_scraped = len(fbref_df)
    print(f"       → {rows_scraped} rows scraped")

    # ── Step 2: Transform + Load ─────────────────────────────────────
    print("[2/4] Transform + upsert into player_master / player_season_stats")
    rows_upserted = run_transform_and_load(fbref_df)
    print(f"       → {rows_upserted} rows upserted")

    features_built = 0
    similarities_computed = 0
    silhouette_score = None
    self_match_pass = None

    if not args.skip_model:
        # ── Step 3: Feature engineering + similarity ─────────────────
        print("[3/4] Building features + computing similarity matrix")
        features_built = run_features(conn)
        print(f"       → {features_built} feature rows written")

        similarities_computed = run_similarity(conn)
        print(f"       → {similarities_computed} similarity pairs written")

        # ── Step 4: Validate ─────────────────────────────────────────
        print("[4/4] Running validation checks")
        silhouette_score, self_match_pass = run_validation(conn)
        print(f"       → silhouette={silhouette_score}, self_match_pass={self_match_pass}")
    else:
        print("[3/4] Skipped (--skip-model)")
        print("[4/4] Skipped (--skip-model)")

    log_run_finish(
        conn, run_id, rows_scraped, rows_upserted,
        features_built, similarities_computed,
        silhouette_score, self_match_pass,
    )
    conn.close()
    print(f"\n✓ run_id={run_id} complete")


if __name__ == "__main__":
    main()