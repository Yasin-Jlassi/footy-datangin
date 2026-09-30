"""
Element 3 — Validation.
Silhouette score, self-match coverage check, and spot-check runner.
"""
import os
import psycopg2

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def run_validation(conn):
    config = load_config()
    pca_variance_threshold = config.get("model", {}).get("pca_variance_threshold", 0.90)
    groups = config.get("positions", {}).get("groups", [])
    features_config = config.get("features", {})
    min_minutes = config.get("scraper", {}).get("min_minutes", 450)

    silhouette_scores = []

    for group in groups:
        if group not in features_config:
            continue

        table_name = f"feature_{group.lower()}"
        z_cols = [f"{col}_z" for col in features_config[group].keys()]

        with conn.cursor() as cur:
            cur.execute(f"""
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY player_id ORDER BY season DESC) as rn
                    FROM {table_name}
                )
                SELECT * FROM ranked WHERE rn = 1
            """)
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]

        if not rows:
            continue

        df = pd.DataFrame(rows, columns=colnames)
        for c in z_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.dropna(subset=z_cols)

        if len(df) < 3:
            continue

        X = df[z_cols].values.astype(float)

        max_components = min(X.shape[0], X.shape[1])
        pca = PCA(n_components=max_components)
        pca.fit(X)
        cumsum = np.cumsum(pca.explained_variance_ratio_)
        k = int(np.argmax(cumsum >= pca_variance_threshold) + 1)
        k = min(k, max_components)

        pca = PCA(n_components=k)
        X_reduced = pca.fit_transform(X)

        n_clusters = min(5, len(X_reduced) - 1)
        if n_clusters < 2:
            continue

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_reduced)

        score = silhouette_score(X_reduced, labels)
        silhouette_scores.append(score)
        print(f"  {group}: silhouette={score:.3f} (n={len(df)}, PCA k={k}, clusters={n_clusters})")

    avg_silhouette = float(np.mean(silhouette_scores)) if silhouette_scores else None

    # Self-match coverage: every eligible player should appear in similarity_matrix
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH eligible_players AS (
                SELECT DISTINCT p.player_id
                FROM player_master p
                JOIN player_season_stats s ON p.player_id = s.player_id
                WHERE s.minutes_played >= {min_minutes}
            ),
            matrix_players AS (
                SELECT player_id_a AS player_id FROM similarity_matrix
                UNION
                SELECT player_id_b AS player_id FROM similarity_matrix
            )
            SELECT COUNT(*)
            FROM eligible_players e
            LEFT JOIN matrix_players m ON e.player_id = m.player_id
            WHERE m.player_id IS NULL
        """)
        missing_count = cur.fetchone()[0]

    self_match_pass = (missing_count == 0)

    # Spot checks
    spot_checks = [
        ("Pedri", "Gavi"),
        ("Mohamed Salah", "Sadio Mané"),
        ("Erling Haaland", "Kylian Mbappé"),
        ("Virgil van Dijk", "Rúben Dias"),
        ("Kevin De Bruyne", "Martin Ødegaard"),
        ("Bukayo Saka", "Phil Foden"),
        ("Trent Alexander-Arnold", "Andrew Robertson"),
        ("Declan Rice", "Rodrigo Hernández"),
    ]

    print(f"\n{'='*50}")
    print(f"Validation Results:")
    print(f"  Average Silhouette Score: {avg_silhouette}")
    print(f"  Self Match Pass: {self_match_pass} (Missing: {missing_count})")
    print(f"\nSpot Checks:")

    with conn.cursor() as cur:
        for p1, p2 in spot_checks:
            cur.execute("""
                SELECT similarity_score
                FROM similarity_matrix sm
                JOIN player_master pm1 ON sm.player_id_a = pm1.player_id
                JOIN player_master pm2 ON sm.player_id_b = pm2.player_id
                WHERE (pm1.full_name ILIKE %s AND pm2.full_name ILIKE %s)
                   OR (pm1.full_name ILIKE %s AND pm2.full_name ILIKE %s)
            """, (f"%{p1}%", f"%{p2}%", f"%{p2}%", f"%{p1}%"))
            row = cur.fetchone()
            score = f"{row[0]:.3f}" if row else "Not Found"
            print(f"  {p1} ↔ {p2}: {score}")

    return avg_silhouette, self_match_pass


if __name__ == "__main__":
    DB_DSN = os.environ.get("DATABASE_URL")
    if DB_DSN:
        conn = psycopg2.connect(DB_DSN)
        run_validation(conn)
        conn.close()
