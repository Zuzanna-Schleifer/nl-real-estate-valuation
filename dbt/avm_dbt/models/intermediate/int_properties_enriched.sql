-- TYDZIEN 3 - dbt model: intermediate/int_properties_enriched.sql
-- Laczy BAG + WOZ + EP-online + CBS w jeden rekord per nieruchomosc
-- Materialized: table (dla wydajnosci joinow)

WITH bag AS (
    SELECT * FROM {{ ref('stg_bag') }}
),

woz AS (
    SELECT * FROM {{ ref('stg_woz') }}
),

ep AS (
    SELECT * FROM {{ ref('stg_ep_online') }}
),

cbs AS (
    SELECT * FROM {{ ref('stg_cbs') }}
),

-- Mediana WOZ per postcode (dla imputacji brakujacych wartosci)
postcode_median_woz AS (
    SELECT
        postcode_4digit,
        MEDIAN(woz_waarde)      AS median_woz_in_postcode,
        COUNT(*)                AS n_properties_in_postcode
    FROM woz
    GROUP BY postcode_4digit
),

joined AS (
    SELECT
        b.bag_id,
        b.straatnaam,
        b.huisnummer,
        b.postcode,
        b.postcode_4digit,
        b.stad,
        b.gemeente,
        b.gebruiksdoel,
        b.oppervlakte_m2,
        b.bouwjaar,
        b.leeftijd_jaar,
        b.status,

        -- WOZ (target variable)
        w.woz_waarde,
        w.woz_waarde_log,
        w.peildatum             AS woz_peildatum,
        w.gebruikscategorie,

        -- Postcode stats
        pm.median_woz_in_postcode,
        pm.n_properties_in_postcode,

        -- EP-online
        e.energielabel,
        e.energielabel_score,
        e.energieindex,
        e.gebouwtype,

        -- CBS wijk (join na 4-cyfrowym postcode)
        c.wijk_code,
        c.wijk_naam,
        c.gemiddelde_woningwaarde   AS wijk_gemiddelde_waarde,
        c.gemiddeld_inkomen         AS wijk_gemiddeld_inkomen,
        c.pct_eigenaar              AS wijk_pct_eigenaar,
        c.bevolkingsdichtheid       AS wijk_bevolkingsdichtheid,

        -- Flagi jakosci danych
        CASE WHEN w.woz_waarde IS NULL THEN 1 ELSE 0 END       AS is_woz_missing,
        CASE WHEN e.energielabel IS NULL THEN 1 ELSE 0 END     AS is_ep_missing,
        CASE WHEN c.wijk_code IS NULL THEN 1 ELSE 0 END        AS is_cbs_missing

    FROM bag b

    -- LEFT JOIN: zachowaj wszystkie adresy BAG nawet bez WOZ
    LEFT JOIN woz w
        ON b.postcode = w.postcode
        AND b.huisnummer = w.huisnummer

    LEFT JOIN postcode_median_woz pm
        ON b.postcode_4digit = pm.postcode_4digit

    LEFT JOIN ep e
        ON b.postcode = e.postcode
        AND b.huisnummer = e.huisnummer

    -- CBS join na 4-cyfrowym kodzie pocztowym
    LEFT JOIN cbs c
        ON b.postcode_4digit = LEFT(c.wijk_code, 4)

    WHERE b.oppervlakte_m2 IS NOT NULL
)

SELECT * FROM joined
