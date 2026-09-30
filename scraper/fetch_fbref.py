"""
Element 1 — Ingestion / FBref source.
Wraps `soccerdata.FBref`. Local cache avoids redundant hits on free-tier rate limits.
"""
import os
import time
import random
import logging
from pathlib import Path
import soccerdata as sd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("SOCCERDATA_CACHE_DIR", os.path.expanduser("~/.soccerdata_cache")))

# Stat groups pulled per player-season; extend as new raw columns are added to the schema.
STAT_TYPES = ["standard", "shooting", "passing", "defense", "possession", "misc", "keepers", "keepersadv"]


def _get_fbref_with_retry(leagues: list[str], seasons: list[str]) -> sd.FBref:
    retries = [10, 30, 60]
    for attempt, delay in enumerate(retries + [0]):
        try:
            return sd.FBref(leagues=leagues, seasons=seasons, data_dir=CACHE_DIR)
        except Exception as e:
            if attempt < len(retries):
                logger.warning(f"sd.FBref initialization failed ({e}). Retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"sd.FBref initialization failed completely after {len(retries)} retries.")
                raise


def fetch_fbref_season(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """
    Returns one row per player-season-competition, wide across STAT_TYPES.
    `leagues` / `seasons` use soccerdata's naming (e.g. ["ENG-Premier League"], ["2425"]).
    """
    fbref = _get_fbref_with_retry(leagues, seasons)

    frames = []
    for stat_type in STAT_TYPES:
        logger.info(f"Scraping stat type: {stat_type}...")
        try:
            df = fbref.read_player_season_stats(stat_type=stat_type)
            frames.append(df)
        except Exception as e:
            logger.warning(f"Failed to scrape stat type '{stat_type}': {e}. Skipping...")
            continue
            
        sleep_time = random.uniform(3, 6)
        logger.info(f"Sleeping for {sleep_time:.2f}s...")
        time.sleep(sleep_time)

    if not frames:
        raise ValueError("Failed to scrape any stat types.")

    combined = frames[0]
    for df in frames[1:]:
        # multi-index on (league, season, team, player); avoid duplicate cols on join
        combined = combined.join(df, rsuffix=f"_{df.columns.name or 'x'}", how="outer")

    combined = combined.reset_index()
    return combined


def fetch_fbref_ids(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """Player metadata (fbref_id, birth_date, nationality) for identity matching."""
    fbref = _get_fbref_with_retry(leagues, seasons)
    try:
        df = fbref.read_player_season_stats(stat_type="standard")
    except Exception as e:
        logger.error(f"Failed to fetch standard stats for IDs: {e}")
        raise
    return df.reset_index()[
        ["player", "player_id", "birth_year", "nation", "team", "league", "season"]
    ]


if __name__ == "__main__":
    df = fetch_fbref_season(["ENG-Premier League"], ["2425"])
    print(df.shape)