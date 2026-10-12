"""
Footy DataNgin — Playwright FBref Ingestion Engine
Bypasses Cloudflare Managed Challenges via a persistent browser profile and extracts
both standard and secondary (commented) FBref tables using data-stat attributes.
"""
import os
import re
import time
import random
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
from bs4 import BeautifulSoup, Comment
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("SOCCERDATA_CACHE_DIR", os.path.expanduser("~/.soccerdata_cache")))
HTML_CACHE_DIR = CACHE_DIR / "fbref_html"
PROFILE_DIR = CACHE_DIR / "fbref_playwright_profile"

LEAGUE_CONFIG = {
    "ENG-Premier League": {"comp_id": "9", "slug": "Premier-League"},
    "ESP-La Liga": {"comp_id": "12", "slug": "La-Liga"},
    "GER-Bundesliga": {"comp_id": "20", "slug": "Bundesliga"},
    "ITA-Serie A": {"comp_id": "11", "slug": "Serie-A"},
    "FRA-Ligue 1": {"comp_id": "13", "slug": "Ligue-1"},
}

STAT_TYPE_MAP = {
    "standard": {"url_slug": "stats", "table_id": "stats_standard"},
    "shooting": {"url_slug": "shooting", "table_id": "stats_shooting"},
    "passing": {"url_slug": "passing", "table_id": "stats_passing"},
    "defense": {"url_slug": "defense", "table_id": "stats_defense"},
    "possession": {"url_slug": "possession", "table_id": "stats_possession"},
    "misc": {"url_slug": "misc", "table_id": "stats_misc"},
    "keepers": {"url_slug": "keepers", "table_id": "stats_keeper"},
    "keepersadv": {"url_slug": "keepersadv", "table_id": "stats_keeper_adv"},
}


def normalize_season(season: str | int) -> tuple[str, str]:
    """
    Returns (short_code, full_season_str), e.g. ("2324", "2023-2024").
    """
    s = str(season).strip()
    if len(s) == 4 and s.isdigit():
        y1 = int(s[:2])
        y2 = int(s[2:])
        if y1 < 100 and y2 < 100 and y2 == (y1 + 1) % 100:
            # e.g. "2324" -> "2023-2024"
            full = f"20{y1:02d}-20{y2:02d}"
            short = s
            return short, full
        elif int(s) >= 1990:
            # e.g. "2023" -> ("2324", "2023-2024")
            y_start = int(s)
            y_end = y_start + 1
            full = f"{y_start}-{y_end}"
            short = f"{str(y_start)[-2:]}{str(y_end)[-2:]}"
            return short, full
    elif "-" in s:
        # e.g. "2023-2024" -> ("2324", "2023-2024")
        parts = s.split("-")
        short = f"{parts[0][-2:]}{parts[1][-2:]}"
        return short, s
    return str(season), str(season)


class PlaywrightFBrefScraper:
    def __init__(self, headless: bool = False, cache_ttl_hours: int = 24):
        self.headless = headless
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        self.playwright = None
        self.context = None
        self.page = None

    def _start_browser(self):
        if self.page is not None:
            return
        logger.info(f"Launching Playwright browser (headless={self.headless}) with profile at {PROFILE_DIR}...")
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.playwright = None

    def __enter__(self):
        self._start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_html(self, url: str, cache_key: str) -> str:
        """Fetch URL with disk cache and Cloudflare verification check."""
        cache_file = HTML_CACHE_DIR / f"{cache_key}.html"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < self.cache_ttl_seconds:
                logger.debug(f"Reading from HTML cache: {cache_file.name}")
                return cache_file.read_text(encoding="utf-8")

        self._start_browser()
        logger.info(f"Navigating to: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Allow Cloudflare challenge to pass
        for _ in range(15):
            title = self.page.title()
            if "Just a moment" not in title and not title.startswith("Loading"):
                break
            time.sleep(1)

        time.sleep(2)  # Allow DOM to settle
        content = self.page.content()

        # Cache valid HTML
        if "<table" in content:
            cache_file.write_text(content, encoding="utf-8")

        # Sleep to respect FBref rate limits (<= 20 req/min)
        sleep_delay = random.uniform(3.5, 5.5)
        logger.info(f"Pacing delay: sleeping {sleep_delay:.2f}s...")
        time.sleep(sleep_delay)

        return content

    @staticmethod
    def parse_table_by_data_stat(html_content: str, target_table_id: str) -> pd.DataFrame:
        """
        Parses direct or HTML-commented tables using data-stat attributes and extracts player_id.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Search direct tables
        candidate_tables = soup.find_all("table")

        # Search commented tables (the FBref HTML comment trap)
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        for c in comments:
            if "<table" in c and target_table_id in c:
                c_soup = BeautifulSoup(c, "html.parser")
                candidate_tables.extend(c_soup.find_all("table"))

        table_node = None
        for t in candidate_tables:
            if t.get("id") == target_table_id:
                table_node = t
                break

        if not table_node:
            logger.warning(f"Table '{target_table_id}' not found in HTML.")
            return pd.DataFrame()

        rows = []
        tbody = table_node.find("tbody")
        if not tbody:
            return pd.DataFrame()

        for tr in tbody.find_all("tr"):
            if "thead" in tr.get("class", []):
                continue
            row = {}
            for cell in tr.find_all(["th", "td"]):
                stat = cell.get("data-stat")
                if not stat:
                    continue
                row[stat] = cell.get_text(strip=True)
                if stat == "player":
                    a = cell.find("a")
                    if a and a.get("href"):
                        # Format: /en/players/e342ad68/Brenden-Aaronson
                        parts = a["href"].split("/")
                        if len(parts) >= 4 and parts[2] == "players":
                            row["player_id"] = parts[3]

            if row.get("player"):
                rows.append(row)

        df = pd.DataFrame(rows)
        return df


def fetch_fbref_season_playwright(
    leagues: list[str],
    seasons: list[str],
    stat_types: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Fetches one row per player-season-competition wide across STAT_TYPES.
    Produces identical columns and keys expected by pipeline.clean_transform.
    """
    if stat_types is None:
        stat_types = ["standard", "shooting", "passing", "defense", "possession", "misc", "keepers", "keepersadv"]

    all_league_dfs = []

    with PlaywrightFBrefScraper(headless=False) as scraper:
        for league in leagues:
            if league not in LEAGUE_CONFIG:
                logger.error(f"League '{league}' not recognized in LEAGUE_CONFIG. Skipping.")
                continue

            cfg = LEAGUE_CONFIG[league]
            comp_id = cfg["comp_id"]
            league_slug = cfg["slug"]

            for season in seasons:
                short_season, full_season = normalize_season(season)
                logger.info(f"--- Fetching {league} ({short_season}) ---")

                type_dfs = []
                for stat_type in stat_types:
                    if stat_type not in STAT_TYPE_MAP:
                        continue

                    s_info = STAT_TYPE_MAP[stat_type]
                    url_slug = s_info["url_slug"]
                    table_id = s_info["table_id"]

                    # Determine URL structure (historical season vs current)
                    # Historical format: /en/comps/{id}/{full_season}/{url_slug}/{full_season}-{league_slug}-Stats
                    # Current format fallback if season matches 2024-2025 / 2425
                    cache_key = f"{league_slug}_{short_season}_{stat_type}"
                    url = f"https://fbref.com/en/comps/{comp_id}/{full_season}/{url_slug}/{full_season}-{league_slug}-Stats"

                    try:
                        html_content = scraper.get_html(url, cache_key=cache_key)
                        df_stat = scraper.parse_table_by_data_stat(html_content, table_id)
                        if not df_stat.empty and "player_id" in df_stat.columns:
                            # Drop duplicate player_id entries in same table if any
                            df_stat = df_stat.drop_duplicates(subset=["player_id"]).set_index("player_id")
                            type_dfs.append(df_stat)
                    except Exception as e:
                        logger.warning(f"Failed to fetch {stat_type} for {league} {short_season}: {e}")

                if not type_dfs:
                    logger.warning(f"No stat tables retrieved for {league} {short_season}.")
                    continue

                # Merge all stat types horizontally on player_id
                combined = type_dfs[0]
                for df in type_dfs[1:]:
                    # Avoid duplicated columns on join
                    cols_to_use = [c for c in df.columns if c not in combined.columns]
                    if cols_to_use:
                        combined = combined.join(df[cols_to_use], how="outer")

                combined = combined.reset_index()

                # Add metadata columns required by clean_transform
                combined["league"] = league
                combined["season"] = short_season

                # Map column aliases expected by clean_transform.py
                if "position" in combined.columns and "pos" not in combined.columns:
                    combined["pos"] = combined["position"]
                if "nationality" in combined.columns and "nation" not in combined.columns:
                    # e.g. "eng ENG" -> "ENG"
                    combined["nation"] = combined["nationality"].str.extract(r"([A-Z]{3})")[0].fillna(combined["nationality"])

                all_league_dfs.append(combined)

    if not all_league_dfs:
        return pd.DataFrame()

    final_df = pd.concat(all_league_dfs, ignore_index=True)
    return final_df
