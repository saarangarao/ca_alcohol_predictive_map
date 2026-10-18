-- 06 | License issue-year cohorts
-- WARNING (survivorship bias): the ABC file lists only licenses that exist TODAY. Outlets that
-- opened and later closed are missing, so older years look quieter than they really were. The
-- issue date is also not the opening date (transfers and ownership changes can reset it).
-- Read this as "the age profile of today's outlets", NOT as growth or decline over time.
--
-- Question:  in which years were today's active retail licenses originally issued?
-- Source:    outlets_deduped (one row per outlet per channel, before the ZIP check).
-- Technique: CTE + window functions for a running (cumulative) total within each channel.
WITH by_year AS (
    SELECT year(type_orig_iss_date) AS issue_year,
           channel,
           count(*)                 AS n_outlets
    FROM outlets_deduped
    WHERE type_orig_iss_date IS NOT NULL
    GROUP BY 1, 2
)
SELECT issue_year, channel, n_outlets,
       sum(n_outlets) OVER (PARTITION BY channel ORDER BY issue_year) AS cumulative_outlets,
       round(100.0 * sum(n_outlets) OVER (PARTITION BY channel ORDER BY issue_year)
                   / sum(n_outlets) OVER (PARTITION BY channel), 1)   AS cumulative_pct
FROM by_year
ORDER BY channel, issue_year;
