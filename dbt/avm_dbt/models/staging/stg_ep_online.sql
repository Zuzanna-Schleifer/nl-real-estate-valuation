-- TYDZIEN 3 - dbt model: staging/stg_ep_online.sql
-- Czysci etykiety energetyczne z EP-online

WITH source AS (
    SELECT * FROM {{ source('raw', 'ep_online_labels') }}
),

cleaned AS (
    SELECT
        UPPER(REPLACE(postcode, ' ', ''))       AS postcode,
        LEFT(UPPER(REPLACE(postcode, ' ', '')), 4) AS postcode_4digit,
        huisnummer,
        UPPER(TRIM(energielabel))               AS energielabel,

        -- Numeryczny score etykiety dla modelu ML
        -- Wyzszy = lepszy (bardziej energooszczedny)
        CASE UPPER(TRIM(energielabel))
            WHEN 'A+++' THEN 10
            WHEN 'A++'  THEN 9
            WHEN 'A+'   THEN 8
            WHEN 'A'    THEN 7
            WHEN 'B'    THEN 6
            WHEN 'C'    THEN 5
            WHEN 'D'    THEN 4
            WHEN 'E'    THEN 3
            WHEN 'F'    THEN 2
            WHEN 'G'    THEN 1
            ELSE NULL
        END                                     AS energielabel_score,

        energieindex,
        registratiedatum,
        gebouwtype,
        is_synthetic,
        loaded_at

    FROM source
    WHERE energielabel IS NOT NULL
      AND postcode IS NOT NULL
)

SELECT * FROM cleaned
