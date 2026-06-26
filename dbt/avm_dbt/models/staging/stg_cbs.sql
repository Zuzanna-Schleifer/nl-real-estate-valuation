-- TYDZIEN 3 - dbt model: staging/stg_cbs.sql
-- Czysci dane demograficzne CBS per wijk

WITH source AS (
    SELECT * FROM {{ source('raw', 'cbs_wijk_data') }}
),

cleaned AS (
    SELECT
        TRIM(wijk_code)                     AS wijk_code,
        TRIM(wijk_naam)                     AS wijk_naam,
        TRIM(gemeente)                      AS gemeente,

        -- Walidacja wartosci (NULL jesli poza zakresem)
        CASE
            WHEN gemiddelde_woningwaarde BETWEEN 50000 AND 5000000
            THEN gemiddelde_woningwaarde
            ELSE NULL
        END                                 AS gemiddelde_woningwaarde,

        CASE
            WHEN gemiddeld_inkomen BETWEEN 10000 AND 200000
            THEN gemiddeld_inkomen
            ELSE NULL
        END                                 AS gemiddeld_inkomen,

        CASE
            WHEN pct_eigenaar BETWEEN 0 AND 100
            THEN pct_eigenaar
            ELSE NULL
        END                                 AS pct_eigenaar,

        CASE
            WHEN bevolkingsdichtheid BETWEEN 0 AND 30000
            THEN bevolkingsdichtheid
            ELSE NULL
        END                                 AS bevolkingsdichtheid,

        NULLIF(inwoners, 0)                 AS inwoners,
        oppervlakte_km2,
        is_synthetic,
        loaded_at

    FROM source
    WHERE wijk_code IS NOT NULL
)

SELECT * FROM cleaned
