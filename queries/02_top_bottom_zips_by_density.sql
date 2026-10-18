-- 02 | Highest and lowest 20 ZIPs by off-sale density
-- Question:  which ZIPs have the most and the fewest off-sale outlets per 1,000 residents?
-- Source:    zip_features (population floor already applied, so tiny ZIPs cannot dominate).
-- Technique: CTE + two ROW_NUMBER() window functions, one per direction.
-- Reading:   many ZIPs tie at zero outlets, so the "lowest" list breaks ties by population:
--            it shows the LARGEST ZIPs with no off-sale outlets, which is the interesting case.
--            visitor_heavy marks ZIPs whose demand likely comes from non-residents.
WITH ranked AS (
    SELECT zip5, city, county, population, outlets_off, off_per_1k, visitor_heavy,
           row_number() OVER (ORDER BY off_per_1k DESC, population DESC) AS rank_high,
           row_number() OVER (ORDER BY off_per_1k ASC,  population DESC) AS rank_low
    FROM zip_features
)
SELECT 'highest' AS side, rank_high AS rank, zip5, city, county,
       population::INT AS population, outlets_off, round(off_per_1k, 2) AS off_per_1k, visitor_heavy
FROM ranked
WHERE rank_high <= 20
UNION ALL
SELECT 'lowest', rank_low, zip5, city, county,
       population::INT, outlets_off, round(off_per_1k, 2), visitor_heavy
FROM ranked
WHERE rank_low <= 20
ORDER BY side DESC, rank;
