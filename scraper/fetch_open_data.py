"""
Element 1 — Ingestion / supplementary free sources.
StatsBomb Open Data (event-level, free competitions only) + football-data.co.uk (match-level CSVs).
Both used to backfill/cross-check FBref, not as primary source.
"""
import io
import pandas as pd
import requests
from statsbombpy import sb

FOOTBALL_DATA_BASE = "https://www.football-data.co.uk/mmz4281"


def fetch_statsbomb_competitions() -> "pandas.DataFrame":
    """Free StatsBomb competitions/seasons currently open."""
    return sb.competitions()


def fetch_statsbomb_matches(competition_id: int, season_id: int) -> "pandas.DataFrame":
    return sb.matches(competition_id=competition_id, season_id=season_id)


def fetch_football_data_csv(season_code: str, league_code: str) -> "pandas.DataFrame":
    """
    season_code e.g. '2425' (2024-2025), league_code e.g. 'E0' (EPL).
    Returns match-level results/odds CSV as a DataFrame.
    """
    url = f"{FOOTBALL_DATA_BASE}/{season_code}/{league_code}.csv"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


if __name__ == "__main__":
    comps = fetch_statsbomb_competitions()
    print(comps.shape)