"""
Element 3 — Similarity computation.
PCA + cosine similarity per position group → writes to similarity_matrix.
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
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def run_similarity(conn) -> int:
    config = load_config()
    pca_variance_threshold = config.get("model", {}).get("pca_variance_threshold", 0.90)
    groups = config.get("positions", {}).get("groups", [])
    features_config = config.get("features", {})

    total_written = 0

    for group in groups:
        if group not in features_config:
            continue

        table_name = f"feature_{group.lower()}"
        z_cols = [f"{col}_z" for col in features_config[group].keys()]

        # Use cursor directly to avoid SQLAlchemy warning
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

        # Convert z-score columns to numeric
        for c in z_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.dropna(subset=z_cols)

        if df.empty or len(df) < 2:
            continue

        X = df[z_cols].values.astype(float)
        n_features = X.shape[1]
        n_samples = X.shape[0]
        max_components = min(n_features, n_samples)

        pca = PCA(n_components=max_components)
        pca.fit(X)

        cumsum = np.cumsum(pca.explained_variance_ratio_)
        k = int(np.argmax(cumsum >= pca_variance_threshold) + 1)
        k = min(k, max_components)

        pca = PCA(n_components=k)
        X_reduced = pca.fit_transform(X)

        sim_matrix = cosine_similarity(X_reduced)

        # Verify self-similarity is ~1.0
        diag = np.diag(sim_matrix)
        if not np.allclose(diag, 1.0, atol=1e-3):
            print(f"  WARNING: Self-similarity not ~1.0 for {group}")

        player_ids = df["player_id"].values

        records = []
        for i in range(len(player_ids)):
            for j in range(i + 1, len(player_ids)):
                id_a = int(player_ids[i])
                id_b = int(player_ids[j])
                score = float(sim_matrix[i, j])

                if id_a < id_b:
                    records.append((group, id_a, id_b, score))
                else:
                    records.append((group, id_b, id_a, score))

        if not records:
            continue

        with conn.cursor() as cur:
            cur.execute("DELETE FROM similarity_matrix WHERE position_group = %s", (group,))

            insert_query = """
                INSERT INTO similarity_matrix (position_group, player_id_a, player_id_b, similarity_score)
                VALUES (%s, %s, %s, %s)
            """
            pgx.execute_batch(cur, insert_query, records)
            total_written += len(records)
            print(f"  {group}: {len(df)} players → {len(records)} pairs (PCA k={k})")

    conn.commit()
    return total_written


if __name__ == "__main__":
    DB_DSN = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(DB_DSN)
    written = run_similarity(conn)
    print(f"✓ {written} similarity pairs written")
    conn.close()
