"""
Element 1 → 2 → 3: Full pipeline entrypoint.
Orchestrates: Ingestion (StatsBomb Open Data + FBref) → Transform → Features → Similarity → Validate.
Invoked by scheduler (GitHub Actions cron) or manually via CLI.
"""
import argparse
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import psycopg2
import pandas as pd
import time
import logging

from pipeline.clean_transform import run_transform_and_load
from pipeline.features import run_features
from pipeline.model_similarity import run_similarity
from pipeline.validate import run_validation
from scraper.fetch_fbref import fetch_fbref_season
from scraper.fetch_open_data import run_statsbomb_ingestion

# Load config for defaults
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.toml")
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

LEAGUES = CONFIG.get("scraper", {}).get("leagues", [])
BACKFILL_SEASONS = CONFIG.get("scraper", {}).get("backfill_seasons", [])


def get_db_dsn():
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise ValueError("DATABASE_URL environment variable is not set")
    return dsn


def log_run_start(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO refresh_log (started_at)
            VALUES (now())
            RETURNING run_id;
            """
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def log_run_finish(
    conn,
    run_id: int,
    rows_scraped: int,
    rows_upserted: int,
    features_built: int,
    similarities_computed: int,
    silhouette_score: float | None,
    self_match_pass: bool | None,
    error_msg: str | None = None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE refresh_log SET
                finished_at           = now(),
                rows_scraped          = %s,
                rows_upserted         = %s,
                features_built        = %s,
                similarities_computed = %s,
                silhouette_score      = %s,
                self_match_pass       = %s
            WHERE run_id = %s;
            """,
            (
                rows_scraped,
                rows_upserted,
                features_built,
                similarities_computed,
                silhouette_score,
                self_match_pass,
                run_id,
            ),
        )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Footy DataNgin — full refresh pipeline")
    parser.add_argument(
        "--source",
        choices=["all", "statsbomb", "fbref"],
        default="all",
        help="Data source to ingest: 'statsbomb' (fast, reliable open data), 'fbref', or 'all' (attempts both)",
    )
    parser.add_argument(
        "--seasons",
        nargs="*",
        default=None,
        help="e.g. --seasons 2425 (omit for full 3-season backfill)",
    )
    parser.add_argument("--leagues", nargs="*", default=LEAGUES)
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Only scrape + transform, skip feature/similarity/validation steps",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=4,
        help="Base delay (seconds) between scraping different leagues",
    )
    args = parser.parse_args()

    seasons = args.seasons or BACKFILL_SEASONS
    conn = psycopg2.connect(get_db_dsn())
    run_id = log_run_start(conn)

    total_scraped = 0
    total_upserted = 0

    # ── Step 1: Ingestion & Transform ──────────────────────────────────
    print(f"\n[1/4] Ingesting data (Source: {args.source.upper()})")

    # A. StatsBomb Open Data
    if args.source in ("all", "statsbomb"):
        print("      -> Running StatsBomb Open Data ingestion (Euro 2024, Copa America 2024, Bundesliga)...")
        try:
            sb_upserted = run_statsbomb_ingestion(conn)
            total_scraped += sb_upserted
            total_upserted += sb_upserted
            print(f"      [OK] StatsBomb ingestion completed: {sb_upserted} player seasons")
        except Exception as e:
            print(f"      [WARNING] StatsBomb ingestion failed: {e}")
            logging.exception(e)

    # B. FBref (if requested)
    if args.source in ("all", "fbref"):
        print(f"      -> Attempting FBref scrape: leagues={args.leagues}, seasons={seasons}")
        all_dfs = []
        try:
            for i, league in enumerate(args.leagues):
                if i > 0:
                    time.sleep(args.delay)
                print(f"        Scraping {league}...")
                df = fetch_fbref_season([league], seasons)
                if df is not None and not df.empty:
                    all_dfs.append(df)

            if all_dfs:
                fbref_df = pd.concat(all_dfs, ignore_index=True)
                rows_scraped = len(fbref_df)
                total_scraped += rows_scraped
                print(f"        -> {rows_scraped} rows scraped from FBref")
                print("      -> Upserting FBref data into player_master / player_season_stats")
                rows_upserted = run_transform_and_load(fbref_df)
                total_upserted += rows_upserted
                print(f"        [OK] {rows_upserted} rows upserted from FBref")
            else:
                print("        [INFO] No data returned from FBref (blocked or empty).")
        except Exception as e:
            print(f"        [INFO] FBref scrape encountered an error or Cloudflare challenge: {e}")
            if args.source == "fbref" and total_upserted == 0:
                log_run_finish(conn, run_id, 0, 0, 0, 0, None, None, error_msg=str(e))
                conn.close()
                sys.exit(1)

    print(f"\n[2/4] Total Ingestion Summary: {total_scraped} scraped, {total_upserted} upserted")

    features_built = 0
    similarities_computed = 0
    silhouette_score = None
    self_match_pass = None

    if not args.skip_model:
        # ── Step 3: Feature engineering + similarity ─────────────────
        print("\n[3/4] Building features + computing similarity matrix")
        features_built = run_features(conn)
        print(f"       -> {features_built} feature rows written")

        similarities_computed = run_similarity(conn)
        print(f"       -> {similarities_computed} similarity pairs written")

        # ── Step 4: Validate ─────────────────────────────────────────
        print("\n[4/4] Running validation checks")
        silhouette_score, self_match_pass = run_validation(conn)
        print(f"       -> silhouette={silhouette_score}, self_match_pass={self_match_pass}")
    else:
        print("\n[3/4] Skipped (--skip-model)")
        print("[4/4] Skipped (--skip-model)")

    log_run_finish(
        conn,
        run_id,
        total_scraped,
        total_upserted,
        features_built,
        similarities_computed,
        silhouette_score,
        self_match_pass,
    )
    conn.close()
    print(f"\n[OK] run_id={run_id} complete!")


if __name__ == "__main__":
    main()