"""
Element 1 — Ingestion / FBref source.
Uses Playwright FBref scraper with persistent profile to bypass Cloudflare Managed Challenges,
extracting standard and advanced commented stat tables.
"""
import os
import logging
import pandas as pd
from scraper.playwright_fbref import fetch_fbref_season_playwright

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Stat groups pulled per player-season; extend as new raw columns are added to the schema.
STAT_TYPES = ["standard", "shooting", "passing", "defense", "possession", "misc", "keepers", "keepersadv"]


def fetch_fbref_season(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """
    Returns one row per player-season-competition, wide across STAT_TYPES.
    `leagues` / `seasons` use naming (e.g. ["ENG-Premier League"], ["2324"]).
    """
    logger.info(f"Fetching FBref seasons via Playwright engine: leagues={leagues}, seasons={seasons}")
    df = fetch_fbref_season_playwright(leagues, seasons, stat_types=STAT_TYPES)
    if df is not None and not df.empty:
        return df

    raise ValueError("Failed to scrape any FBref stat types.")


def fetch_fbref_ids(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """Player metadata (player_id, birth_year, nation, team, league, season) for identity matching."""
    df = fetch_fbref_season_playwright(leagues, seasons, stat_types=["standard"])
    cols = [c for c in ["player", "player_id", "birth_year", "nation", "team", "league", "season"] if c in df.columns]
    return df[cols].drop_duplicates()


if __name__ == "__main__":
    df = fetch_fbref_season(["ENG-Premier League"], ["2324"])
    print("Fetched shape:", df.shape)
    print(df.head(3))