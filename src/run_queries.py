"""Phase 4 runner - execute every queries/*.sql file and save the result to outputs/tables/."""
from pathlib import Path

import duckdb

DB = "data/market_map.duckdb"
QUERY_DIR = Path("queries")
OUT_DIR = Path("outputs/tables")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DB, read_only=True)
    sanity_failures = []
    for sql_file in sorted(QUERY_DIR.glob("*.sql")):
        df = con.sql(sql_file.read_text()).df()
        out = OUT_DIR / f"{sql_file.stem}.csv"
        df.to_csv(out, index=False)
        print(f"{sql_file.name}: {len(df):,} rows -> {out}")
        if sql_file.stem.startswith("07"):
            sanity_failures = df.loc[~df["passed"], "check_name"].tolist()
    if sanity_failures:
        raise SystemExit("SANITY CHECKS FAILED:\n  " + "\n  ".join(sanity_failures))
    print("All sanity checks passed.")


if __name__ == "__main__":
    main()
