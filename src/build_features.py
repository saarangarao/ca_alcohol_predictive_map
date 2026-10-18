"""Phase 3 - the master feature table: one row per ZIP, ready for clustering and modeling."""
import duckdb

DB = "data/market_map.duckdb"

# Visitor-heavy rule: flag a ZIP if either outlet density is a "far outlier" on the log1p scale,
# i.e. above Q3 + FENCE_K * IQR (Tukey's fence; 3 = far out, 1.5 = merely unusual).
FENCE_K = 3.0

# ZIPs added to the flag BY HAND, after the first modelling run (Phase 6) showed them with the
# largest residuals: Napa city, wine-country tourism. Kept apart from the rule so the README can
# say exactly what was added and when; visitor_heavy = rule OR manual.
MANUAL_VISITOR_ZIPS = ("94558", "94559")


def build_zip_city(con):
    """A human-readable label for each ZIP (most common premise city). A label only, never a join key."""
    con.sql("""
        CREATE OR REPLACE TABLE zip_city AS
        SELECT o.zip5, mode(r."Prem City") AS city
        FROM clean_outlets AS o
        JOIN raw_abc AS r ON trim(r."File Number") = o.file_number
        GROUP BY o.zip5
    """)


def build_zip_features(con):
    """3.1 - 3.3 - densities, log transforms and the visitor-heavy flag."""
    manual = ", ".join(f"'{z}'" for z in MANUAL_VISITOR_ZIPS)
    con.sql(f"""
        CREATE OR REPLACE TABLE zip_features AS
        WITH base AS (
            SELECT z.zip5, c.city, z.county_fips, z.county_name AS county,
                   z.lat, z.lon, z.land_sqmi,
                   z.population, z.population_moe,
                   z.median_income, z.median_income_moe, z.income_top_coded,
                   z.median_age, z.median_age_moe,
                   z.outlets_off, z.outlets_on_core,
                   z.outlets_off     * 1000.0 / z.population                         AS off_per_1k,
                   z.outlets_on_core * 1000.0 / z.population                         AS on_per_1k,
                   z.outlets_on_core * 1.0 / nullif(z.outlets_on_core + z.outlets_off, 0) AS on_share,
                   z.population / nullif(z.land_sqmi, 0)                             AS pop_density
            FROM zip_base AS z
            LEFT JOIN zip_city AS c ON z.zip5 = c.zip5
        ),
        fences AS (
            SELECT quantile_cont(ln(1 + off_per_1k), 0.25) AS off_q1,
                   quantile_cont(ln(1 + off_per_1k), 0.75) AS off_q3,
                   quantile_cont(ln(1 + on_per_1k),  0.25) AS on_q1,
                   quantile_cont(ln(1 + on_per_1k),  0.75) AS on_q3
            FROM base
        )
        ,
        scored AS (
            SELECT b.*,
                   ln(b.population)        AS log_population,
                   ln(b.median_income)     AS log_income,
                   ln(b.pop_density)       AS log_pop_density,
                   ln(1 + b.off_per_1k)    AS log1p_off_per_1k,
                   ln(1 + b.on_per_1k)     AS log1p_on_per_1k,
                   (   ln(1 + b.off_per_1k) > f.off_q3 + {FENCE_K} * (f.off_q3 - f.off_q1)
                    OR ln(1 + b.on_per_1k)  > f.on_q3  + {FENCE_K} * (f.on_q3  - f.on_q1)) AS visitor_heavy_rule,
                   b.zip5 IN ({manual})    AS visitor_heavy_manual
            FROM base AS b
            CROSS JOIN fences AS f
        )
        SELECT *, (visitor_heavy_rule OR visitor_heavy_manual) AS visitor_heavy
        FROM scored
    """)


if __name__ == "__main__":
    con = duckdb.connect(DB)
    build_zip_city(con)
    build_zip_features(con)
    n, n_unique = con.sql("SELECT count(*), count(DISTINCT zip5) FROM zip_features").fetchone()
    print(f"zip_features: {n:,} rows, {n_unique:,} distinct zip5")
    con.sql("""
        SELECT column_name, column_type, round(null_percentage, 1) AS pct_null
        FROM (SUMMARIZE zip_features)
    """).show(max_rows=40)
