-- TYDZIEN 3 - dbt model: staging/stg_woz.sql
-- Czysci dane WOZ (wartosci podatkowe nieruchomosci)

WITH source AS (
    SELECT * FROM {{ source('raw', 'woz_waarden') }}
),

cleaned AS (
    SELECT
        woz_object_nummer,
        UPPER(REPLACE(postcode, ' ', ''))   AS postcode,
        LEFT(UPPER(REPLACE(postcode, ' ', '')), 4) AS postcode_4digit,
        huisnummer,
        woz_waarde,
        peildatum,

        -- Kategoria uzytkowania
        CASE gebruikscode
            WHEN '1000' THEN 'wonen'
            WHEN '2000' THEN 'bedrijf'
            WHEN '3000' THEN 'overig'
            ELSE COALESCE(gebruikscode, 'onbekend')
        END                                 AS gebruikscategorie,

        -- Log ceny (lepszy rozklad dla modeli ML)
        LN(NULLIF(woz_waarde, 0))           AS woz_waarde_log,

        is_synthetic,
        loaded_at

    FROM source
    WHERE woz_waarde BETWEEN {{ var('min_woz_waarde') }} AND {{ var('max_woz_waarde') }}
      AND postcode IS NOT NULL
)

SELECT * FROM cleaned
