"""One command rebuilds everything: raw files -> clean -> features -> queries -> clusters -> model -> figures.

    python run_all.py               full rebuild (tests first)
    python run_all.py --skip-tests  skip the pytest step
    python run_all.py --with-heavy  also run the optional bigger-model experiment (about 3 more minutes)

Run it from the project root, with the virtual environment active, after placing the raw files
described in README.md ("How to reproduce"). Every step rewrites its tables in
data/market_map.duckdb and its files in outputs/, so the run is repeatable.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

REQUIRED_FILES = [
    "data/raw/abc/ABC-DailyDataExport.csv",
    "data/raw/acs/Population.csv",
    "data/raw/acs/Median-Income.csv",
    "data/raw/acs/Median-Age.csv",
    "data/raw/census_ref/2024_Gaz_zcta_national.txt",
    "data/raw/census_ref/tab20_zcta520_county20_natl.txt",
    "data/reference/channel_lookup.csv",
]

STEPS = [
    ("clean the ABC license data (phase 1)", "src/ingest_abc.py"),
    ("load Census data and join it to the outlets (phase 2)", "src/ingest_acs.py"),
    ("build the ZIP feature table (phase 3)", "src/build_features.py"),
    ("run the SQL queries and sanity checks (phase 4)", "src/run_queries.py"),
    ("cluster ZIPs into archetypes (phase 5)", "src/cluster.py"),
    ("fit and validate the models (phase 6)", "src/model.py"),
    ("interpretation and robustness checks (phase 7)", "src/interpret.py"),
    ("make the remaining figures (phase 8)", "src/figures.py"),
]
HEAVY_STEP = ("bigger-model experiment (optional)", "src/model_heavy.py")


def run(label, command):
    print(f"\n=== {label}", flush=True)
    start = time.time()
    subprocess.run(command, check=True)
    print(f"--- done in {time.time() - start:.0f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--with-heavy", action="store_true")
    args = parser.parse_args()

    missing = [f for f in REQUIRED_FILES if not Path(f).exists()]
    if missing:
        sys.exit("Missing input files (see README.md, 'How to reproduce'):\n  " + "\n  ".join(missing))

    began = time.time()
    if not args.skip_tests:
        run("tests", [sys.executable, "-m", "pytest", "-q"])
    steps = list(STEPS)
    if args.with_heavy:
        steps.insert(steps.index(next(s for s in steps if s[1] == "src/interpret.py")), HEAVY_STEP)
    for label, script in steps:
        run(label, [sys.executable, script])
    print(f"\nAll steps finished in {time.time() - began:.0f}s. Results are in outputs/tables and outputs/figures.")


if __name__ == "__main__":
    main()
