# Footy DataNgin ⚽📊

> A modern football analytics & player similarity engine covering Europe's top 5 leagues across the 2022/23 to 2024/25 seasons.

Footy DataNgin ingests multi-source performance data, standardizes position-specific metrics, and runs cosine-similarity algorithms to match players by playstyle and output — all visualized through an interactive Streamlit dashboard.

---

## 💡 Why This Project?

Public football scouting tools frequently suffer from two issues:
1. **Comparing apples to oranges**: Comparing a box-to-box midfielder with an inverted winger using identical stat weights gives misleading results.
2. **Missing context & dead metrics**: Raw stats often lack per-90 normalization, position mapping, or multi-source validation (e.g., blending Opta passing & defensive actions with Understat expected metrics).

Footy DataNgin was built to solve this by grouping players into position cohorts (GK, CB, FB, CM, W, ST), computing per-90 metrics, weighting metrics by role relevance, and calculating mathematical similarity scores with cosine similarity.

---

## 🚀 Key Features

- **🔍 Player Search & Similarity Engine**:
  - Search any player across the top 5 European leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).
  - Find the top 10 most stylistically similar players in the same position group.
  - See clear match percentages (e.g., De Bruyne $\leftrightarrow$ Ødegaard at 93.0% similarity, Bellingham $\leftrightarrow$ Musiala at 91.0%).

- **⚔️ 1v1 Player Comparison**:
  - Head-to-head radar charts and percentile bars comparing two players across key per-90 metrics.
  - Direct metric breakdown for passing accuracy, progressive play, defensive contributions, and finishing.

- **📈 Deep Player Profiles**:
  - Multi-season progression breakdown.
  - Metric breakdown against cohort percentiles.

- **🤖 Automated Pipelines & Self-Healing Cloud Database**:
  - Automated data ingestion, normalization, and similarity matrix calculations via GitHub Actions.
  - Active heartbeat workflow keeping the free-tier Supabase Postgres instance alive and responsive.

---

## 🏗️ Architecture & Data Pipeline

```
  Multi-Source Scrapers
  (FBref + FotMob + Understat)
             │
             ▼
   [ Raw Ingestion Layer ]
             │
             ▼
  [ clean_transform.py ] ──► Standardize IDs, names, seasons & minutes
             │
             ▼
     [ features.py ]     ──► Position-specific feature engineering & per-90 scaling
             │
             ▼
  [ model_similarity.py] ──► Cohort StandardScaler + Cosine Similarity Matrix
             │
             ▼
   [ Supabase Postgres ] ──► Relational storage & indexed query layer
             │
             ▼
   [ Streamlit Cloud ]   ──► Interactive scouting UI (Search, Compare, Detail, Browse)
```

### Position Cohorts & Feature Sets

| Position Group | Roles Included | Core Metric Focus |
| :--- | :--- | :--- |
| **GK** | Goalkeepers | Pass completion %, xG Buildup/90, xG Chain/90 |
| **CB** | Center Backs | Tackles/90, Tackles Won %, Interceptions/90, Clearances/90, Blocks/90, Recoveries/90, Pass %, xG Buildup |
| **FB** | Fullbacks / Wingbacks | Interceptions/90, Tackles/90, Clearances/90, Take-ons Won/90, Pass %, Key Passes/90, Assists/90 |
| **CM** | Central & Defensive Midfielders | Pass %, Tackles/90, Interceptions/90, Clearances/90, Take-ons Won/90, Key Passes/90, xG Buildup/90 |
| **W** | Wingers / Wide Attackers | Goals/90, Assists/90, xG/90, xAG/90, Shots/90, Shots on Target %, Key Passes/90, Take-ons Won/90 |
| **ST** | Center Forwards / Strikers | Goals/90, Non-penalty xG/90, xAG/90, Shots/90, Shots on Target %, Conversion Rate, Key Passes/90 |

---

## 🛠️ Tech Stack

- **Dashboard**: [Streamlit](https://streamlit.io/), Plotly, Pandas
- **Data Pipeline**: Python 3.11+, Scikit-learn, Psycopg2, SoccerData, Playwright
- **Database**: PostgreSQL on [Supabase](https://supabase.com/)
- **Orchestration**: GitHub Actions (scheduled runs & database keepalive)

---

## ⚡ Quickstart & Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/Yasin-Jlassi/footy-datangin.git
cd footy-datangin
```

### 2. Set up virtual environment

```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL="postgresql://<user>:<password>@<host>:<port>/postgres"
```

### 4. Launch the Streamlit dashboard

```bash
streamlit run dashboard/app.py
```

Open `http://localhost:8501` in your browser.

---

## 🔄 Running the Pipeline

If you want to re-run transformations and compute similarities locally:

```bash
# 1. Transform raw stats and backfill enriched data
python pipeline/clean_transform.py

# 2. Compute position-specific per-90 metrics
python pipeline/features.py

# 3. Fit scaler and compute similarity matrices
python pipeline/model_similarity.py

# 4. Validate output integrity
python pipeline/validate.py
```

---

## 🧪 Testing

Run unit and integration tests with pytest:

```bash
pytest tests/
```

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/Yasin-Jlassi/footy-datangin/issues) or submit a pull request.

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
