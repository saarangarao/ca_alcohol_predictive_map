-- 03 | County rollups with RANK()
-- Question:  how do California's 58 counties compare on outlet density?
-- Source:    zip_features (ZIPs above the population floor; county = largest-overlap county).
-- Technique: CTE for the rollup, RANK() window functions for the league tables.
-- Note:      county density is TOTAL outlets / TOTAL population (pooled). Averaging the ZIP
--            ratios instead would let a 1,000-person ZIP count as much as a 50,000-person one.
WITH county AS (
    SELECT county,
           count(*)             AS n_zips,
           sum(population)      AS population,
           sum(outlets_off)     AS outlets_off,
           sum(outlets_on_core) AS outlets_on_core
    FROM zip_features
    GROUP BY county
)
SELECT county, n_zips, population::BIGINT AS population, outlets_off, outlets_on_core,
       round(outlets_off     * 1000.0 / population, 2) AS off_per_1k,
       round(outlets_on_core * 1000.0 / population, 2) AS on_per_1k,
       rank() OVER (ORDER BY outlets_off     * 1.0 / population DESC) AS off_rank,
       rank() OVER (ORDER BY outlets_on_core * 1.0 / population DESC) AS on_rank
FROM county
ORDER BY off_rank;
