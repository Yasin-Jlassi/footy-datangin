"""
Element 3 — Feature engineering.
Reads player_season_stats, computes per-position derived metrics,
z-scores and percentile-ranks them, writes to feature_* tables.
"""
import os
import psycopg2
import psycopg2.extras as pgx

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import pandas as pd
import numpy as np
from scipy.stats import rankdata


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _safe_python(val):
    """Convert numpy types to Python native types for psycopg2."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val


def run_features(conn) -> int:
    config = load_config()
    min_minutes = config.get("scraper", {}).get("min_minutes", 450)
    groups = config.get("positions", {}).get("groups", [])
    features_config = config.get("features", {})

    total_written = 0

    for group in groups:
        if group not in features_config:
            continue

        group_features = features_config[group]

        # Avoid duplicate player_id by only selecting from s + joining position_group
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.player_id, s.season, s.competition_id, s.minutes_played,
                       s.goals, s.assists, s.xg, s.npxg, s.xag,
                       s.shots, s.shots_on_target,
                       s.passes_completed, s.passes_attempted,
                       s.progressive_passes, s.key_passes,
                       s.passes_into_final_third, s.passes_into_penalty_area,
                       s.crosses_into_penalty_area,
                       s.passes_long_completed, s.passes_long_attempted,
                       s.tackles, s.tackles_won,
                       s.interceptions, s.blocks, s.clearances,
                       s.touches, s.touches_att_pen_area,
                       s.take_ons_won, s.take_ons_attempted,
                       s.progressive_carries,
                       s.carries_into_final_third, s.carries_into_penalty_area,
                       s.aerials_won, s.aerials_lost,
                       s.recoveries, s.fouls, s.fouled,
                       s.games_played,
                       s.gk_saves, s.gk_shots_on_target_against,
                       s.gk_goals_against, s.gk_clean_sheets,
                       s.gk_psxg, s.gk_crosses_faced, s.gk_crosses_stopped,
                       s.gk_def_actions_outside_pen
                FROM player_season_stats s
                JOIN player_master p ON p.player_id = s.player_id
                WHERE p.position_group = %s AND s.minutes_played >= %s
            """, (group, min_minutes))
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]

        if not rows:
            continue

        df = pd.DataFrame(rows, columns=colnames)

        # Convert numeric columns to float for math operations
        for c in df.columns:
            if c not in ("season", "competition_id"):
                df[c] = pd.to_numeric(df[c], errors="coerce")

        derived_cols = []

        for feature_name, expr in group_features.items():
            derived_cols.append(feature_name)
            if expr.startswith("per90:"):
                col = expr.split(":")[1]
                df[feature_name] = np.where(
                    df["minutes_played"] > 0,
                    (df[col] / df["minutes_played"]) * 90,
                    np.nan,
                )
            elif expr.startswith("ratio:"):
                parts = expr.split(":")
                num_expr = parts[1]
                den_expr = parts[2]

                if "+" in den_expr:
                    den_cols = den_expr.split("+")
                    den = df[den_cols[0]] + df[den_cols[1]]
                else:
                    den = df[den_expr]

                df[feature_name] = np.where(den > 0, df[num_expr] / den, np.nan)
            elif expr.startswith("per90_diff:"):
                parts = expr.split(":")
                col_a = parts[1]
                col_b = parts[2]
                df[feature_name] = np.where(
                    df["minutes_played"] > 0,
                    ((df[col_a] - df[col_b]) / df["minutes_played"]) * 90,
                    np.nan,
                )
            elif expr.startswith("raw:"):
                col = expr.split(":")[1]
                df[feature_name] = df[col]

        # Z-score and percentile within (season, competition_id)
        out_rows = []
        for (season, comp), sub_df in df.groupby(["season", "competition_id"]):
            sub_df = sub_df.copy()
            for col in derived_cols:
                # Z-score
                mean = sub_df[col].mean()
                std = sub_df[col].std()
                if pd.isna(std) or std == 0:
                    sub_df[f"{col}_z"] = 0.0
                else:
                    sub_df[f"{col}_z"] = (sub_df[col] - mean) / std

                # Percentile
                valid_mask = sub_df[col].notna()
                sub_df[f"{col}_pct"] = np.nan
                if valid_mask.sum() > 1:
                    ranks = rankdata(sub_df.loc[valid_mask, col], method="average")
                    pct = (ranks - 1) / (len(ranks) - 1) * 100
                    sub_df.loc[valid_mask, f"{col}_pct"] = pct
                elif valid_mask.sum() == 1:
                    sub_df.loc[valid_mask, f"{col}_pct"] = 50.0

            out_rows.append(sub_df)

        if not out_rows:
            continue

        final_df = pd.concat(out_rows)

        # Build upsert columns
        table_name = f"feature_{group.lower()}"
        upsert_cols = ["player_id", "season", "competition_id"]
        for col in derived_cols:
            upsert_cols.extend([f"{col}_z", f"{col}_pct"])

        # Convert to Python-native tuples for psycopg2
        data_tuples = []
        for _, row in final_df.iterrows():
            data_tuples.append(tuple(_safe_python(row[c]) for c in upsert_cols))

        if not data_tuples:
            continue

        update_cols = [c for c in upsert_cols if c not in ("player_id", "season", "competition_id")]
        insert_query = f"""
            INSERT INTO {table_name} ({", ".join(upsert_cols)})
            VALUES ({", ".join(["%s"] * len(upsert_cols))})
            ON CONFLICT (player_id, season, competition_id) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)}
        """

        with conn.cursor() as cur:
            pgx.execute_batch(cur, insert_query, data_tuples)
            total_written += len(data_tuples)

    conn.commit()
    return total_written


if __name__ == "__main__":
    DB_DSN = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(DB_DSN)
    written = run_features(conn)
    print(f"[OK] {written} feature rows written")
    conn.close()
