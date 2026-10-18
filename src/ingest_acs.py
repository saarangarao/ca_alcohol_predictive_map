"""Phase 2 - load Census data (ACS + reference files) and join it to the cleaned ABC outlets."""
import duckdb

DB = "data/market_map.duckdb"
ACS_DIR = "data/raw/acs"
GAZETTEER = "data/raw/census_ref/2024_Gaz_zcta_national.txt"
ZCTA_COUNTY = "data/raw/census_ref/tab20_zcta520_county20_natl.txt"

POP_FLOOR = 1000                       # ZIPs below this population are too small for per-capita ratios
CA_ZIP_MIN, CA_ZIP_MAX = "90001", "96162"


def acs_csv(name):
    # header=true is required: with all_varchar the sniffer can't tell header from data
    return f"read_csv('{ACS_DIR}/{name}.csv', header=true, all_varchar=true)"


def to_num(col):
    """ACS text -> number. Drops thousands commas and the top-code '+'.
    Anything else ('-', '**', '2,500-') becomes NULL."""
    return f"try_cast(replace(replace({col}, ',', ''), '+', '') AS DOUBLE)"


def build_raw_acs(con):
    """2.1 - load each ACS file exactly as-is."""
    for table, name in [("raw_acs_pop", "Population"),
                        ("raw_acs_income", "Median-Income"),
                        ("raw_acs_age", "Median-Age")]:
        con.sql(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {acs_csv(name)}")


def build_acs_parsed(con):
    """2.2 + 2.3 - one row per California ZIP, numeric columns, label row skipped."""
    con.sql(f"""
        CREATE OR REPLACE TABLE acs_parsed AS
        SELECT right(p.GEO_ID, 5)                        AS zip5,
               {to_num('p.B01003_001E')}                 AS population,
               {to_num('p.B01003_001M')}                 AS population_moe,
               {to_num('i.B19013_001E')}                 AS median_income,
               {to_num('i.B19013_001M')}                 AS median_income_moe,
               coalesce(i.B19013_001E LIKE '%+', false)  AS income_top_coded,
               {to_num('a.B01002_001E')}                 AS median_age,
               {to_num('a.B01002_001M')}                 AS median_age_moe
        FROM raw_acs_pop    AS p
        JOIN raw_acs_income AS i ON p.GEO_ID = i.GEO_ID
        JOIN raw_acs_age    AS a ON p.GEO_ID = a.GEO_ID
        WHERE p.GEO_ID <> 'Geography'
          AND right(p.GEO_ID, 5) BETWEEN '{CA_ZIP_MIN}' AND '{CA_ZIP_MAX}'
    """)
    # How many values became NULL after coercion?
    cols = ["population", "population_moe", "median_income",
            "median_income_moe", "median_age", "median_age_moe"]
    counts = " UNION ALL ".join(
        f"SELECT '{c}' AS column_name, count(*) FILTER (WHERE {c} IS NULL) AS n_missing, "
        f"count(*) AS n_rows FROM acs_parsed" for c in cols)
    con.sql(f"CREATE OR REPLACE TABLE acs_missing AS {counts}")


def build_reference(con):
    """2.4 - land area and coordinates, and ONE county per ZIP (largest overlap wins)."""
    con.sql(f"""
        CREATE OR REPLACE TABLE gazetteer AS
        SELECT GEOID                          AS zip5,
               try_cast(ALAND_SQMI AS DOUBLE) AS land_sqmi,
               try_cast(INTPTLAT   AS DOUBLE) AS lat,
               try_cast(INTPTLONG  AS DOUBLE) AS lon
        FROM read_csv('{GAZETTEER}', delim='\t', header=true, all_varchar=true)
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE zcta_county AS
        SELECT GEOID_ZCTA5_20     AS zip5,
               GEOID_COUNTY_20    AS county_fips,
               NAMELSAD_COUNTY_20 AS county_name
        FROM read_csv('{ZCTA_COUNTY}', delim='|', header=true, all_varchar=true)
        WHERE GEOID_ZCTA5_20 IS NOT NULL AND GEOID_ZCTA5_20 <> ''
        QUALIFY row_number() OVER (
            PARTITION BY GEOID_ZCTA5_20
            ORDER BY try_cast(AREALAND_PART AS BIGINT) DESC, GEOID_COUNTY_20
        ) = 1
    """)


def build_acs_clean(con):
    """2.4 + 2.7 - attach area, coordinates and county; then apply the population floor."""
    con.sql("""
        CREATE OR REPLACE TABLE acs_ca AS
        SELECT p.*, g.land_sqmi, g.lat, g.lon, c.county_fips, c.county_name
        FROM acs_parsed AS p
        LEFT JOIN gazetteer   AS g ON p.zip5 = g.zip5
        LEFT JOIN zcta_county AS c ON p.zip5 = c.zip5
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE acs_clean AS
        SELECT * FROM acs_ca WHERE population >= {POP_FLOOR}
    """)


def build_zip_base(con):
    """2.5 - outlet counts per ZIP, LEFT JOINed onto the ACS ZIP list; no outlets = a real 0."""
    con.sql("""
        CREATE OR REPLACE TABLE zip_outlets AS
        SELECT zip5,
               count(*) FILTER (WHERE channel = 'OFF_SALE')     AS outlets_off,
               count(*) FILTER (WHERE channel = 'ON_SALE_CORE') AS outlets_on_core
        FROM clean_outlets
        GROUP BY zip5
    """)
    con.sql("""
        CREATE OR REPLACE TABLE zip_base AS
        SELECT a.*,
               coalesce(o.outlets_off, 0)     AS outlets_off,
               coalesce(o.outlets_on_core, 0) AS outlets_on_core
        FROM acs_clean AS a
        LEFT JOIN zip_outlets AS o ON a.zip5 = o.zip5
    """)


def build_join_report(con):
    """2.6 + 2.7 - join quality in BOTH directions, plus a reconciliation of every outlet."""
    con.sql("""
        CREATE OR REPLACE TABLE join_misses_abc AS
        SELECT o.zip5, o.outlets_off, o.outlets_on_core
        FROM zip_outlets AS o
        LEFT JOIN acs_ca AS a ON o.zip5 = a.zip5
        WHERE a.zip5 IS NULL
    """)
    con.sql("""
        CREATE OR REPLACE TABLE join_report AS
        SELECT 1 AS ord, 'ACS ZIPs in California range' AS metric, count(*)::BIGINT AS value FROM acs_ca
        UNION ALL SELECT 2, 'ABC ZIPs with at least one outlet', count(*) FROM zip_outlets
        UNION ALL SELECT 3, 'ABC ZIPs with NO ACS match (join_misses_abc)', count(*) FROM join_misses_abc
        UNION ALL SELECT 4, '   outlets in those ZIPs',
                            coalesce(sum(outlets_off + outlets_on_core), 0)::BIGINT FROM join_misses_abc
        UNION ALL SELECT 5, 'ACS ZIPs removed by population floor',
                            (SELECT count(*) FROM acs_ca) - (SELECT count(*) FROM acs_clean)
        UNION ALL SELECT 6, '   outlets in those ZIPs',
                            coalesce(sum(o.outlets_off + o.outlets_on_core), 0)::BIGINT
                            FROM zip_outlets AS o
                            JOIN acs_ca AS a ON o.zip5 = a.zip5
                            LEFT JOIN acs_clean AS c ON o.zip5 = c.zip5
                            WHERE c.zip5 IS NULL
        UNION ALL SELECT 7, 'ZIPs kept in zip_base', count(*) FROM zip_base
        UNION ALL SELECT 8, '   of which have zero outlets (real zeros, kept)',
                            count(*) FROM zip_base WHERE outlets_off + outlets_on_core = 0
        UNION ALL SELECT 9, 'outlets in zip_base', sum(outlets_off + outlets_on_core)::BIGINT FROM zip_base
        UNION ALL SELECT 10, 'outlets in clean_outlets (must equal rows 4 + 6 + 9)',
                            count(*) FROM clean_outlets
    """)


if __name__ == "__main__":
    con = duckdb.connect(DB)
    build_raw_acs(con)
    build_acs_parsed(con)
    build_reference(con)
    build_acs_clean(con)
    build_zip_base(con)
    build_join_report(con)
    con.sql("SELECT * FROM acs_missing").show()
    con.sql("SELECT metric, value FROM join_report ORDER BY ord").show(max_rows=20)
