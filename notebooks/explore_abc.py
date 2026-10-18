import duckdb

ABC = "data/raw/abc/ABC-DailyDataExport.csv"

con = duckdb.connect()   # in-memory database; it disappears when the script ends

# A VIEW is a saved query. Nothing is copied; DuckDB re-reads the file each time.
con.sql(f"""
    CREATE VIEW abc AS
    SELECT *
    FROM read_csv('{ABC}', skip=1, all_varchar=true)
""")

con.sql("DESCRIBE abc").show()                   # column names and types
con.sql("SELECT count(*) AS n_rows FROM abc").show()

# left out the name and address columns on purpose.
con.sql("""
    SELECT "License Type", "File Number", "Lic or App", "Type Status",
           "Prem State", "Prem Zip", "Prem County"
    FROM abc
    LIMIT 5
""").show()

def profile(col, limit=15):
    """Show how often each distinct value appears in one column."""
    con.sql(f"""
        SELECT "{col}" AS value, count(*) AS n
        FROM abc
        GROUP BY 1
        ORDER BY n DESC
        LIMIT {limit}
    """).show()

for col in ["Lic or App", "Type Status", "Master Ind", "Prem State"]:
    print(f"\n=== {col} ===")
    profile(col)

# How many license RECORDS vs how many distinct license NUMBERS?
con.sql("""
    SELECT count(*)                      AS n_rows,
           count(DISTINCT "File Number") AS n_file_numbers
    FROM abc
""").show()
