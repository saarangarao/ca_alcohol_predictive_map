-- 07 | Sanity checks
-- Every row must show passed = true. The runner (src/run_queries.py) stops with an error if any
-- check fails, so a broken pipeline cannot quietly produce results.
WITH checks AS (
    SELECT 'zip_features has no duplicate zip5' AS check_name,
           (SELECT count(*) = count(DISTINCT zip5) FROM zip_features) AS passed
    UNION ALL
    SELECT 'clean_outlets has no duplicate (file_number, channel)',
           (SELECT count(*) = count(DISTINCT (file_number, channel)) FROM clean_outlets)
    UNION ALL
    SELECT 'clean_outlets contains only the two retail channels',
           (SELECT count(*) = 0 FROM clean_outlets WHERE channel NOT IN ('OFF_SALE', 'ON_SALE_CORE'))
    UNION ALL
    SELECT 'every zip5 in zip_features is exactly five digits',
           (SELECT count(*) = 0 FROM zip_features WHERE NOT regexp_matches(zip5, '^[0-9]{5}$'))
    UNION ALL
    SELECT 'outlets in zip_features equal clean_outlets for the same ZIPs',
           (SELECT sum(outlets_off + outlets_on_core) FROM zip_features)
           = (SELECT count(*) FROM clean_outlets WHERE zip5 IN (SELECT zip5 FROM zip_features))
    UNION ALL
    SELECT 'every outlet is accounted for: kept + below floor + no Census match = clean_outlets',
           (SELECT sum(value) FROM join_report WHERE ord IN (4, 6, 9))
           = (SELECT count(*) FROM clean_outlets)
    UNION ALL
    SELECT 'no ZIP in zip_features is below the population floor (keep in sync with POP_FLOOR)',
           (SELECT count(*) = 0 FROM zip_features WHERE population < 1000)
    UNION ALL
    SELECT 'densities are never NULL or negative',
           (SELECT count(*) = 0 FROM zip_features
            WHERE off_per_1k IS NULL OR on_per_1k IS NULL OR off_per_1k < 0 OR on_per_1k < 0)
)
SELECT check_name, coalesce(passed, false) AS passed
FROM checks;
