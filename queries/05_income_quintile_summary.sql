-- 05 | Outlet density by income quintile
-- Question:  does outlet density change as ZIP median household income rises?
-- Source:    zip_features, ZIPs with a known median income (28 ZIPs have none and are left out).
-- Technique: NTILE(5) window function to cut ZIPs into five equal-sized income groups
--            (quintile 1 = lowest income, 5 = highest), then group and summarize.
-- Note:      "pooled" density = total outlets / total population in the group. The median of the
--            ZIP-level ratios is shown beside it because a few extreme ZIPs can distort pooled values.
--            Ties (for example the 250,000 top-code) are broken by zip5, so the result is repeatable.
WITH ranked AS (
    SELECT *, ntile(5) OVER (ORDER BY median_income, zip5) AS income_quintile
    FROM zip_features
    WHERE median_income IS NOT NULL
)
SELECT income_quintile,
       count(*)                                               AS n_zips,
       min(median_income)::INT                                AS min_income,
       max(median_income)::INT                                AS max_income,
       sum(population)::BIGINT                                AS population,
       sum(outlets_off)                                       AS outlets_off,
       sum(outlets_on_core)                                   AS outlets_on_core,
       round(sum(outlets_off)     * 1000.0 / sum(population), 2) AS off_per_1k_pooled,
       round(sum(outlets_on_core) * 1000.0 / sum(population), 2) AS on_per_1k_pooled,
       round(median(off_per_1k), 2)                           AS off_per_1k_median_zip,
       round(median(on_per_1k), 2)                            AS on_per_1k_median_zip,
       count(*) FILTER (WHERE visitor_heavy)                  AS n_visitor_heavy
FROM ranked
GROUP BY income_quintile
ORDER BY income_quintile;
