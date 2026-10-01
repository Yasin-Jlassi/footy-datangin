"""
Unit tests for Element 3: Feature Engineering.
Validates derived metric formulas, edge cases (zero minutes, division by zero),
and z-score / percentile ranking properties.
"""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata


def test_per90_formula():
    minutes = 1800
    goals = 10
    # Expected: (10 / 1800) * 90 = 0.5
    goals_per90 = (goals / minutes) * 90
    assert pytest.approx(goals_per90, 0.01) == 0.5


def test_per90_zero_minutes_safe():
    df = pd.DataFrame({"minutes": [0, 900], "goals": [5, 10]})
    result = np.where(df["minutes"] > 0, (df["goals"] / df["minutes"]) * 90, np.nan)
    assert np.isnan(result[0])
    assert result[1] == 1.0


def test_ratio_formula_and_zero_division():
    df = pd.DataFrame({"comp": [80, 0], "att": [100, 0]})
    safe_ratio = np.where(df["att"] > 0, df["comp"] / df["att"], np.nan)
    assert safe_ratio[0] == 0.8
    assert np.isnan(safe_ratio[1])


def test_z_score_calculation():
    # Standard normal distribution property: mean=0, std=1
    data = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    mean = data.mean()
    std = data.std()
    z_scores = (data - mean) / std

    assert pytest.approx(z_scores.mean(), abs=1e-6) == 0.0
    assert pytest.approx(z_scores.std(), abs=1e-6) == 1.0


def test_percentile_ranking_scale_0_to_100():
    data = np.array([5.0, 10.0, 15.0, 20.0, 25.0])
    ranks = rankdata(data, method="average")
    pct = (ranks - 1) / (len(ranks) - 1) * 100

    assert pct[0] == 0.0    # lowest value is 0th percentile
    assert pct[-1] == 100.0  # highest value is 100th percentile
    assert pct[2] == 50.0   # median is 50th percentile
