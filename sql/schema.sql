-- =====================================================================
-- Footy DataNgin — Full Schema  (Supabase / Neon Postgres, free tier)
-- Single clean layer: ingestion upserts directly into these tables.
-- =====================================================================

-- ---------------------------------------------------------------------
-- player_master: one canonical row per real player
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_master (
    player_id        BIGSERIAL PRIMARY KEY,
    fbref_id         TEXT UNIQUE NOT NULL,
    full_name        TEXT NOT NULL,
    birth_date       DATE NOT NULL,
    nationality      TEXT NOT NULL,
    primary_position TEXT,
    position_group   TEXT NOT NULL
        CHECK (position_group IN ('GK','CB','FB','CM','W','ST')),
    source_id_map    JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_player_master_dedup
    ON player_master (full_name, birth_date, nationality);

-- ---------------------------------------------------------------------
-- player_season_stats: grain = player + season + competition
-- Expanded to capture every stat needed for feature engineering.
-- GK-specific columns are NULL for outfield players and vice-versa.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_season_stats (
    id               BIGSERIAL PRIMARY KEY,
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,                -- e.g. '2025-2026'
    competition_id   TEXT NOT NULL,
    games_played     INT DEFAULT 0,
    games_started    INT DEFAULT 0,
    minutes_played   INT NOT NULL DEFAULT 0,

    -- ── outfield counting stats ──────────────────────────────────────
    goals            INT DEFAULT 0,
    assists          INT DEFAULT 0,
    xg               NUMERIC DEFAULT 0,
    npxg             NUMERIC DEFAULT 0,
    xag              NUMERIC DEFAULT 0,

    shots            INT DEFAULT 0,
    shots_on_target  INT DEFAULT 0,

    passes_completed INT DEFAULT 0,
    passes_attempted INT DEFAULT 0,
    progressive_passes INT DEFAULT 0,
    key_passes       INT DEFAULT 0,
    passes_into_final_third INT DEFAULT 0,
    passes_into_penalty_area INT DEFAULT 0,
    crosses_into_penalty_area INT DEFAULT 0,
    passes_long_completed INT DEFAULT 0,
    passes_long_attempted INT DEFAULT 0,

    tackles          INT DEFAULT 0,
    tackles_won      INT DEFAULT 0,
    interceptions    INT DEFAULT 0,
    blocks           INT DEFAULT 0,
    clearances       INT DEFAULT 0,

    touches          INT DEFAULT 0,
    touches_att_pen_area INT DEFAULT 0,
    take_ons_won     INT DEFAULT 0,
    take_ons_attempted INT DEFAULT 0,
    progressive_carries INT DEFAULT 0,
    carries_into_final_third INT DEFAULT 0,
    carries_into_penalty_area INT DEFAULT 0,

    aerials_won      INT DEFAULT 0,
    aerials_lost     INT DEFAULT 0,
    recoveries       INT DEFAULT 0,
    fouls            INT DEFAULT 0,
    fouled           INT DEFAULT 0,

    -- ── GK-specific stats (NULL for outfield players) ────────────────
    gk_saves         INT,
    gk_shots_on_target_against INT,
    gk_goals_against INT,
    gk_clean_sheets  INT,
    gk_psxg          NUMERIC,
    gk_crosses_faced INT,
    gk_crosses_stopped INT,
    gk_def_actions_outside_pen INT,

    -- ── basic per-90 derivations (for dashboard display) ─────────────
    goals_per90      NUMERIC,
    assists_per90    NUMERIC,
    xg_per90         NUMERIC,
    npxg_per90       NUMERIC,
    xag_per90        NUMERIC,
    shots_per90      NUMERIC,
    tackles_per90    NUMERIC,

    updated_at       TIMESTAMPTZ DEFAULT now(),

    UNIQUE (player_id, season, competition_id)
);

CREATE INDEX IF NOT EXISTS idx_pss_player     ON player_season_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_pss_season_comp ON player_season_stats(season, competition_id);

-- =====================================================================
-- Feature tables: one per position group.
-- Each stores z-scored (*_z) and percentile-ranked (*_pct) features
-- computed by pipeline/features.py.
-- =====================================================================

-- ── GK  (8 features) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_gk (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    save_pct_z                      NUMERIC,
    save_pct_pct                    NUMERIC,
    ga_per90_z                      NUMERIC,
    ga_per90_pct                    NUMERIC,
    psxg_diff_per90_z               NUMERIC,
    psxg_diff_per90_pct             NUMERIC,
    crosses_stopped_pct_z           NUMERIC,
    crosses_stopped_pct_pct         NUMERIC,
    def_actions_outside_pen_per90_z NUMERIC,
    def_actions_outside_pen_per90_pct NUMERIC,
    pass_pct_z                      NUMERIC,
    pass_pct_pct                    NUMERIC,
    long_pass_cmp_pct_z             NUMERIC,
    long_pass_cmp_pct_pct           NUMERIC,
    clean_sheet_pct_z               NUMERIC,
    clean_sheet_pct_pct             NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- ── CB  (10 features) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_cb (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    tackles_per90_z              NUMERIC,
    tackles_per90_pct            NUMERIC,
    tackles_won_pct_z            NUMERIC,
    tackles_won_pct_pct          NUMERIC,
    interceptions_per90_z        NUMERIC,
    interceptions_per90_pct      NUMERIC,
    clearances_per90_z           NUMERIC,
    clearances_per90_pct         NUMERIC,
    blocks_per90_z               NUMERIC,
    blocks_per90_pct             NUMERIC,
    aerials_won_pct_z            NUMERIC,
    aerials_won_pct_pct          NUMERIC,
    aerials_won_per90_z          NUMERIC,
    aerials_won_per90_pct        NUMERIC,
    pass_pct_z                   NUMERIC,
    pass_pct_pct                 NUMERIC,
    progressive_passes_per90_z   NUMERIC,
    progressive_passes_per90_pct NUMERIC,
    progressive_carries_per90_z  NUMERIC,
    progressive_carries_per90_pct NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- ── FB  (10 features) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_fb (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    tackles_per90_z                    NUMERIC,
    tackles_per90_pct                  NUMERIC,
    interceptions_per90_z              NUMERIC,
    interceptions_per90_pct            NUMERIC,
    progressive_carries_per90_z        NUMERIC,
    progressive_carries_per90_pct      NUMERIC,
    carries_into_final_third_per90_z   NUMERIC,
    carries_into_final_third_per90_pct NUMERIC,
    crosses_into_pen_area_per90_z      NUMERIC,
    crosses_into_pen_area_per90_pct    NUMERIC,
    key_passes_per90_z                 NUMERIC,
    key_passes_per90_pct               NUMERIC,
    assists_per90_z                    NUMERIC,
    assists_per90_pct                  NUMERIC,
    pass_pct_z                         NUMERIC,
    pass_pct_pct                       NUMERIC,
    take_ons_won_per90_z               NUMERIC,
    take_ons_won_per90_pct             NUMERIC,
    take_ons_won_pct_z                 NUMERIC,
    take_ons_won_pct_pct               NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- ── CM  (10 features) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_cm (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    pass_pct_z                         NUMERIC,
    pass_pct_pct                       NUMERIC,
    progressive_passes_per90_z         NUMERIC,
    progressive_passes_per90_pct       NUMERIC,
    key_passes_per90_z                 NUMERIC,
    key_passes_per90_pct               NUMERIC,
    passes_into_final_third_per90_z    NUMERIC,
    passes_into_final_third_per90_pct  NUMERIC,
    xag_per90_z                        NUMERIC,
    xag_per90_pct                      NUMERIC,
    tackles_per90_z                    NUMERIC,
    tackles_per90_pct                  NUMERIC,
    interceptions_per90_z              NUMERIC,
    interceptions_per90_pct            NUMERIC,
    progressive_carries_per90_z        NUMERIC,
    progressive_carries_per90_pct      NUMERIC,
    recoveries_per90_z                 NUMERIC,
    recoveries_per90_pct               NUMERIC,
    goals_per90_z                      NUMERIC,
    goals_per90_pct                    NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- ── W   (10 features) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_w (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    goals_per90_z                   NUMERIC,
    goals_per90_pct                 NUMERIC,
    npxg_per90_z                    NUMERIC,
    npxg_per90_pct                  NUMERIC,
    shots_per90_z                   NUMERIC,
    shots_per90_pct                 NUMERIC,
    shots_on_target_pct_z           NUMERIC,
    shots_on_target_pct_pct         NUMERIC,
    assists_per90_z                 NUMERIC,
    assists_per90_pct               NUMERIC,
    xag_per90_z                     NUMERIC,
    xag_per90_pct                   NUMERIC,
    key_passes_per90_z              NUMERIC,
    key_passes_per90_pct            NUMERIC,
    take_ons_won_per90_z            NUMERIC,
    take_ons_won_per90_pct          NUMERIC,
    take_ons_won_pct_z              NUMERIC,
    take_ons_won_pct_pct            NUMERIC,
    progressive_carries_per90_z     NUMERIC,
    progressive_carries_per90_pct   NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- ── ST  (10 features) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_st (
    player_id        BIGINT NOT NULL REFERENCES player_master(player_id),
    season           TEXT NOT NULL,
    competition_id   TEXT NOT NULL,

    goals_per90_z                    NUMERIC,
    goals_per90_pct                  NUMERIC,
    npxg_per90_z                     NUMERIC,
    npxg_per90_pct                   NUMERIC,
    shots_per90_z                    NUMERIC,
    shots_per90_pct                  NUMERIC,
    shots_on_target_pct_z            NUMERIC,
    shots_on_target_pct_pct          NUMERIC,
    goals_per_shot_z                 NUMERIC,
    goals_per_shot_pct               NUMERIC,
    assists_per90_z                  NUMERIC,
    assists_per90_pct                NUMERIC,
    xag_per90_z                      NUMERIC,
    xag_per90_pct                    NUMERIC,
    aerials_won_per90_z              NUMERIC,
    aerials_won_per90_pct            NUMERIC,
    aerials_won_pct_z                NUMERIC,
    aerials_won_pct_pct              NUMERIC,
    touches_att_pen_area_per90_z     NUMERIC,
    touches_att_pen_area_per90_pct   NUMERIC,

    PRIMARY KEY (player_id, season, competition_id)
);

-- =====================================================================
-- similarity_matrix: full pairwise similarity, rewritten each refresh
-- =====================================================================
CREATE TABLE IF NOT EXISTS similarity_matrix (
    position_group    TEXT NOT NULL
        CHECK (position_group IN ('GK','CB','FB','CM','W','ST')),
    player_id_a       BIGINT NOT NULL REFERENCES player_master(player_id),
    player_id_b       BIGINT NOT NULL REFERENCES player_master(player_id),
    similarity_score  NUMERIC NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (position_group, player_id_a, player_id_b),
    CHECK (player_id_a < player_id_b)
);

CREATE INDEX IF NOT EXISTS idx_sm_player_a ON similarity_matrix(player_id_a);
CREATE INDEX IF NOT EXISTS idx_sm_player_b ON similarity_matrix(player_id_b);

-- =====================================================================
-- refresh_log: one row per refresh cycle
-- =====================================================================
CREATE TABLE IF NOT EXISTS refresh_log (
    run_id            BIGSERIAL PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    rows_scraped      INT,
    rows_upserted     INT,
    features_built    INT,               -- rows written to feature tables
    similarities_computed INT,           -- rows written to similarity_matrix
    silhouette_score  NUMERIC,
    self_match_pass   BOOLEAN
);
