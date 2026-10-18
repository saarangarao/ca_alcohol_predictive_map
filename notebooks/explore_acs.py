import duckdb

con = duckdb.connect()

def acs(name):
    # header=true is required: with all_varchar the sniffer can't tell header from data
    return f"read_csv('data/raw/acs/{name}.csv', header=true, all_varchar=true)"

# 1. Row counts. GEO_ID = 'Geography' is the second header row of labels, so exclude it.
for name in ["Population", "Median-Income", "Median-Age"]:
    con.sql(f"""
        SELECT '{name}' AS file,
               count(*) AS n_zctas,
               sum((right(GEO_ID, 5) BETWEEN '90001' AND '96162')::int) AS in_ca_range
        FROM {acs(name)}
        WHERE GEO_ID <> 'Geography'
    """).show()

# 2. Which income estimates can't be converted to a number?
con.sql(f"""
    SELECT B19013_001E AS value, count(*) AS n
    FROM {acs('Median-Income')}
    WHERE GEO_ID <> 'Geography'
      AND try_cast(B19013_001E AS DOUBLE) IS NULL
    GROUP BY 1
    ORDER BY n DESC
""").show()
