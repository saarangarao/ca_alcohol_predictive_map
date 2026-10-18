import duckdb

DB = "data/market_map.duckdb"        
ABC_CSV = "data/raw/abc/ABC-DailyDataExport.csv"
LOOKUP_CSV = "data/reference/channel_lookup.csv"

CHANNELS_KEPT = "('OFF_SALE', 'ON_SALE_CORE')"   # add 'ON_SALE_OTHER' for a sensitivity run

# One list drives BOTH the counts and the real filtering, so they can never disagree.
FILTERS = [
    ("premise state = CA",   "prem_state = 'CA'"),
    ("issued licenses only", "lic_or_app = 'LIC'"),
    ("status ACTIVE",        "type_status = 'ACTIVE'"),
    ("retail channels",      f"channel IN {CHANNELS_KEPT}"),
]


def build_raw(con):
    """1.1 - Load the file exactly as-is. No edits, nothing dropped."""
    con.sql(f"""
        CREATE OR REPLACE TABLE raw_abc AS
        SELECT * FROM read_csv('{ABC_CSV}', skip=1, all_varchar=true)
    """)


def build_std(con):
    """1.2 - snake_case names, real types, blanks -> NULL, personal columns dropped."""
    con.sql("""
        CREATE OR REPLACE TABLE abc_std AS
        SELECT
            lpad(trim("License Type"), 2, '0')                                 AS license_type,
            trim("File Number")                                                AS file_number,
            trim("Lic or App")                                                 AS lic_or_app,
            trim("Type Status")                                                AS type_status,
            strptime(NULLIF(trim("Type Orig Iss Date"), ''), '%d-%b-%Y')::DATE AS type_orig_iss_date,
            NULLIF(trim("Dup Counts"), '')                                     AS dup_counts,
            trim("Master Ind")                                                 AS master_ind,
            NULLIF(trim("Prem State"), '')                                     AS prem_state,
            NULLIF(trim("Prem Zip"), '')                                       AS prem_zip,
            NULLIF(trim("Prem County"), '')                                    AS prem_county,
            NULLIF(trim("Prem Census Tract #"), '')                            AS prem_census_tract
        FROM raw_abc
    """)


def build_lookup(con):
    """1.3 - Load the channel lookup. all_varchar keeps '02' from becoming 2."""
    con.sql(f"""
        CREATE OR REPLACE TABLE channel_lookup AS
        SELECT * FROM read_csv('{LOOKUP_CSV}', header=true, all_varchar=true)
    """)




def count(con, table, where="TRUE"):
    return con.sql(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]


def build_clean(con):
    """1.4-1.6 - label, filter, dedupe, clean ZIPs; record every step."""
    # Unmatched license types are flagged UNMAPPED, not dropped.
    con.sql("""
        CREATE OR REPLACE TABLE abc_labeled AS
        SELECT a.*, coalesce(c.channel, 'UNMAPPED') AS channel
        FROM abc_std AS a
        LEFT JOIN channel_lookup AS c USING (license_type)
    """)

    # 1.4 - rows remaining after each filter, applied cumulatively
    steps = [("start: all ABC records", count(con, "abc_labeled"))]
    preds = []
    for label, pred in FILTERS:
        preds.append(pred)
        steps.append((label, count(con, "abc_labeled", " AND ".join(preds))))
    where = " AND ".join(preds)

    # 1.5 + 1.6 - one row per (file_number, channel); the master record wins
    con.sql(f"""
        CREATE OR REPLACE TABLE outlets_deduped AS
        SELECT *,
               left(prem_zip, 5) AS zip5,
               coalesce(regexp_matches(left(prem_zip, 5), '^[0-9]{{5}}$'), false) AS zip_ok
        FROM abc_labeled
        WHERE {where}
        QUALIFY row_number() OVER (
            PARTITION BY file_number, channel
            ORDER BY (master_ind = 'Y') DESC, type_orig_iss_date, license_type
        ) = 1
    """)
    steps.append(("one row per (file_number, channel)", count(con, "outlets_deduped")))

    con.sql("""
        CREATE OR REPLACE TABLE clean_outlets AS
        SELECT file_number, channel, license_type, zip5, prem_county AS county
        FROM outlets_deduped
        WHERE zip_ok
    """)
    con.sql("""
        CREATE OR REPLACE TABLE bad_zip AS
        SELECT file_number, channel, prem_zip
        FROM outlets_deduped
        WHERE NOT zip_ok
    """)
    steps.append(("valid 5-digit ZIP", count(con, "clean_outlets")))

    con.sql("CREATE OR REPLACE TABLE filter_attrition "
            "(step_no INTEGER, step VARCHAR, rows_remaining BIGINT)")
    con.executemany("INSERT INTO filter_attrition VALUES (?, ?, ?)",
                    [(i, s, n) for i, (s, n) in enumerate(steps)])


if __name__ == "__main__":
    con = duckdb.connect(DB)
    build_raw(con)
    build_std(con)
    build_lookup(con)
    build_clean(con)
    con.sql("""
        SELECT step_no, step, rows_remaining,
               lag(rows_remaining) OVER (ORDER BY step_no) - rows_remaining AS rows_removed
        FROM filter_attrition
        ORDER BY step_no
    """).show()
    print("bad_zip rows:", count(con, "bad_zip"))

