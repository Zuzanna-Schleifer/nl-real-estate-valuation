-- TYDZIEN 3 - dbt model: staging/stg_bag.sql
-- Czysci i standaryzuje surowe dane BAG
-- Materialized: view (nie zajmuje storage, zawsze aktualne)

WITH source AS (
    SELECT * FROM {{ source('raw', 'bag_adressen') }}
),

cleaned AS (
    SELECT
        bag_id,
        straatnaam,
        huisnummer,

        -- Normalizacja kodu pocztowego: usuwa spacje, wielkie litery
        UPPER(REPLACE(postcode, ' ', ''))               AS postcode,
        LEFT(UPPER(REPLACE(postcode, ' ', '')), 4)      AS postcode_4digit,

        stad,
        gemeente,

        -- Filtracja nierealistycznych wartosci metrazowych
        CASE
            WHEN oppervlakte BETWEEN {{ var('min_oppervlakte') }} AND {{ var('max_oppervlakte') }}
            THEN oppervlakte
            ELSE NULL
        END                                             AS oppervlakte_m2,

        -- Parsowanie uzytkowan z VARIANT (JSON array)
        CASE
            WHEN ARRAY_CONTAINS('woonfunctie'::VARIANT, gebruiksdoelen) THEN 'wonen'
            WHEN ARRAY_CONTAINS('kantoorfunctie'::VARIANT, gebruiksdoelen) THEN 'kantoor'
            WHEN ARRAY_CONTAINS('winkelfunctie'::VARIANT, gebruiksdoelen) THEN 'winkel'
            WHEN ARRAY_CONTAINS('industriefunctie'::VARIANT, gebruiksdoelen) THEN 'industrie'
            ELSE 'overig'
        END                                             AS gebruiksdoel,

        -- Rok budowy (filtracja: 1600-2024)
        CASE
            WHEN bouwjaar BETWEEN 1600 AND 2024 THEN bouwjaar
            ELSE NULL
        END                                             AS bouwjaar,

        -- Wiek budynku (feature dla modelu)
        CASE
            WHEN bouwjaar BETWEEN 1600 AND 2024
            THEN YEAR(CURRENT_DATE()) - bouwjaar
            ELSE NULL
        END                                             AS leeftijd_jaar,

        status,
        loaded_at

    FROM source
    WHERE postcode IS NOT NULL
      AND bag_id IS NOT NULL
)

SELECT * FROM cleaned
