-- TYDZIEN 3 - dbt model: mart/mart_features.sql
-- Finalna tabela feature store dla modelu XGBoost
-- Materialized: table w schemacie MART
-- Spatial features (dist_*) sa uzupelniane przez PySpark job (tydzien 4)

WITH enriched AS (
    SELECT * FROM {{ ref('int_properties_enriched') }}
),

-- Imputacja brakujacych wartosci (globalne mediany)
global_stats AS (
    SELECT
        MEDIAN(energielabel_score)          AS median_energielabel_score,
        MEDIAN(oppervlakte_m2)              AS median_oppervlakte,
        MEDIAN(wijk_gemiddeld_inkomen)      AS median_wijk_inkomen,
        MEDIAN(wijk_gemiddelde_waarde)      AS median_wijk_waarde,
        MEDIAN(wijk_pct_eigenaar)           AS median_wijk_pct_eigenaar,
        MEDIAN(wijk_bevolkingsdichtheid)    AS median_bevolkingsdichtheid
    FROM enriched
    WHERE woz_waarde IS NOT NULL
),

mart AS (
    SELECT
        e.bag_id,
        e.straatnaam,
        e.huisnummer,
        e.postcode,
        e.postcode_4digit,
        e.stad,
        e.gemeente,

        -- ===== TARGET VARIABLE =====
        e.woz_waarde                                            AS target_price,
        e.woz_waarde_log                                        AS target_price_log,
        e.woz_peildatum,

        -- ===== CECHY BUDYNKU =====
        COALESCE(e.oppervlakte_m2, g.median_oppervlakte)       AS oppervlakte_m2,
        LN(COALESCE(e.oppervlakte_m2, g.median_oppervlakte))   AS oppervlakte_log,
        e.bouwjaar,
        e.leeftijd_jaar,
        e.gebruiksdoel,

        -- One-hot encoding uzytkownia
        CASE WHEN e.gebruiksdoel = 'wonen' THEN 1 ELSE 0 END   AS is_wonen,
        CASE WHEN e.gebruiksdoel = 'kantoor' THEN 1 ELSE 0 END AS is_kantoor,
        CASE WHEN e.gebruiksdoel = 'winkel' THEN 1 ELSE 0 END  AS is_winkel,

        -- ===== CECHY ENERGETYCZNE =====
        e.energielabel,
        COALESCE(e.energielabel_score, g.median_energielabel_score) AS energielabel_score,
        e.energieindex,
        e.gebouwtype,

        -- ===== CECHY WIJK (DZIELNICA) =====
        COALESCE(e.wijk_gemiddeld_inkomen, g.median_wijk_inkomen)       AS wijk_gemiddeld_inkomen,
        COALESCE(e.wijk_gemiddelde_waarde, g.median_wijk_waarde)        AS wijk_gemiddelde_waarde,
        COALESCE(e.wijk_pct_eigenaar, g.median_wijk_pct_eigenaar)       AS wijk_pct_eigenaar,
        COALESCE(e.wijk_bevolkingsdichtheid, g.median_bevolkingsdichtheid) AS wijk_bevolkingsdichtheid,

        -- Postcode popularity (ile nieruchomosci w danym postcode)
        e.n_properties_in_postcode,
        e.median_woz_in_postcode,

        -- ===== CECHY SPATIAL (wypelnia PySpark w tygodniu 4) =====
        CAST(NULL AS FLOAT)             AS dist_centrum_m,
        CAST(NULL AS FLOAT)             AS dist_station_m,
        CAST(NULL AS FLOAT)             AS dist_water_m,
        CAST(NULL AS INTEGER)           AS n_shops_500m,
        CAST(NULL AS INTEGER)           AS n_schools_1km,

        -- ===== METADATA =====
        e.is_woz_missing,
        e.is_ep_missing,
        e.is_cbs_missing,
        CURRENT_TIMESTAMP()             AS feature_created_at

    FROM enriched e
    CROSS JOIN global_stats g

    WHERE e.woz_waarde IS NOT NULL  -- tylko rekordy z cena docelowa
      AND e.oppervlakte_m2 IS NOT NULL
)

SELECT * FROM mart
