-- 01 | Outlets per ZIP by channel
-- Question:  how many retail outlets of each kind does every ZIP code have?
-- Source:    clean_outlets (one row per outlet per channel). Covers ALL ZIPs, including ones
--            with no Census match or below the population floor; query 07 reconciles this
--            against zip_features.
-- Technique: conditional aggregation, count(*) FILTER (WHERE ...), one pass over the table.
SELECT zip5,
       count(*) FILTER (WHERE channel = 'OFF_SALE')     AS outlets_off,
       count(*) FILTER (WHERE channel = 'ON_SALE_CORE') AS outlets_on_core,
       count(*)                                         AS outlets_total
FROM clean_outlets
GROUP BY zip5
ORDER BY outlets_total DESC, zip5;
