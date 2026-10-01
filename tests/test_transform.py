"""
Unit tests for Element 1 & 2: Transform, Deduplication, and Position Mapping.
"""
import pandas as pd
from pipeline.clean_transform import to_position_group as fbref_to_pos
from scraper.fetch_open_data import to_position_group as sb_to_pos


def test_fbref_position_mapping():
    assert fbref_to_pos("GK") == "GK"
    assert fbref_to_pos("CB") == "CB"
    assert fbref_to_pos("DF-CB") == "CB"
    assert fbref_to_pos("LB") == "FB"
    assert fbref_to_pos("RB") == "FB"
    assert fbref_to_pos("CM") == "CM"
    assert fbref_to_pos("DM") == "CM"
    assert fbref_to_pos("AM") == "CM"
    assert fbref_to_pos("LW") == "W"
    assert fbref_to_pos("RW") == "W"
    assert fbref_to_pos("ST") == "ST"
    assert fbref_to_pos("CF") == "ST"


def test_statsbomb_position_mapping():
    assert sb_to_pos("Goalkeeper") == "GK"
    assert sb_to_pos("Center Back") == "CB"
    assert sb_to_pos("Left Center Back") == "CB"
    assert sb_to_pos("Left Back") == "FB"
    assert sb_to_pos("Right Wing Back") == "FB"
    assert sb_to_pos("Center Defensive Midfield") == "CM"
    assert sb_to_pos("Center Attacking Midfield") == "CM"
    assert sb_to_pos("Left Wing") == "W"
    assert sb_to_pos("Right Midfield") == "W"
    assert sb_to_pos("Center Forward") == "ST"


def test_player_deduplication_keeps_distinct_seasons():
    # If the same player has stats in 2 different seasons, both must be preserved
    rows = [
        {"player": "Pedri", "birth_year": 2002, "nation": "ESP", "season": "2324", "league": "La Liga", "minutes": 1500},
        {"player": "Pedri", "birth_year": 2002, "nation": "ESP", "season": "2425", "league": "La Liga", "minutes": 1800},
        {"player": "Pedri", "birth_year": 2002, "nation": "ESP", "season": "2425", "league": "La Liga", "minutes": 1800}, # duplicate
    ]
    df = pd.DataFrame(rows)
    deduped = df.drop_duplicates(subset=["player", "birth_year", "nation", "season", "league"])

    assert len(deduped) == 2
    assert set(deduped["season"]) == {"2324", "2425"}
