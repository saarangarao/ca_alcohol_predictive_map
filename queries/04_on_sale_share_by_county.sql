-- 04 | On-sale share by county
-- Question:  in which counties is the retail mix tilted toward bars and restaurants (on-sale)
--            rather than stores (off-sale)?
-- Source:    zip_features.
-- Technique: two CTEs; a window function over the aggregated rows (sum(...) OVER ()) gives the
--            statewide share so each county can be compared with it.
-- Reading:   on_share = on-sale outlets / (on-sale + off-sale outlets).
WITH county AS (
    SELECT county,
           sum(outlets_off)     AS outlets_off,
           sum(outlets_on_core) AS outlets_on_core
    FROM zip_features
    GROUP BY county
),
shares AS (
    SELECT county, outlets_off, outlets_on_core,
           outlets_on_core * 1.0 / (outlets_on_core + outlets_off) AS on_share,
           sum(outlets_on_core) OVER () * 1.0
             / sum(outlets_on_core + outlets_off) OVER ()          AS state_on_share
    FROM county
)
SELECT county, outlets_off, outlets_on_core,
       round(on_share, 3)                   AS on_share,
       round(state_on_share, 3)             AS state_on_share,
       round(on_share - state_on_share, 3)  AS diff_vs_state
FROM shares
ORDER BY on_share DESC;
