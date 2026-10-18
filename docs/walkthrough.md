# Technical walkthrough

A guided tour of the whole repository: what every file does, how data flows through it, why each decision was
made, and the concepts underneath. It is written for two uses: a ten-minute memory refresher (read sections 1 to 4
and the cheat sheets), and an in-depth study guide (read in order, run the snippets, do the exercises at the end).

Everything here was checked against the code and the database as they stand. When a number is quoted, it comes from a
file in `outputs/tables/` or from the DuckDB database `data/market_map.duckdb`.

## Contents

1. [The 60-second picture](#1-the-60-second-picture)
2. [Repository map](#2-repository-map)
3. [Running things, and looking inside the database](#3-running-things-and-looking-inside-the-database)
4. [The data model: every table in the database](#4-the-data-model-every-table-in-the-database)
5. [The source data in depth](#5-the-source-data-in-depth)
6. [Phase 1: ingest and clean the ABC data](#6-phase-1-ingest-and-clean-the-abc-data)
7. [Phase 2: integrate the Census data](#7-phase-2-integrate-the-census-data)
8. [Phase 3: the master feature table](#8-phase-3-the-master-feature-table)
9. [Phase 4: the SQL analysis layer](#9-phase-4-the-sql-analysis-layer)
10. [Phase 5: K-means archetypes and PCA](#10-phase-5-k-means-archetypes-and-pca)
11. [Phase 6: prediction and honest validation](#11-phase-6-prediction-and-honest-validation)
12. [Phase 7: interpretation and robustness](#12-phase-7-interpretation-and-robustness)
13. [Phase 8: figures and the chart rules behind them](#13-phase-8-figures-and-the-chart-rules-behind-them)
14. [Phase 9: reproducibility, packaging, privacy](#14-phase-9-reproducibility-packaging-privacy)
15. [Concept cheat sheet](#15-concept-cheat-sheet)
16. [SQL and DuckDB idioms used here](#16-sql-and-duckdb-idioms-used-here)
17. [Python, pandas and scikit-learn patterns used here](#17-python-pandas-and-scikit-learn-patterns-used-here)
18. [Decision log](#18-decision-log)
19. [Things that went wrong, and what they taught](#19-things-that-went-wrong-and-what-they-taught)
20. [Results cheat sheet](#20-results-cheat-sheet)
21. [How to extend the project](#21-how-to-extend-the-project)
22. [Exercises](#22-exercises)
23. [Glossary](#23-glossary)

---

## 1. The 60-second picture

**The question.** California's alcohol regulator (ABC) publishes every licensed outlet. Joined to Census demographics at
ZIP-code level, that supports three questions: how many outlets of each kind does each ZIP have; which ZIPs resemble each
other; and how many off-sale outlets (stores selling sealed containers) would a ZIP's demographics predict, and where does
reality differ most? The project measures **market structure** (who is licensed where), not sales.

**The pipeline.**

```
data/raw/   (never edited, git-ignored)
  abc/ABC-DailyDataExport.csv        acs/{Population,Median-Income,Median-Age}.csv     census_ref/{Gazetteer, relationship}
        |                                         |                                              |
        v   src/ingest_abc.py                     v   src/ingest_acs.py  <----------------------+
  raw_abc -> abc_std -> abc_labeled               raw_acs_* -> acs_parsed -> acs_ca -> acs_clean
          -> outlets_deduped -> clean_outlets                                            |
                    |                                                                    |
                    +------------> zip_outlets ------------------> zip_base <------------+
                                                                      |
                                                                      v   src/build_features.py
                                                                 zip_features   (one row per ZIP, 28 columns)
                                                                      |
          +-----------------------+-----------------------------------+------------------------+
          v                       v                                   v                        v
  src/run_queries.py       src/cluster.py                      src/model.py             (all read zip_features)
  queries/*.sql            -> zip_clusters                     -> zip_residuals
  -> outputs/tables/01-07  -> 05_* figures                     -> 06_* figure
                                                                      |
                                                                      v
                                                    src/interpret.py (07_* tables)     src/figures.py (08_* figures)
```

**The funnel, in numbers.**

| Stage | Count |
|---|---|
| License records in the ABC export | 129,653 |
| ...in California | 126,405 |
| ...issued licenses (not applications) | 106,216 |
| ...status ACTIVE | 102,905 |
| ...retail channels (off-sale, on-sale core) | 72,464 |
| ...one row per outlet and channel | **70,402** |
| ZIPs with at least one outlet | 1,766 |
| California ZIPs in the Census files | 1,802 |
| ...at least 1,000 residents (the **1,419** ZIPs analyzed) | 1,419 |
| ...of which flagged visitor-heavy | 28 |
| ...of which have enough features to cluster | 1,348 |

**Cost.** The whole thing, from raw files to figures, runs in about 100 seconds on a laptop (`python run_all.py`).
The slowest steps are the model (about 50 s) and the robustness checks (about 30 s).

---

## 2. Repository map

```
run_all.py            one command: tests, then every step below in order
Makefile              `make all`, `make test`, `make heavy` wrappers
requirements.txt      pinned versions (Python 3.13.5)
pytest.ini            tells pytest to add src/ to the import path
README.md             the front door (for readers who have not seen the project)

src/
  ingest_abc.py       Phase 1: raw ABC file -> clean_outlets, with an audit trail
  ingest_acs.py       Phase 2: Census data -> zip_base, join-quality reports
  build_features.py   Phase 3: zip_features (densities, logs, visitor-heavy flag)
  run_queries.py      Phase 4 runner: queries/*.sql -> outputs/tables/*.csv, gates on sanity checks
  cluster.py          Phase 5: K-means scan, final fit, profiles, PCA, two figures
  model.py            Phase 6: grouped cross-validation, four models, importance, residuals
  interpret.py        Phase 7: ranked leads, archetype residuals, Stockton check, robustness
  figures.py          Phase 8: three remaining figures
  model_heavy.py      optional experiment: do bigger models help? (no)

queries/              01_ ... 07_*.sql, each a documented question
tests/                conftest.py (fixtures) + 3 test files, 22 tests
data/
  raw/                inputs (git-ignored; see README "How to reproduce")
  reference/channel_lookup.csv   license type -> channel (committed, no personal data)
  market_map.duckdb   the database every step reads and writes (git-ignored, rebuilt by run_all.py)
docs/
  walkthrough.md      this file
  findings.md         the five claims, caveats, limitations
  data_guide.md       column dictionary for the sources and zip_features
outputs/
  tables/             every result as CSV (ZIP-level aggregates only)
  figures/            six PNGs
notebooks/            early exploration scripts (not part of the pipeline)
```

**Who reads and writes what.** Each script rebuilds its own tables with `CREATE OR REPLACE`, so you can re-run any step
alone as long as the steps before it have run once.

| Script | Reads | Writes (tables in the database unless noted) |
|---|---|---|
| `ingest_abc.py` | raw ABC CSV, `channel_lookup.csv` | `raw_abc`, `abc_std`, `channel_lookup`, `abc_labeled`, `outlets_deduped`, `clean_outlets`, `bad_zip`, `filter_attrition` |
| `ingest_acs.py` | 3 ACS CSVs, Gazetteer, relationship file, `clean_outlets` | `raw_acs_pop/income/age`, `acs_parsed`, `acs_missing`, `gazetteer`, `zcta_county`, `acs_ca`, `acs_clean`, `zip_outlets`, `zip_base`, `join_misses_abc`, `join_report` |
| `build_features.py` | `zip_base`, `clean_outlets`, `raw_abc` (city label only) | `zip_city`, `zip_features` |
| `run_queries.py` | `queries/*.sql` over the tables above | `outputs/tables/01_` to `07_*.csv` (files) |
| `cluster.py` | `zip_features` | `zip_clusters`; files: `cluster_selection`, `cluster_profile`, `pca_loadings`, `zip_clusters` CSVs, figures `05_*` |
| `model.py` | `zip_features`, `zip_clusters` | `zip_residuals`; files: `model_results*`, `oof_predictions`, `permutation_importance_by_fold` CSVs, figure `06_*` |
| `interpret.py` | `zip_residuals`, `zip_features`, plus throwaway database copies | files: `07_*` CSVs |
| `figures.py` | `zip_features`, `zip_residuals`, `model_results.csv` | files: figures `08_*` |

---

## 3. Running things, and looking inside the database

**Always from the project root, with the virtual environment active.** Paths in the code are relative, and the wrong
interpreter is the most common failure (`which python` should end in `.venv/bin/python`; use `python -m pytest`).

```bash
source .venv/bin/activate
python run_all.py                  # everything (about 100 s)
python run_all.py --skip-tests     # without pytest
python run_all.py --with-heavy     # plus the optional bigger-model experiment (about 3 more minutes)
python src/cluster.py              # one step on its own
python -m pytest -q                # tests only (22 should pass)
```

**Look inside the database** (a `.duckdb` file is a single-file database holding many tables; open it read-only so you
cannot block or corrupt a run):

```python
import duckdb
con = duckdb.connect("data/market_map.duckdb", read_only=True)

con.sql("SHOW TABLES").show()                                   # all 25 tables
con.sql("DESCRIBE zip_features").show(max_rows=40)             # columns and types
con.sql("SELECT * FROM zip_features WHERE city = 'STOCKTON'").show()
df = con.sql("SELECT * FROM zip_residuals").df()               # same query as a pandas DataFrame
```

Two rules: only one process may hold the database in write mode (a second writer fails), and `.show()` is needed in
scripts because only the interactive prompt auto-prints a query result.

---

## 4. The data model: every table in the database

The database is organized in **layers**, each a deliberate step away from the raw file. A table's *grain* is what one row
means; getting the grain right is the main discipline in data work (it is why the outlet-versus-license-record
distinction took a whole phase).

| Layer | Table | Grain (one row per...) | Rows | Why it exists |
|---|---|---|---|---|
| ABC raw | `raw_abc` | license record, 26 text columns exactly as downloaded | 129,653 | untouched copy; **contains names and addresses**, so it lives only in the git-ignored database |
| ABC clean | `abc_std` | license record, 11 typed columns | 129,653 | snake_case, real types, blanks as NULL, **personal columns dropped** |
| | `channel_lookup` | license type | 84 | type code to channel (OFF_SALE, ON_SALE_CORE, ...) |
| | `abc_labeled` | license record plus channel | 129,653 | join result; unmapped types flagged `UNMAPPED`, not dropped |
| | `outlets_deduped` | (file number, channel), after all filters | 70,402 | adds `zip5` and `zip_ok` |
| | `clean_outlets` | (file number, channel) with a valid ZIP | 70,402 | the analysis-ready outlet table |
| | `bad_zip` | outlet with a malformed ZIP | 0 | a validation sink; empty means the check ran and found nothing |
| | `filter_attrition` | pipeline step | 7 | audit trail of rows surviving each step |
| Census raw | `raw_acs_pop`, `raw_acs_income`, `raw_acs_age` | ZCTA plus one label row | 1,809 each | as downloaded (the label row and a phantom empty column included) |
| Census clean | `acs_parsed` | California ZIP, numeric columns | 1,802 | label row dropped, text coerced to numbers |
| | `acs_missing` | numeric column | 6 | how many values became NULL after coercion |
| | `gazetteer` | ZCTA, nationwide | 33,791 | land area and centroid |
| | `zcta_county` | ZCTA, nationwide | 33,791 | one county per ZCTA (largest overlap) |
| | `acs_ca` | California ZIP with area, centroid and county | 1,802 | before the population floor |
| | `acs_clean` | California ZIP with population of 1,000 or more | 1,419 | after the floor |
| Join | `zip_outlets` | ZIP with at least one outlet | 1,766 | outlet counts per ZIP and channel |
| | `zip_base` | `acs_clean` plus outlet counts (zeros filled) | 1,419 | the join result |
| | `join_misses_abc` | ABC ZIP with no Census match | 95 | join quality, ABC side |
| | `join_report` | metric | 10 | the reconciliation of every outlet |
| Features | `zip_city` | ZIP with outlets | 1,766 | a human-readable label only |
| | `zip_features` | ZIP | 1,419 | **the master table** (28 columns), the input to all analysis |
| Results | `zip_clusters` | ZIP | 1,419 | cluster, cluster name, status, nearest cluster |
| | `zip_residuals` | ZIP | 1,419 | out-of-fold predictions from four models plus the residual |

**Keys.** `file_number` identifies an outlet (a premises with a license). `zip5` (text, 5 characters, leading zeros
preserved) is the join key to every Census table. `county` is used only to build cross-validation groups.

---

## 5. The source data in depth

Four public files feed everything. Their quirks drive most of the cleaning code, so they are worth knowing.

### 5.1 ABC Daily Data Export (`data/raw/abc/ABC-DailyDataExport.csv`)

27.7 MB, downloaded 2026-10-12; a snapshot of every **pending and active** license (not closed ones).

| Quirk | Detail | Handled by |
|---|---|---|
| Banner line | Line 1 is `"Updated Monday 12th of October 2026 ..."`, not a header | `read_csv(..., skip=1)` |
| Header spacing | Some column names have leading spaces (`" Prem State"`) | DuckDB trims them on read |
| Blank means a space | Empty fields are the string `" "`, not NULL | `NULLIF(trim(col), '')` |
| Trailing blank line | 129,656 lines = banner + header + 129,653 records + 1 blank line | DuckDB skips blank lines |
| Leading zeros matter | `02` is a Winegrower license; file numbers are 8-char IDs (`00677645`) | `all_varchar=true`, `lpad` |
| ZIP+4 | `90033-2028` | `left(prem_zip, 5)` |
| Dates | `16-JUL-2009`; blank for applications (21,485 rows) | `strptime(..., '%d-%b-%Y')` |

Distinct values worth memorizing (all statuses, as downloaded):

- `Lic or App`: `LIC` 108,243 (issued license) and `APP` 21,410 (application). Keep `LIC`.
- `Type Status`: ACTIVE 118,683; PEND 7,703; SUREND 2,304; REVPEN 510; **SUSPEN** 323; R64B 130. A third-party glossary
  called suspended `SUPEND` and listed `REV` and `SLMSHD`; the real file has `SUSPEN` and neither of the others, which is
  why the requirements said to verify.
- `Master Ind`: `Y` 110,368, `N` 19,285. Its meaning is not documented in the file, and it is **not** a safe dedupe key
  (see section 6.4, step C).
- `Dup Counts`: blank for 110,567 rows, else `001`, `002`, ...
- 79 distinct license types; the three most common are 41 (restaurants, beer and wine), 47 (restaurants, full liquor)
  and 21 (off-sale general). Three types in the file (73, 76, 92; one record each) are not in the requirements' mapping,
  which is exactly what the `UNMAPPED` label is for.
- 96,563 distinct file numbers in 129,653 records: **rows are not outlets**.
- Blank premise state and blank premise ZIP: 1,291 rows each (all outside the final retail set).
- A `Prem Census Tract #` column exists (blank for 4,314 rows), which would enable a tract-level version.

Columns that hold **personal data**: `Primary Name`, `DBA Name`, `Prem Addr 1/2`, `Mail Addr 1/2`, `Mail City/State/Zip`.
They are loaded into `raw_abc` (untouched copy) and dropped at `abc_std`, so nothing downstream, and nothing committed,
contains them.

### 5.2 Census ACS 5-year, 2024 vintage (`data/raw/acs/*.csv`)

Three tables by ZIP Code Tabulation Area: B01003 (population), B19013 (median household income), B01002 (median age).
Downloaded 2026-10-12. Each file has 1,808 ZCTAs; 1,802 fall in California's ZIP range 90001 to 96162 (the other six are
border ZCTAs).

| Quirk | Detail | Handled by |
|---|---|---|
| Two header rows | Row 1 variable codes, row 2 text labels (`GEO_ID = 'Geography'`) | `WHERE GEO_ID <> 'Geography'` |
| Phantom column | A trailing comma in the header creates an empty extra column (`column4`/`column8`) | ignored |
| `GEO_ID` format | `860Z200US89010`; the ZIP is the last 5 characters | `right(GEO_ID, 5)` |
| Estimate vs margin | `..._001E` estimate, `..._001M` margin of error | both kept |
| Special values | income: `-` (212 ZIPs), `250,000+` (17), `2,500-` (1); median age: `-` (61); margins of error `**` / `***` | `to_num()` in `ingest_acs.py` |
| `header=true` required | with `all_varchar=true` the sniffer cannot tell header from data and calls columns `column0...` | explicit option |

ACS numbers are **estimates with margins of error**, larger in small ZIPs. This repository keeps the margins but does
not propagate them (a listed add-on).

### 5.3 Census Gazetteer and ZCTA-county relationship file (`data/raw/census_ref/`)

- `2024_Gaz_zcta_national.txt`: **tab**-delimited; `GEOID` (the ZIP), `ALAND_SQMI` (land area in square miles, the
  denominator of population density), `INTPTLAT`/`INTPTLONG` (centroid). 33,791 ZCTAs nationwide.
- `tab20_zcta520_county20_natl.txt`: **pipe**-delimited, starts with a byte-order mark, and its first data rows have an
  empty ZCTA (land covered by no ZIP area). A ZCTA that straddles counties has several rows; `AREALAND_PART` is the land
  area of that ZCTA-county overlap, which is what lets us pick one county per ZIP.

### 5.4 The channel lookup (`data/reference/channel_lookup.csv`)

84 rows mapping each license type to a **channel**. This is a join target instead of a long `CASE` statement so it can be
reviewed, versioned and extended in one place.

| Channel | Types | Meaning | Used? |
|---|---|---|---|
| `OFF_SALE` | 20, 21 | stores selling sealed containers | yes (the modeling target) |
| `ON_SALE_CORE` | 40, 41, 42, 47, 48, 61 | bars, restaurants, night clubs | yes |
| `ON_SALE_OTHER` | 49, 59, 60, 70, 75, 90, 99 and 63-65, 67, 69, 71, 72, 78, 80, 87, 88 | seasonal or special-purpose | no (switch in `CHANNELS_KEPT`) |
| `CLUB` | 50, 51, 52, 57 | members-only clubs | no |
| `PRODUCER_RETAIL` | 02, 23, 74 | winegrowers, small brewers, distillers | no |
| `EXCLUDE` | the rest | manufacturers, wholesalers, temporary, vessels, permits | no |

Caveat that belongs in every write-up: the channel is the license's *primary business model*. Several on-sale types also
allow off-premises sales of beer and wine.

---

## 6. Phase 1: ingest and clean the ABC data

File: [`src/ingest_abc.py`](../src/ingest_abc.py). Four functions run in order; each leaves tables behind.

### 6.1 `build_raw`: load it exactly as it is

```python
CREATE OR REPLACE TABLE raw_abc AS
SELECT * FROM read_csv('data/raw/abc/ABC-DailyDataExport.csv', skip=1, all_varchar=true)
```

- `CREATE OR REPLACE TABLE ... AS SELECT` makes the step **idempotent**: run it ten times, get the same table.
- `skip=1` ignores the banner line. DuckDB's CSV sniffer can often guess this, but an explicit option does not break when
  ABC changes the file's layout next week.
- `all_varchar=true` loads every column as text. This is deliberate. DuckDB's sniffer *currently* keeps leading-zero values
  such as `00677645` and `02` as text on its own, so this file would load as text anyway, but that is a heuristic that can
  change between versions or files (and pandas' `read_csv` would silently turn `00677645` into `677645`). The explicit option
  makes it a guarantee. Types are applied later, on purpose, in `build_std`.
- Principle: the raw layer is **never edited**. If you find a cleaning bug, you fix code and rerun; you never touch data.

### 6.2 `build_std`: names, types, blanks, privacy

| Expression | What it does | Why |
|---|---|---|
| `lpad(trim("License Type"), 2, '0')` | trim spaces, left-pad to two characters | guarantees `'02'`, never `'2'` or `' 2'` |
| `trim("File Number")` | trim spaces | the outlet identifier |
| `strptime(NULLIF(trim("Type Orig Iss Date"), ''), '%d-%b-%Y')::DATE` | text like `16-JUL-2009` to a real date; blank to NULL | `NULLIF(x, '')` turns an empty string into NULL first, so `strptime` is never asked to parse a blank |
| `NULLIF(trim("Prem Zip"), '')` | blank to NULL | the file's blank is a *space*, not NULL, and `WHERE col IS NULL` would never find it |
| (no mailing, name or address columns) | dropped | personal data stops here; see section 14 |

Result: `abc_std`, 11 columns, 129,653 rows, all text except one date.

### 6.3 `build_lookup`: the channel table

Loads `channel_lookup.csv` with `all_varchar=true` for the same reason as above: `'02'` must stay `'02'`, because if a
numeric type ever slipped in, the join to `abc_std.license_type` could quietly stop matching the zero-padded types. A test
(`("02", "PRODUCER_RETAIL")`) guards this.

### 6.4 `build_clean`: label, filter, count, deduplicate, validate

**Step A, label.**

```python
CREATE OR REPLACE TABLE abc_labeled AS
SELECT a.*, coalesce(c.channel, 'UNMAPPED') AS channel
FROM abc_std AS a
LEFT JOIN channel_lookup AS c USING (license_type)
```

A `LEFT JOIN` keeps every license record; those with no lookup row get a NULL channel, which `coalesce` turns into the
label `UNMAPPED`. That is the project rule "**flag, don't drop**": the three unmapped types (73, 76, 92) stay visible
in the counts and are removed later by an explicit, counted filter, not silently by a join. `USING (col)` is shorthand
for `ON a.col = c.col` that also merges the column.

**Step B, the filters and the attrition table.**

```python
FILTERS = [
    ("premise state = CA",   "prem_state = 'CA'"),
    ("issued licenses only", "lic_or_app = 'LIC'"),
    ("status ACTIVE",        "type_status = 'ACTIVE'"),
    ("retail channels",      f"channel IN {CHANNELS_KEPT}"),
]
```

The loop appends one predicate at a time and counts the rows that survive the *cumulative* filter:

```python
preds = []
for label, pred in FILTERS:
    preds.append(pred)
    steps.append((label, count(con, "abc_labeled", " AND ".join(preds))))
where = " AND ".join(preds)
```

The same list builds the real `WHERE` clause (`where`) that produces `outlets_deduped`. **One list drives both the
counts and the filtering, so they cannot disagree.** The resulting table (`filter_attrition`):

| Step | Rows remaining | Removed |
|---|---|---|
| start: all ABC records | 129,653 | |
| premise state = CA | 126,405 | 3,248 |
| issued licenses only | 106,216 | 20,189 |
| status ACTIVE | 102,905 | 3,311 |
| retail channels | 72,464 | 30,441 |
| one row per (file number, channel) | 70,402 | 2,062 |
| valid 5-digit ZIP | 70,402 | 0 |

The script prints this with a window function: `lag(rows_remaining) OVER (ORDER BY step_no) - rows_remaining`. `LAG`
looks at the previous row in the given order, which is how "rows removed" is computed without a loop.

**Step C, deduplicate: one row per outlet and channel.** This is the most important modeling decision in Phase 1, so
here is the evidence. After the filters there are 72,464 license *records*. Candidate definitions of "an outlet":

| Rule | Count | Verdict |
|---|---|---|
| every record | 72,464 | records are not outlets |
| distinct `file_number` | 69,643 | merges premises that hold both an off-sale and an on-sale license; loses a channel |
| distinct (`file_number`, `channel`) | **70,402** | **chosen**: matches the definition `outlets_off = COUNT(DISTINCT file_number) WHERE channel = OFF_SALE` |
| rows with `master_ind = 'Y'` | 70,406 | **not safe**: 762 file numbers have several master rows, and one has none |

What the duplicate structure looks like: 2,774 file numbers have more than one retail record (2,729 with two, 43 with
three, 2 with four). The most common combinations are 47+47 (1,820 file numbers: the same license type twice, the
second flagged `N`), 21+42 (309), 48+48 (155), 21+41 (148), 20+42 (110). 722 file numbers span *both* channels (a store
with a bar license). No file number spans two ZIPs or two counties, so keeping any one row per group cannot move an outlet.

```sql
SELECT *, left(prem_zip, 5) AS zip5, ...
FROM abc_labeled
WHERE {where}
QUALIFY row_number() OVER (
    PARTITION BY file_number, channel
    ORDER BY (master_ind = 'Y') DESC, type_orig_iss_date, license_type
) = 1
```

- `row_number() OVER (PARTITION BY g ORDER BY k)` numbers rows 1, 2, 3, ... **restarting for each group `g`**, in the order
  given by `k`. Keeping number 1 keeps the "best" row per group.
- `QUALIFY` filters on a window function's result. Mental model: `WHERE` filters rows *before* windows are computed,
  `HAVING` filters groups after aggregation, `QUALIFY` filters after windows.
- The ordering makes the choice **deterministic**: master record first (`true` sorts above `false` with `DESC`), then the
  earliest issue date, then license type as a final tie-break. Without a full ordering, "keep one arbitrary row" could pick
  differently on another machine.

**Step D, validate ZIPs.**

```sql
coalesce(regexp_matches(left(prem_zip, 5), '^[0-9]{{5}}$'), false) AS zip_ok
```

- `{{5}}` is a regex quantifier ("exactly five digits"). Inside a Python f-string, braces are special, so they are
  doubled and Python emits `{5}`.
- **Three-valued logic.** A regex applied to NULL returns NULL, and `NOT NULL` is also NULL, so a bare `WHERE NOT valid`
  would send NULL-ZIP rows to *neither* table: a silent drop. `coalesce(..., false)` makes `zip_ok` strictly true or false,
  so every row lands in exactly one of `clean_outlets` (`WHERE zip_ok`) or `bad_zip` (`WHERE NOT zip_ok`).
- `bad_zip` is empty today because earlier filters already removed the 1,291 blank-ZIP records. An empty check table is
  still valuable: it proves the validation ran, and it will fill up if next week's file is messier.

### 6.5 The tests ([`tests/`](../tests))

22 tests, all on tiny hand-built data, not the real file.

| File | Tests | What it guards |
|---|---|---|
| `test_channel_mapping.py` | 8 (6 parametrized) | known codes map to the right channel, **`02` keeps its zero**, unknown type becomes `UNMAPPED` and survives, non-retail never reaches `clean_outlets` |
| `test_dedupe.py` | 6 | the same type twice is one outlet; two `Y` masters still one outlet; two channels give two rows; the master row is the one kept; an outlet with no master is not lost; different file numbers stay different |
| `test_zip_cleaning.py` | 8 (5 parametrized) | ZIP+4 is trimmed; leading zeros survive; NULL, empty, 4-digit, letters and a letter-O all go to `bad_zip`; `clean + bad = deduped` (nothing silently lost) |

**How they work** ([`tests/conftest.py`](../tests/conftest.py)):

- A **fixture** (`@pytest.fixture`) is a function whose result pytest passes to any test that names it as a parameter.
  `con` gives each test a fresh *in-memory* DuckDB with the real lookup table and an empty `abc_std`, so tests never touch
  your real database and cannot affect one another.
- `add(**overrides)` inserts one fake license with sensible defaults (an active, issued, off-sale California license), so
  each test states only what it cares about: `add(prem_zip="90033-2028")`.
- This only works because `build_clean(con)` **takes the connection as an argument** instead of opening its own, and
  because the module is guarded by `if __name__ == "__main__":`, so importing it does not run the pipeline.
- The tests encode findings: `test_two_master_rows_still_count_as_one_outlet` is the master-flag discovery frozen as a check.
- A test is only worth having if it can fail. Try it: change `) = 1` to `) >= 1` in the `QUALIFY`, run `pytest`, and
  watch the dedupe tests fail (then `git restore` the file).

---

## 7. Phase 2: integrate the Census data

File: [`src/ingest_acs.py`](../src/ingest_acs.py). Constants at the top are the knobs: `POP_FLOOR = 1000`,
`CA_ZIP_MIN/MAX = "90001"/"96162"`.

### 7.1 Loading and parsing (`build_raw_acs`, `build_acs_parsed`)

- The raw tables are loaded as-is (`header=true, all_varchar=true`; see section 5.2 for why both).
- `to_num(col)` builds the SQL expression `try_cast(replace(replace(col, ',', ''), '+', '') AS DOUBLE)`:
  strip thousands commas, strip the top-code `+`, then cast. `try_cast` returns NULL instead of raising an error on
  failure, so `-`, `**` and `2,500-` become NULL, which you can then **count** instead of crashing on.
- `250,000+` therefore becomes 250000, and a separate column records that it was top-coded:
  `coalesce(i.B19013_001E LIKE '%+', false) AS income_top_coded`. The value is "at least $250,000", so the number is a
  floor; the flag lets analyses treat it separately. `-` (no estimate exists) stays NULL: a true missing value.
- `right(GEO_ID, 5)` extracts the ZIP. `BETWEEN '90001' AND '96162'` compares **strings**, which works because ZIPs are
  fixed-width and zero-padded, so alphabetical order equals numeric order. (Hawaii's 967-969 sit outside the range,
  which is why a "starts with 90 to 96" filter would be wrong.)
- The three tables join on `GEO_ID`; the label row is excluded with `WHERE p.GEO_ID <> 'Geography'`.

`acs_missing` records how many values became NULL after coercion (out of 1,802): population 0; income 213; income margin
230; age 61; age margin 61.

### 7.2 Reference data (`build_reference`)

- `gazetteer`: land area (`ALAND_SQMI`) and centroid, read with a tab delimiter.
- `zcta_county` picks **one county per ZIP** with the same window pattern as the dedupe:

```sql
QUALIFY row_number() OVER (
    PARTITION BY GEOID_ZCTA5_20
    ORDER BY try_cast(AREALAND_PART AS BIGINT) DESC, GEOID_COUNTY_20
) = 1
```

  `AREALAND_PART` arrives as text (everything is loaded with `all_varchar`), so it is cast to a number before sorting;
  as text, `"9"` would sort after `"10000"`.

  The county with the largest land overlap wins. It is an approximation: ZIP 94515 (Calistoga's ZIP) is assigned to Sonoma
  County because more of its land lies there. County is used **only** to build cross-validation groups, so a small
  misassignment here does not touch any outlet count.

### 7.3 Joining and the population floor (`build_acs_clean`, `build_zip_base`)

```sql
-- acs_ca: ACS rows plus area, centroid and county (LEFT JOINs on zip5)
-- acs_clean: acs_ca WHERE population >= 1000
```

- Why a floor: outlets per 1,000 residents explodes when population is tiny (one store in a 300-person ZIP is 3.3 per
  1,000). The 383 ZIPs below 1,000 have a median population of 269 (maximum 998) and hold only **1,030 of 70,402
  outlets (1.5%)**, though they are 21% of ZIPs. They are set aside, not forgotten: the reconciliation below counts them.
- `zip_outlets` counts outlets per ZIP with **conditional aggregation**: `count(*) FILTER (WHERE channel = 'OFF_SALE')`
  and the same for `ON_SALE_CORE`, in one pass. Because `clean_outlets` has one row per (outlet, channel), `count(*)`
  per channel *is* the outlet count.
- `zip_base` = `acs_clean LEFT JOIN zip_outlets`, with `coalesce(outlets_off, 0)`. **The Census ZIP list is on the left,
  so ZIPs with no outlets survive as real zeros (31 ZIPs).** Starting from the ABC side instead would silently delete
  every zero-outlet ZIP and bias every density upward.

### 7.4 Join quality in both directions (`build_join_report`)

| Direction | Question | Table | Result |
|---|---|---|---|
| ABC to Census | ABC ZIPs with no Census area | `join_misses_abc` (LEFT JOIN ... `WHERE a.zip5 IS NULL`) | 95 ZIPs, 123 outlets |
| Census to ABC | Census ZIPs with no outlets | rows of `zip_base` with zero outlets | 31 ZIPs (kept) |
| Floor | ZIPs removed | `acs_ca` minus `acs_clean` | 383 ZIPs, 1,030 outlets |

`LEFT JOIN ... WHERE right.key IS NULL` is the standard **anti-join**: "rows in A with no partner in B".

**The reconciliation identity** (check 6 in query 07): every outlet is in exactly one bucket.

```
123 (no Census match) + 1,030 (below floor) + 69,249 (in zip_base) = 70,402 = rows in clean_outlets
```

The ZIP/ZCTA mismatch has a concrete example: UC Irvine's own mailing ZIP, 92697, has 5 licensed on-sale outlets but no
Census area (a join miss), while the 24,017 residents nearby are counted in ZIP 92617, which shows zero off-sale outlets.
The residents and the businesses sit in different ZIPs.

---

## 8. Phase 3: the master feature table

File: [`src/build_features.py`](../src/build_features.py). One SQL statement with three CTEs (`base`, `fences`, `scored`)
builds `zip_features`, one row per ZIP.

### 8.1 Formulas

| Column | Formula | Notes |
|---|---|---|
| `outlets_off`, `outlets_on_core` | counts from `zip_base` | |
| `off_per_1k`, `on_per_1k` | `outlets * 1000.0 / population` | `1000.0` forces floating-point division |
| `on_share` | `on / nullif(on + off, 0)` | `nullif(x, 0)` returns NULL instead of dividing by zero: undefined for the 31 zero-outlet ZIPs |
| `pop_density` | `population / nullif(land_sqmi, 0)` | people per square mile |
| `log_population`, `log_income`, `log_pop_density` | `ln(...)` | these quantities are right-skewed; logs make relationships closer to linear and spread more even |
| `log1p_off_per_1k`, `log1p_on_per_1k` | `ln(1 + x)` | `log1p` because densities contain exact zeros and `ln(0)` is undefined |
| `city` | `mode(Prem City)` among the ZIP's outlets, from `zip_city` | a **label only**: free text, never a join key |

Expected NULLs: `median_income` and `log_income` for 28 ZIPs (no estimate); `on_share` and `city` for 31 (no outlets).
`SUMMARIZE zip_features` prints per-column type and null percentage.

### 8.2 The visitor-heavy flag

Per-resident ratios are misleading where non-residents buy: tourists, travelers on an interstate, daytime workers
downtown. The flag marks those ZIPs so models do not learn from them blindly.

```
fence = Q3 + 3 x (Q3 - Q1)      computed on ln(1 + density), separately for off-sale and on-sale
visitor_heavy_rule = off-sale density above its fence  OR  on-sale density above its fence
```

- This is **Tukey's fence**: the interquartile range (IQR = Q3 - Q1) measures typical spread; points more than 1.5 IQR
  beyond the quartiles are "unusual", more than 3 IQR are "far out". On the original scale the 3-IQR fences are 4.02
  off-sale and 14.05 on-sale outlets per 1,000. With k = 1.5 they would be 2.17 and 5.33, flagging 116 ZIPs (8%): too many.
- `quantile_cont(x, 0.25)` is DuckDB's interpolated percentile. `CROSS JOIN fences` attaches the one-row threshold table to
  every ZIP.
- Result: **26 ZIPs by rule.** Reading the list shows three groups: destinations (St. Helena, Calistoga, Carmel, Big Sur,
  Healdsburg), highway stops (Buttonwillow, Kettleman City, Lost Hills, Westley) and downtowns (San Jose 95113, San
  Francisco 94111, Sacramento 95814). The common thread is *non-resident demand*.
- `visitor_heavy_manual`: two ZIPs added by hand, **94558 and 94559 (Napa city)**, *after* the first model run showed them
  with the largest residuals. `visitor_heavy = rule OR manual` (28 ZIPs). Both columns are kept so the write-up can say
  exactly what was added and when. This is a "forking path": adjusting a rule after seeing outcomes can flatter results,
  so the robustness check trains once with and once without the flagged ZIPs (it makes no difference).
- Caveat: the flag is defined using the outcome (density), so it is partly circular; flagged ZIPs are **marked, never
  deleted**.

---

## 9. Phase 4: the SQL analysis layer

[`queries/`](../queries) holds seven documented questions; [`src/run_queries.py`](../src/run_queries.py) runs each file,
saves the result as `outputs/tables/<name>.csv`, and exits with an error if any sanity check (query 07) fails. Each file's
header comment states the question, source, technique and caveats.

| Query | Question | Technique to learn | Result in one line |
|---|---|---|---|
| `01_outlets_per_zip_by_channel` | outlets per ZIP and channel | conditional aggregation (`FILTER`) | 1,766 ZIPs, including those later dropped |
| `02_top_bottom_zips_by_density` | highest and lowest 20 ZIPs | CTE + two `row_number()` windows | "lowest" breaks zero ties by population, showing the largest ZIPs with no off-sale outlet |
| `03_county_rollup_with_rank` | 58 counties compared | CTE + `rank()`; **pooled** ratios | Napa highest (3.65 per 1,000), Santa Clara lowest (0.47) |
| `04_on_sale_share_by_county` | mix tilted to bars or stores | two CTEs; the second applies `sum(...) OVER ()` across the county rows to get the statewide share | San Francisco 79% on-sale vs 62% statewide; Napa lowest at 36% |
| `05_income_quintile_summary` | density by income fifth | `ntile(5) OVER (ORDER BY median_income, zip5)` | off-sale 0.85 to 0.52, on-sale 0.94 to 1.37 per 1,000 |
| `06_issue_year_cohorts` | when today's licenses were issued | running total with a partitioned window; **survivorship warning** | an age profile of surviving outlets, not growth |
| `07_sanity_checks` | does the pipeline reconcile | one `UNION ALL` of boolean checks | 8 of 8 pass |

Ideas worth internalizing:

- **Pooled versus averaged ratios.** County density is `sum(outlets) / sum(population)`, not the average of ZIP ratios; the
  average would let a 1,000-person ZIP count as much as a 50,000-person one.
- **`ntile(5)`** cuts rows into five equal-sized groups after sorting; the added `zip5` in `ORDER BY` breaks ties
  (for example the 12 ZIPs top-coded at 250,000) so the result is repeatable on any machine.
- **Query 06's warning is part of the deliverable.** The file contains only licenses alive today, so older years look
  quieter than they were, and an issue date is not an opening date (transfers can reset it).
- **Query 07's checks:** no duplicate ZIPs; no duplicate (file number, channel); only the two retail channels; every ZIP
  five digits; ZIP-level outlet sums match `clean_outlets`; the three-bucket reconciliation; no ZIP under the floor;
  densities never NULL or negative.
- `run_queries.py` is deliberately tiny: `con.sql(text).df()` runs a query into a pandas DataFrame, `df.to_csv(...)`
  saves it. Because the runner fails loudly, a broken pipeline cannot quietly publish results.

---

## 10. Phase 5: K-means archetypes and PCA

File: [`src/cluster.py`](../src/cluster.py). **Goal:** group ZIPs into a few interpretable market types.

### 10.1 What gets clustered

`load()` assigns every ZIP a `status`:

| Status | Rule | ZIPs |
|---|---|---|
| `clustered` | has all six features and is not visitor-heavy | 1,348 |
| `missing_features` | any feature NULL (no income, or no outlets so no `on_share`) | 43 |
| `visitor_heavy` | flagged (kept out of the fit so extreme points do not drag the centers) | 28 |

Visitor-heavy ZIPs still get a `nearest_cluster` (which archetype they most resemble) for context. Most land nearest
cluster 2 (sparse, older towns), which fits.

### 10.2 The six features, and why each is there

| Feature | Why |
|---|---|
| `log1p_off_per_1k` | store density; log tames the long right tail |
| `log1p_on_per_1k` | bar/restaurant density; same transform |
| `on_share` | the retail *mix*: on-sale as a share of all outlets |
| `log_income` | affluence; income is right-skewed |
| `median_age` | age profile |
| `log_pop_density` | urban versus rural character |

**Standardization** (`StandardScaler`): each feature becomes `z = (x - mean) / sd`, mean 0 and standard deviation 1.
K-means uses straight-line (Euclidean) distance, so a feature measured in dollars would otherwise swamp one measured in
fractions. Scaling is effectively *choosing the weights* of the features, and here every feature gets equal weight.

### 10.3 How K-means works

1. Pick `k` starting centers (scikit-learn's default, k-means++, spreads them out).
2. Assign every point to its nearest center.
3. Move each center to the mean of its assigned points.
4. Repeat 2 and 3 until nothing changes.

**Inertia** is the sum of squared distances from each point to its assigned center; the algorithm only ever lowers it. It
finds a *local* optimum, so results depend on the starting centers: `n_init` restarts keep the best run, and
`random_state=42` makes the whole thing repeatable. Inertia always falls as `k` grows (more centers fit better), so on its
own it cannot choose `k`.

### 10.4 Choosing k with three lenses

`scan()` runs k = 2 to 10. Table: `outputs/tables/cluster_selection.csv`; figure: `05_k_selection.png`.

| k | Inertia | Silhouette | Stability: random starts | Stability: 80% subsamples |
|---|---|---|---|---|
| 2 | 6,194 | **0.281** | 1.00 | 0.74 |
| 3 | 4,833 | 0.249 | 1.00 | **0.98** |
| 4 | 4,289 | 0.210 | 0.98 | 0.76 |
| **5** | 3,808 | 0.207 | 0.99 | 0.93 |
| 6 | 3,550 | 0.207 | 0.96 | 0.92 |
| 7 | 3,353 | 0.171 | 0.71 | 0.61 |
| 8-10 | 3,171-2,863 | 0.17-0.18 | 0.62-0.68 | 0.63-0.67 |

- **Elbow (inertia).** Look for where adding a cluster stops helping much. Here the curve bends gradually between 4 and
  6: no sharp elbow.
- **Silhouette.** For each point, `a` = average distance to its own cluster, `b` = average distance to the nearest other
  cluster, `s = (b - a) / max(a, b)`, from -1 to 1. The mean over all points scores the clustering. Rule of thumb: above
  0.5 is strong structure, 0.25 to 0.5 weak, below 0.25 essentially none. **All of ours are 0.17 to 0.28: weak, and below 0.25 for every k above 3.** The data
  form a continuum, and the PCA picture shows overlapping clouds, not islands. This is the most important honest finding
  about the archetypes.
- **Stability**, measured with the **Adjusted Rand Index (ARI)**: given two groupings of the same points, count pairs of
  points that are together in both or apart in both, subtract the agreement expected by chance, and rescale so 1 means
  identical and about 0 means random. ARI ignores what the clusters are *called*, so it compares groupings fairly. Two
  tests: (a) fit 10 times with different random starts and average the pairwise ARI; (b) fit on random 80% subsamples
  (20 times), use each fit to label *all* ZIPs, and compare with the full-data labels.
- **Reading it.** Everything is stable up to k = 6 and collapses at 7 and beyond. Within that range, k = 3, 5 and 6 are
  the stable ones (subsample ARI 0.98, 0.93, 0.92); 2 and 4 are not. k = 5 is a judgment call: more detail than 3, stable,
  and it yields interpretable groups. The constant `CHOSEN_K = 5` is the only thing to change if you disagree.

### 10.5 The final fit and the profiles

- Final fit: `KMeans(5, n_init=50, random_state=42)`. **Clusters are renumbered 1 to 5 from lowest to highest median
  income**, so numbering (and each cluster's chart color) is stable and meaningful instead of arbitrary.
- **Profiles in original units** (medians of ZIP values, so the table reads in dollars and people per square mile, not
  standardized units), plus the five ZIPs nearest each center as "typical" examples.

| # | Draft name | ZIPs | Income | Age | Density /sq mi | Off /1k | On /1k | On share |
|---|---|---|---|---|---|---|---|---|
| 1 | Lower-income, low-density, store-heavy | 215 | $67k | 36 | 92 | 1.07 | 0.60 | 33% |
| 2 | Sparse, older towns rich in bars and restaurants | 160 | $80k | 52 | 45 | 1.45 | 2.32 | 63% |
| 3 | Dense, middle-income, few outlets per resident | 370 | $83k | 36 | 5,431 | 0.59 | 0.52 | 45% |
| 4 | Higher-income, dense, bar-and-restaurant scene | 231 | $105k | 39 | 6,243 | 0.79 | 2.38 | 75% |
| 5 | Affluent suburbs, few outlets of either kind | 372 | $137k | 43 | 2,529 | 0.45 | 0.88 | 66% |

The largest ZIPs in each cluster help check the names. Cluster 2: Palm Springs, Paso Robles, South Lake Tahoe, Palm Desert,
Sonoma, which are resort and retirement towns (several never tripped the visitor-heavy flag, so the cluster is picking up
that pattern anyway). Cluster 1: Tulare, Bakersfield, Merced, Turlock, Porterville, which are Central Valley cities, not
remote countryside; their ZIPs are large in area, hence the low density.

The names live in `CLUSTER_NAMES` in `cluster.py` and are **interpretations**; they describe `k = 5` and must be rewritten
if `CHOSEN_K` changes. One lesson from naming: "rural" was too strong for cluster 1 (median 92 per square mile, but it holds
Stockton's 95215, a big low-density ZIP at a city's edge); the data defines the cluster as lower-income and store-heavy.

### 10.6 PCA, and reading the axes

**Principal component analysis** rotates the standardized features into new, uncorrelated axes ordered by how much
variance they capture. The first two axes (PC1 about 35%, PC2 about 32% of the variance) give a 2-D picture of six
dimensions; the third (about 16%) is not shown.

A **loading** is the weight of a feature in an axis. Large positive or negative weights say what the axis is about:

| Feature | PC1 | PC2 |
|---|---|---|
| `on_share` | **+0.59** | +0.22 |
| `log_income` | **+0.52** | -0.09 |
| `log_pop_density` | +0.36 | **-0.41** |
| `log1p_off_per_1k` | **-0.36** | **+0.51** |
| `log1p_on_per_1k` | +0.30 | **+0.56** |
| `median_age` | +0.17 | **+0.45** |

- **PC1 = income and retail mix**: left is lower income and store-dominated, right is higher income and
  bar/restaurant-dominated.
- **PC2 = outlets per resident, age and density**: top is sparse, older and outlet-rich; bottom is dense, younger and
  few outlets. Income barely matters on this axis, so the two axes tell different stories.
- **Sign ambiguity.** An axis can flip direction without changing the math (`v` and `-v` span the same line). So
  `oriented_pca()` pins the signs (PC1 rises with income, PC2 with on-sale density); otherwise the words on the chart could
  silently become wrong after a rerun. These words are in `AXIS_WORDS`.
- Axis names are interpretations of the weights; PC2 mixes three things and also partly reflects small-population noise.

### 10.7 Caveats

Weak separation (silhouette about 0.21). Membership moves with settings (agreement with the main clusters is 0.67 at k = 4,
0.82 at k = 6, 0.70 without `on_share`, 0.49 with only outlet and density features). The archetypes are built partly from the
very densities the model later predicts, so "residual by archetype" is descriptive, not independent evidence.

---

## 11. Phase 6: prediction and honest validation

File: [`src/model.py`](../src/model.py). **Goal:** predict off-sale outlets per 1,000 residents from demographics, and
measure how well that works on places the model has never seen.

### 11.1 Target, predictors, and what is deliberately excluded

- **Target:** `off_per_1k`, but models train on `log1p(off_per_1k)` (the density is right-skewed with a spike at zero, see
  figure `08_density_distribution.png`). Predictions are back-transformed with `expm1` and clipped at 0, and **all scores are
  computed on the original scale** (outlets per 1,000 residents), because that is what a reader can interpret.
- **Predictors:** `log_population`, `log_income`, `median_age`, `log_pop_density`: demographics only.
- **Excluded on purpose:** anything derived from the target (`on_share` contains the off-sale count: leakage), the
  other channel's density, and race and ethnicity (ethics: this is a public-health topic and modeling siting on racial
  composition is fraught).

### 11.2 Why grouped cross-validation

Ordinary K-fold shuffles ZIPs into folds at random, so a test ZIP's neighbors (similar income, similar rules, similar
shop mix) sit in the training set. The model then looks better than it would on a genuinely new region: **leakage through
spatial similarity**. `GroupKFold(n_splits=5, shuffle=True, random_state=42)` with `groups = county` puts all ZIPs of a
county in the same fold, so every test ZIP belongs to a county the model never trained on.

- Each fold tests on 11 to 12 whole counties. Folds are uneven (161 to 454 ZIPs) because Los Angeles County alone has
  hundreds of ZIPs.
- Honest limit: ZIPs just across a county line still resemble their neighbors; there is no spatial blocking.
- County is assigned from the relationship file (largest overlap), used only for grouping.

### 11.3 No leakage inside the folds

Every model is a scikit-learn `Pipeline`: median imputation (28 ZIPs lack income) then, for linear regression, scaling,
then the model. Fitting a pipeline on training rows learns the imputation median **from training rows only**, then applies
it to the test fold. Imputing on the whole dataset first would leak test information into training.

**Tuning is nested.** For the forest and gradient boosting, `GridSearchCV` runs an *inner* `GroupKFold(3)` on the
training counties to pick hyperparameters (scored by RMSE on the log scale); the winner is refit on all training rows, and
only then scored once on the outer test fold. Because the test fold never influences tuning, the reported scores are not
inflated by hyperparameter search.

| Model | Detail |
|---|---|
| `baseline_mean` | predicts the training mean of the log target for every ZIP; the floor any model must beat |
| `linear_regression` | median impute, standardize, ordinary least squares |
| `random_forest` | 300 trees; grid over `min_samples_leaf` (3, 10, 25) and `max_depth` (6, none) |
| `hist_gradient_boosting` | 200 iterations; grid over learning rate (0.03, 0.1) and `min_samples_leaf` (10, 30) |

### 11.4 Metrics

On the original scale, on each fold's held-out normal (non-flagged) ZIPs: **MAE** (mean absolute error, in outlets per
1,000), **RMSE** (root mean squared error; punishes big misses more), and **R²** = `1 - SS_residual / SS_total`, with the total
variation taken around the test fold's own mean. R² is 1 for perfect prediction and 0 for "no better than predicting that
fold's average"; it can be **negative** when a prediction is worse than that. The baseline is slightly negative because the
*training* mean differs from each *test* fold's mean.

### 11.5 Results (`outputs/tables/model_results.csv`)

Held-out counties, normal ZIPs, mean and standard deviation over 5 folds:

| Model | R² | MAE | RMSE |
|---|---|---|---|
| Training mean | -0.062 +/- 0.082 | 0.425 | 0.636 |
| Linear regression | **0.287 +/- 0.044** | 0.349 | 0.520 |
| Random forest | 0.283 +/- 0.064 | 0.346 | 0.522 |
| Gradient boosting | 0.259 +/- 0.071 | 0.353 | 0.530 |

Training once *with* the flagged ZIPs (the same function, `train_on_flagged=True`): linear 0.305, forest 0.292, boosting
0.250: the same ranking and the same story.

### 11.6 Why a forest cannot beat a line here

Model *capacity* (how complicated a pattern it can fit) is not the same as *information* (how much signal the features
carry). With four features and about 1,350 rows, the signal that exists is smooth and roughly monotone in the log features,
which a line already captures. The remaining 70% of variation comes from things absent from the data (visitors, local rules,
store format, small-count noise). More flexible models mostly fit noise: the spread across folds (0.04 to 0.07) is larger
than any gap between models. In bias-variance terms, the error is dominated by **irreducible error**, which no model
choice can remove. The practical consequence: spend effort on features and data, not on bigger models (section 11.9).

### 11.7 Permutation importance (`06_permutation_importance.png`)

For one fitted forest and one held-out test fold: shuffle a single feature's column (destroying its relationship with the
target), re-score, and record the **drop in R²** (log scale); 20 shuffles per feature per fold, then averaged over folds.
Because it is computed on **held-out** rows, it measures what the model *uses to predict new places*, not what it memorized.

| Feature | Mean drop in R² |
|---|---|
| population density (log) | 0.231 |
| median income (log) | 0.201 |
| median age | 0.066 |
| population (log) | 0.064 |

Cautions: importance is predictive use, not cause; correlated features (density and income both track "how urban") can
share or trade credit. A drop-one test on the *linear* model shows the ranking can flip: removing income costs 0.082 R²
(0.287 to 0.205) while removing density costs only 0.036 (to 0.251), even though the forest ranks density first. Importance
depends on the model and on which correlated features remain. A linear model with density and income only scores 0.264.

### 11.8 Out-of-fold predictions and residuals

Every ZIP is in exactly one test fold, so it receives exactly one **out-of-fold** prediction from a model that never saw its
county. This is stored in `zip_residuals` / `oof_predictions.csv`, together with all four models' predictions and

```
residual_rf = off_per_1k (actual) - pred_random_forest
```

Positive: more off-sale outlets than demographics predict. Negative: fewer. Visitor-heavy ZIPs are *predicted* (their
county's fold) by models that never trained on any flagged ZIP at all.

### 11.9 "Would a bigger model help?" (`src/model_heavy.py`, optional)

Same folds, same training rows, same scoring. Table: `outputs/tables/model_heavy_results.csv`.

| Model | R² | MAE | Time per fold |
|---|---|---|---|
| Linear regression (reference) | 0.287 +/- 0.044 | 0.349 | 0.01 s |
| Random forest, 1,000 trees, 16-point grid | 0.306 +/- 0.048 | 0.343 | 13.5 s |
| Extra-trees, 1,000 trees | 0.290 +/- 0.055 | 0.344 | 5.6 s |
| Gradient boosting, 24-point grid | 0.260 +/- 0.070 | 0.352 | 9.0 s |
| Poisson count model | -0.069 +/- 0.202 | 0.415 | 0.08 s |

- The best is +0.02 R² over a straight line, inside the fold-to-fold spread, at roughly 1,000 times the compute (and it is
  the best of five tried on the same folds, so even that is slightly optimistic). The entire experiment takes about three
  minutes, so compute was never the constraint.
- A bigger tuning grid made boosting *worse*: more knobs, more ways to overfit the inner folds.
- **The Poisson row is not a fair fight.** scikit-learn's `PoissonRegressor` has no offset, so the code models the
  *rate* `r = count / population` with population as the sample weight. That is mathematically a Poisson regression with a
  `log(population)` offset: the log-likelihood of count `y` with mean `mu = pop * exp(eta)` is
  `y*eta + y*log(pop) - pop*exp(eta)`, which equals `pop * (r*eta - exp(eta))` plus a constant. But the weighting makes
  the fit optimize for *big* ZIPs, while we score every ZIP equally on the per-1,000 scale, so small, high-rate ZIPs are
  under-predicted. A fair test scores on outlet counts and allows over-dispersion (negative binomial); that is add-on A5.

---

## 12. Phase 7: interpretation and robustness

File: [`src/interpret.py`](../src/interpret.py). Everything lands in `outputs/tables/07_*.csv`.

### 12.1 Ranking the surprises, two ways

A raw residual (per 1,000) is dominated by tiny ZIPs: five outlets in Pescadero's 1,465-person ZIP is 3.4 per 1,000, against 0.75
predicted. The cure is to ask how surprising the **count** is. Under a Poisson model, variance equals the mean, so

```
expected = max(predicted_rate x population / 1000, 0.1)
z = (actual_count - expected) / sqrt(expected)
```

If counts were pure Poisson noise around the model, `z` would have standard deviation about 1. Observed (normal ZIPs):

| Population | sd of per-1,000 residual | sd of z |
|---|---|---|
| under 3k | 1.01 | 1.21 |
| 3k to 10k | 0.65 | 1.59 |
| 10k to 30k | 0.33 | 1.74 |
| over 30k | 0.24 | 2.01 |

Small ZIPs: the residual spread is large, but `z` is near 1, so it is mostly count noise. Large ZIPs: `z` is about 2,
meaning real structure the model misses (**over-dispersion**). So the **leads worth investigating are among the larger
ZIPs, ranked by z**. By z: San Francisco's Mission (94110) and neighbors, Sonoma County towns, Monterey, Capitola, Santa
Barbara above expectation; Clovis, Fontana, Moreno Valley, Lancaster, Merced and parts of South Los Angeles below. By raw
residual: wine-country, resort and travel-stop ZIPs above, tiny zero-outlet ZIPs below (11 of the 15 lowest have no outlets
at all). `07_top_residuals.csv` holds both rankings (15 over and 15 under each).

### 12.2 Residuals by archetype (`07_residuals_by_archetype.csv`)

| Archetype | Mean residual | % over-predicted |
|---|---|---|
| 2: sparse, older towns | **+0.46** | 73% |
| 4: higher-income, dense, bars | +0.22 | 77% |
| 1: lower-income, low-density | +0.16 | 59% |
| 3: dense, middle-income | -0.07 | 33% |
| 5: affluent suburbs | -0.13 | 29% |

Circularity warning: clusters are built from the densities being predicted, so a link between cluster and residual is
partly built in. Descriptive, not independent evidence.

### 12.3 The Stockton check (a permutation-style test)

Hypothesis (yours): Stockton's strict alcohol ordinance makes its outlet counts lower than demographics predict.
Test: Stockton has 11 ZIPs with mean residual -0.044. Draw 20,000 random sets of 11 ZIPs from the *same archetype
outside Stockton* and ask how often a random set's mean is at or below Stockton's. Answer: **66% of the time**, so
Stockton looks completely typical. This builds the reference distribution empirically instead of assuming a formula.
Limits: one city, low power, and regulation may already be absorbed into income and density. `07_city_residuals.csv` lists
cities with 8 or more ZIPs (Irvine lowest at -0.17; Santa Barbara and San Francisco highest at +0.28 and +0.27).

### 12.4 The robustness suite (`07_robustness.csv`, 14 of 14 pass)

Each *finding* is re-tested under a change. Pass criteria are explicit and deliberately plain:

| Finding | Passes if | Variants tested |
|---|---|---|
| F1: higher-income ZIPs have fewer stores and more bars per resident | off-sale density in the top income quintile is below the bottom's, and on-sale is above | floor 500, 1,000, 2,000; flagged ZIPs removed |
| F2: demographics explain about 30%; forest is not better | linear R² between 0.20 and 0.40 and forest minus linear below 0.03 | floor 500, 1,000, 2,000 |
| F3: density and income carry the signal | density+income-only linear R² within 0.03 of all four | density+income only; without population; without age |
| F4: sparse, older towns are the most over-served archetype | the top-residual cluster has median density under 150 per sq mi and median age over 45 | k = 4; k = 6; without `on_share`; outlet and density features only |

How it is built (worth reading as a design pattern):

- **Floor variants** copy the database file to a temporary directory, set the module variable
  `ingest_acs.POP_FLOOR`, call `build_acs_clean`, `build_zip_base` and `build_features.build_zip_features` on the copy,
  then restore the original value in a `finally` block. The real database is never touched.
- `quick_cv()` re-runs the grouped CV with just the linear model and the forest.
- The cluster variants refit K-means and report the ARI against the main clusters (0.49 to 0.82).

Honesty about the suite: these criteria are directional and lenient. The softer message is that the *boundaries* of the
archetypes move between settings even when the headline pattern holds.

---

## 13. Phase 8: figures and the chart rules behind them

Files: [`src/figures.py`](../src/figures.py) for the three `08_*` figures; `cluster.py` and `model.py` make `05_*` and
`06_*`. The shared look (fonts, colors, `style_axes`) is defined once in `cluster.py` and imported, so restyling is a
one-place change.

**Rules applied** (a chart procedure: choose the form, assign color by the job it does, validate, then mark specs):

- **One y-axis per chart.** Never two scales on one plot; the k-selection figure is three small panels instead.
- **Categorical hues in a fixed order, tied to the entity**: cluster 1 is always blue, cluster 2 orange, and so on, so a
  color means the same thing in every figure.
- **The palette was validated with a script**, not by eye: neighboring colors must stay separable under color-vision
  deficiency (OKLab distance of at least 8) and for normal vision (at least 15). Past three colored groups in a *scatter*
  the pairwise separation fails, so the PCA figure uses **small multiples**: one panel per cluster, that cluster in color
  and the rest in gray.
- **Text never wears a data color**; labels use ink tones. Direct labels are selective, never a number on every point.
- **Marks:** 2-pixel lines, dots at least 8 pixels with a 2-pixel ring in the background color so overlapping dots stay
  legible, hairline solid gridlines.
- **Diverging** data (residuals) uses two opposite hues, blue and red, with a neutral gray midpoint.
- Every figure has a **table twin** in `outputs/tables/` (the data behind it), because color alone is not a complete
  encoding.

| Figure | Built by | What to look for |
|---|---|---|
| `05_k_selection.png` | `cluster.plot_selection` | inertia, silhouette and stability side by side; the vertical line is the chosen k |
| `05_pca_clusters.png` | `cluster.plot_clusters` | five panels in the same 2-D space; the axes are named in words (drawn arrows, because the font lacked arrow glyphs and they rendered as empty boxes) |
| `06_permutation_importance.png` | `model.plot_importance` | density and income dominate; whiskers are +/- 1 sd across folds |
| `08_density_distribution.png` | `figures.plot_density_distribution` | the raw density is right-skewed with a spike at zero; the log scale tames it |
| `08_predicted_vs_actual.png` | `figures.plot_predicted_vs_actual` | wide scatter around the diagonal (R² about 0.28); the black decile line stays near the diagonal, so average predictions are well calibrated; flagged ZIPs sit far above |
| `08_residual_map.png` | `figures.plot_residual_map` | red = more outlets than predicted; triangles are visitor-heavy ZIPs, clustered in wine country |

Details that matter when reading them: the predicted-vs-actual x-axis is cut at about 2.4 because the model never predicts
above about 2.2 (shrinkage toward the mean), and 4 flagged ZIPs above 6 are off the chart (stated in the footnote). The map
saturates colors at plus or minus 2 and uses an aspect ratio of `1 / cos(37.5 degrees)` so a degree of longitude is not drawn
as wide as a degree of latitude.

---

## 14. Phase 9: reproducibility, packaging, privacy

### 14.1 The one-command rebuild

[`run_all.py`](../run_all.py) checks that the seven required input files exist (and says which are missing), runs `pytest`,
then runs each `src/` script with `subprocess.run([sys.executable, script], check=True)`:

- `sys.executable` is the interpreter running `run_all.py`, so every step uses the same virtual environment.
- `check=True` stops at the first failure with its traceback; later steps never run on bad data.
- Running scripts as separate processes keeps them independently runnable (`python src/model.py` works alone).
- `--with-heavy` inserts the bigger-model experiment before the interpretation step.

### 14.2 Determinism

A reproducible result needs every source of randomness pinned.

| Source | How it is pinned |
|---|---|
| K-means starts | `random_state=42`, explicit `n_init` |
| Cross-validation folds | `GroupKFold(shuffle=True, random_state=42)` |
| Forest, boosting, permutation importance | `random_state=42` |
| Subsampling and bootstraps | `np.random.default_rng(42)` |
| Ties in SQL (`ntile`, `row_number`) | full `ORDER BY` including `zip5` or `license_type` |
| `mode()` for the city label | ties could differ, but it is a label only |

**The clean-copy test.** To prove "a fresh clone reproduces the results": copy only the files Git would carry
(`git ls-files -co --exclude-standard`), add the raw data, delete every output, run `python run_all.py`. Result: **102
seconds**, 22 tests pass, all sanity checks pass, and 20 of 21 result tables byte-identical to the originals; the 21st
(`05_income_quintile_summary.csv`) matched except for a trailing newline that an editor had stripped.

### 14.3 Packaging

`requirements.txt` pins exact versions (duckdb 1.5.6, pandas 3.0.6, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1,
matplotlib 3.11.2, pytest 9.1.1; Python 3.13.5). `pytest.ini` has `pythonpath = src` so tests can `import ingest_abc`.

### 14.4 Privacy by design

- The raw layer (`raw_abc`) is the only place names and addresses exist, and it lives in the git-ignored database.
- `abc_std` drops the personal columns, so everything downstream is clean.
- `.gitignore` excludes `data/raw/`, `*.duckdb`, `.env`, `.venv/`, `.DS_Store`, `__pycache__/`, `.pytest_cache/`.
- Only ZIP-level aggregates are committed (`outputs/`).
- **Audit before publishing:** list every path ever committed and look for large blobs.

```bash
git log --all --name-only --format='' | sort -u
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob" && $3>1000000'
```

  Result for this repository: no raw data, no `.duckdb`, no file over 1 MB, ever. The only trace of the business-name column
  is a scratch script (`notebooks/check_lookup.py`) containing the placeholder `'NAME'`.
- Git lessons from the build: `.gitignore` only affects files Git is **not already tracking** (a `.DS_Store` had been staged
  before it was ignored; `git rm --cached` fixed it); `git restore` discards uncommitted changes, so commit first; add files
  by explicit path rather than `git add .`; the first two commits carry a mistyped email (`.comm`), which is cosmetic and
  would need a force-push to fix after pushing.

---

## 15. Concept cheat sheet

| Concept | Meaning | Where it appears here |
|---|---|---|
| **Grain** | what one row of a table represents | outlet vs license record vs ZIP (section 4) |
| **Idempotent step** | running it again gives the same result | every build uses `CREATE OR REPLACE` |
| **Left join / anti-join** | keep all left rows; `... WHERE right.key IS NULL` finds left rows with no partner | zero-outlet ZIPs; `join_misses_abc` |
| **Three-valued logic** | SQL booleans are true, false or NULL; `NOT NULL` is NULL; `x = NULL` is NULL | the `zip_ok` coalesce |
| **Window function** | computes over related rows *without collapsing them*: `row_number`, `rank`, `ntile`, `lag`, running `sum` | dedupe, county choice, quintiles, attrition |
| **Pooled vs averaged ratio** | `sum(a)/sum(b)` vs `avg(a/b)`; pooled weights by size | county densities (query 03) |
| **Log / log1p** | compress right-skewed values; `log1p(x) = ln(1+x)` allows zeros | features and the model target |
| **Standardization** | `z = (x - mean)/sd` so every feature has equal weight in distances | before K-means and the linear model |
| **Inertia** | sum of squared distances to assigned centers; always falls as k rises | k selection |
| **Silhouette** | `(b - a)/max(a, b)` per point, averaged; below 0.25 means little structure | k selection |
| **ARI** | agreement between two groupings, chance-adjusted, label-invariant (1 = identical) | stability tests |
| **PCA / loading** | rotate to uncorrelated axes by variance; a loading is a feature's weight in an axis | the PCA figure |
| **Leakage** | test information reaching training (via neighbors, preprocessing, or tuning) | grouped CV, pipelines, nested tuning |
| **Grouped CV** | whole groups (counties) are held out together | `GroupKFold` |
| **Nested CV** | tuning inside the training folds only | `GridSearchCV` inside `fit_with_tuning` |
| **Out-of-fold (OOF) prediction** | a prediction from a model that never saw that row | `zip_residuals` |
| **MAE / RMSE / R²** | mean absolute error; root mean squared error; `1 - SS_res/SS_tot` | model tables |
| **Bias-variance, irreducible error** | error splits into model flaws, model instability, and noise nothing can fix | why a forest does not beat a line |
| **Permutation importance** | drop in score when one feature is shuffled on held-out data | the importance figure |
| **Calibration** | do predictions match average outcomes? (decile line near the diagonal) | predicted-vs-actual figure |
| **Tukey fence** | `Q3 + k*IQR`; k = 1.5 unusual, 3 far out | visitor-heavy rule |
| **Poisson z, over-dispersion** | `z = (O - E)/sqrt(E)`; sd of z above 1 means more spread than count noise | ranking surprises |
| **Residual** | actual minus predicted; a lead, not a verdict | `residual_rf` |
| **Forking paths / selection effects** | analysis choices made after seeing results can flatter them | the Napa flag; best-of-five heavy models |
| **Ecological inference** | patterns across areas are not statements about individuals | findings 1 and 4 |
| **Survivorship bias** | only survivors are observed (closed outlets are missing) | query 06 |
| **Top-coding** | a reported maximum ("250,000+") hides the true value | `income_top_coded` |
| **Margin of error** | ACS values are survey estimates with uncertainty | kept, not yet propagated |
| **Exposure / offset** | counts scale with population; model the rate | the Poisson experiment |

---

## 16. SQL and DuckDB idioms used here

| Idiom | Example (file) | Notes |
|---|---|---|
| `CREATE OR REPLACE TABLE x AS SELECT ...` | every build function | idempotent |
| `read_csv(path, skip=, header=, delim=, all_varchar=)` | `ingest_*.py` | be explicit; do not trust the sniffer |
| `LEFT JOIN ... USING (col)` | `abc_labeled` | keeps all left rows; NULL where unmatched |
| `coalesce(x, default)` | `'UNMAPPED'`, zero-filled counts, `zip_ok` | first non-NULL |
| `NULLIF(x, '')` | `build_std` | empty string to NULL; also `nullif(x, 0)` to avoid dividing by zero |
| `trim`, `lpad`, `left`, `right` | `build_std`, `right(GEO_ID, 5)` | string cleanup and slicing |
| `strptime(text, '%d-%b-%Y')::DATE` | `build_std` | parse a text date; `::DATE` is a cast |
| `try_cast(x AS DOUBLE)` | `to_num` | NULL instead of an error |
| `regexp_matches(text, pattern)` | `zip_ok` | partial match unless anchored with `^...$` |
| `count(*) FILTER (WHERE cond)` | `zip_outlets`, robustness | conditional aggregation in one pass |
| `row_number() OVER (PARTITION BY g ORDER BY k)` + `QUALIFY ... = 1` | dedupe, county pick | one best row per group |
| `rank()`, `ntile(n)`, `lag(x)` | queries 03, 05; attrition | league tables, equal-size buckets, previous row |
| `sum(x) OVER ()`, `sum(x) OVER (PARTITION BY g ORDER BY t)` | queries 04, 06 | statewide total beside each row; running totals |
| `WITH name AS (...)` | queries 02 to 07 | name an intermediate result (a CTE) |
| `UNION ALL` of one-row selects | `join_report`, query 07 | build a small table from several queries |
| `quantile_cont(x, p)`, `median(x)`, `mode(x)` | fences, profiles, city label | interpolated percentile; most frequent value |
| `CROSS JOIN` | attaching the one-row `fences` table | every row paired with every row |
| `(VALUES (1.5), (2.0)) AS t(k)` | exercise 4 | an inline table |
| `SUMMARIZE t`, `DESCRIBE t`, `SHOW TABLES` | exploration | quick profiling |

**Gotchas met along the way:** a column alias can collide with a reserved word (`types`, `rule` both raised parser
errors; rename the alias); blanks in this data are spaces, not NULL; a regex on NULL returns NULL; text sorts
alphabetically (`"9"` after `"10000"`), so cast before sorting numbers; ties in `ntile`/`row_number` need a full `ORDER BY`
to be repeatable.

---

## 17. Python, pandas and scikit-learn patterns used here

| Pattern | Where | Why |
|---|---|---|
| `if __name__ == "__main__":` | every `src/` script | importable without running (tests and `interpret.py` import functions) |
| Pass the connection in (`build_clean(con)`) | `ingest_*.py` | lets tests use an in-memory database |
| Build SQL with f-strings; double the braces for regex `{{5}}` | `build_clean`, `to_num` | one source of truth for constants; safe here only because the inputs are constants |
| `con.sql(query).df()` / `.show()` / `.fetchone()` | everywhere | DuckDB result to pandas / print / one tuple |
| `df.groupby(...).agg(name=(col, func))` | profiles, `interpret.py` | named aggregations |
| `Pipeline([imputer, scaler, model])` | `model.py` | preprocessing fitted on training rows only |
| `GridSearchCV(..., cv=GroupKFold(3)).fit(X, y, groups=g)` | `fit_with_tuning` | tuning with groups passed to the splitter |
| `GroupKFold(shuffle=True, random_state=42)` | `model.py`, `interpret.py` | repeatable grouped folds |
| `random_state` everywhere | all models | repeatable randomness |
| Module-level constants as knobs | `POP_FLOOR`, `CHOSEN_K`, `FENCE_K`, `CHANNELS_KEPT` | one place to change a decision |
| Temporarily override a module global, then restore in `finally` | `floor_variant` | rerun a pipeline with a different setting without editing files |
| `matplotlib.use("Agg")` | all plotting | render to files without a display |
| `subprocess.run([sys.executable, script], check=True)` | `run_all.py` | same interpreter, stop on failure |
| Fixtures and `@pytest.mark.parametrize` | `tests/` | shared setup; one test body over many inputs |

---

## 18. Decision log

| # | Decision | Alternatives considered | Chosen, and why | Where |
|---|---|---|---|---|
| 1 | What counts as an outlet | every record; distinct file number; master flag | distinct (file number, channel): matches the density definitions and keeps both channels of mixed premises | `build_clean` |
| 2 | Channels kept | include seasonal/special on-sale (1,149 more records), clubs, producers | off-sale and on-sale core only; the rest is a different business | `CHANNELS_KEPT` |
| 3 | License status | include pending | ACTIVE issued licenses only | `FILTERS` |
| 4 | Population floor | none; 500; 2,000 | 1,000; the others tested and the findings survive | `POP_FLOOR` |
| 5 | Top-coded income | NULL; drop those ZIPs | keep at 250000 plus a flag (a floor, not a typo) | `to_num`, `income_top_coded` |
| 6 | Missing income (28 ZIPs) | drop the ZIPs | median-impute inside each pipeline (no leakage) | `model.make_models` |
| 7 | One county per ZIP | population-weighted; HUD crosswalk | largest land overlap (simple; only used for CV grouping) | `build_reference` |
| 8 | Visitor-heavy ZIPs | top 1%; manual list only | Tukey 3-IQR fence on log density, plus two hand-added Napa ZIPs, disclosed; flagged not deleted | `build_features.py` |
| 9 | Clustering features and k | fewer or more features; other k | six features, k = 5 (stable, interpretable); outcome features are included, so the archetype-residual link is partly circular | `cluster.py` |
| 10 | Flagged ZIPs and clustering | cluster everything | exclude from the fit, assign a nearest cluster afterwards | `cluster.load` |
| 11 | Model target | raw ratio; counts with offset | log1p of density, scored on the original scale | `model.py` |
| 12 | Validation | random K-fold; spatial blocks | 5-fold grouped by county, shuffled; spatial blocking left as an add-on | `run_cv` |
| 13 | Models | deep nets, bigger ensembles | baseline, linear, forest, boosting; bigger ones tested and not adopted | `model_heavy.py` |
| 14 | Ranking leads | raw residual only | raw residual and Poisson z, because raw is dominated by tiny ZIPs | `interpret.py` |
| 15 | Privacy | drop columns later | drop at `abc_std`; raw only in the ignored database | `build_std` |
| 16 | PCA figure form | one scatter with five colors | small multiples (the color gates fail past three groups in a scatter) | `plot_clusters` |
| 17 | Orchestration | a Makefile with dependencies | a plain `run_all.py` (portable and readable) plus a thin Makefile | `run_all.py` |

---

## 19. Things that went wrong, and what they taught

| Symptom | Cause | Lesson |
|---|---|---|
| Loader sees one column and a mangled header | line 1 of the ABC file is a banner | look at the raw text (`head`) before loading; pass `skip=1` explicitly |
| `wc -l` says 129,656, DuckDB says 129,653 | banner + header + a trailing blank line | **reconcile counts**; unexplained differences hide bugs |
| ACS columns named `column0`, `column4` | with `all_varchar`, the sniffer cannot find the header; trailing comma adds a phantom column | set `header=true`; expect junk columns |
| A "lowest density" ZIP had density 0.0 | it had exactly zero outlets (not rounding), and the city had stores in *other* ZIPs | a city is not a ZIP; zero means zero; ZIP vs ZCTA matters (92617 vs 92697) |
| 129,653 rows but 96,563 file numbers | a premises holds several licenses | the grain problem: define the unit before counting |
| `master_ind = 'Y'` gave 70,406, not 70,402 | 762 file numbers have several masters, one has none | never trust a flag you cannot explain; test it |
| Three license types unmapped (73, 76, 92) | not in the documented mapping | flag, do not drop |
| Status `SUSPEN` vs documented `SUPEND` | a third-party glossary was wrong | verify glossaries against the data |
| `.DS_Store` showed as modified despite being ignored | it was already staged | `.gitignore` only affects untracked files; `git rm --cached` |
| `ModuleNotFoundError: duckdb` under `pytest` | the shell's `pytest` was Anaconda's, not the venv's | check `which pytest`; use `python -m pytest`; activate the venv in every terminal |
| Chart axis arrows rendered as empty boxes | the font lacked the glyph | draw arrows as shapes; look at every figure |
| SQL parse errors on aliases `types` and `rule` | reserved words | rename aliases |
| "Rural" cluster contained Stockton's 95215 | the cluster is defined by income and mix, and Central Valley ZIPs are large in area | names are hypotheses; check typical members |
| Raw residual lists were all tiny ZIPs | per-capita ratios explode on small counts | rank by a count-based score (Poisson z) |
| Poisson model scored worse than the baseline | weighted by population but scored per ZIP | the objective and the metric must agree |
| 1,000-tree models gained only 0.02 R² | the limit is information, not capacity | invest in features and data |
| Quintile table differed byte-wise between runs | an editor had stripped a trailing newline (and ties were unordered) | compare content, and make ties deterministic |
| Napa residuals led to a hand-added flag | an after-the-fact rule change | disclose it; test with and without |

---

## 20. Results cheat sheet

| Fact | Value |
|---|---|
| Outlets after cleaning | 70,402 (69,249 in the 1,419 analyzed ZIPs) |
| ZIPs: Census CA / with outlets / ABC with no Census match | 1,802 / 1,766 / 95 (123 outlets) |
| Removed by floor | 383 ZIPs, 1,030 outlets |
| Zero-outlet ZIPs kept | 31 (57 ZIPs have zero off-sale) |
| Visitor-heavy | 28 (26 rule + 2 manual) |
| Clustered / missing features | 1,348 / 43 |
| Income gradient, lowest to highest fifth | off-sale 0.85 to 0.52; on-sale 0.94 to 1.37 per 1,000 |
| Linear / forest / boosting R² (held-out counties) | 0.287 / 0.283 / 0.259 |
| Best bigger model | 0.306 (1,000-tree forest) |
| Importance (drop in R²) | density 0.23, income 0.20, age 0.07, population 0.06 |
| Residual archetype extremes | cluster 2 +0.46; cluster 5 -0.13 |
| z-spread by population band | 1.21 (under 3k) to 2.01 (over 30k) |
| Stockton | mean residual -0.044; 66% of random same-size samples are lower |
| Robustness | 14 of 14 checks pass |
| Tests | 22 |
| Full rebuild | about 102 seconds |

**Index of `outputs/tables/`:**

| File | Contents |
|---|---|
| `01_outlets_per_zip_by_channel` | outlets per ZIP: off, on-core, total (all 1,766 ZIPs) |
| `02_top_bottom_zips_by_density` | 20 highest and 20 lowest ZIPs by off-sale density |
| `03_county_rollup_with_rank` | 58 counties: pooled densities and ranks |
| `04_on_sale_share_by_county` | on-sale share by county vs statewide |
| `05_income_quintile_summary` | density by income fifth |
| `06_issue_year_cohorts` | issue years of today's licenses (survivorship warning) |
| `07_sanity_checks` | the 8 reconciliation checks |
| `07_top_residuals` | 15 over and 15 under, by raw residual and by z |
| `07_residuals_by_archetype` | residual mean, median, sd, share over, mean z per archetype |
| `07_residual_spread_by_population` | sd of residual and of z by population band |
| `07_city_residuals` | mean residual for cities with 8 or more ZIPs |
| `07_stockton_check` | the Stockton comparison numbers |
| `07_robustness` | the 14 checks: finding, variant, result, pass |
| `cluster_selection` | k, inertia, silhouette, two stability scores |
| `cluster_profile` | archetype profiles, typical ZIPs, names |
| `zip_clusters` | each ZIP's cluster, status, nearest cluster |
| `pca_loadings` | PCA weights |
| `model_results`, `model_results_by_fold` | scores by run, scope and model (summary and per fold) |
| `model_heavy_results` | the bigger-model experiment |
| `oof_predictions` | every ZIP's out-of-fold predictions and residual |
| `permutation_importance_by_fold` | importance per feature per fold |

---

## 21. How to extend the project

**A. A visitor proxy (the add-on I would do first).** The biggest source of unexplained variation is non-resident
demand; Census table B25004 (vacancy status) has housing units vacant for seasonal, recreational or occasional use.
1. Download B25004 and B25001 (total housing units) for the same ZCTAs; the seasonal column is `B25004_006E` (verify in the
   table metadata); save under new names in `data/raw/acs/` and add them to `REQUIRED_FILES` in `run_all.py`.
2. In `ingest_acs.py`: load them in `build_raw_acs`; in `build_acs_parsed` join on `GEO_ID` and compute
   `seasonal_share = B25004_006E / B25001_001E` using `to_num`.
3. Carry the column through `acs_ca`, `acs_clean`, `zip_base` and `build_features.py`.
4. Add it to `PREDICTORS` and `PLAIN` in `model.py`; compare R² with `quick_cv` from `interpret.py`.
5. Check whether Napa and Tahoe residuals shrink. If so, it is a principled replacement for the hand-picked Napa ZIPs.

**B. A fair count model.** Add `statsmodels`; fit a negative-binomial GLM of `outlets_off` with `offset = log(population)`,
grouped CV by county, and score on counts (and a population-weighted per-1,000 metric) so the objective matches the metric.

**C. Include the seasonal/special on-sale channel.** Add `'ON_SALE_OTHER'` to `CHANNELS_KEPT`. Note that `zip_outlets`
only counts the two core channels, so you would also add an `outlets_on_other` column and carry it through.

**D. Track openings and closings (add-on A15).** ABC re-publishes weekly. Save each export, then compare the sets of
`file_number` between weeks to measure real openings and closures going forward, which fixes the survivorship problem.

**E. A tract-level version (A8).** `Prem Census Tract #` is in the data (for example `2032.00`). Build the 11-digit tract
code (state, county, tract) to match ACS tract tables: about 9,000 tracts instead of 1,400 ZIPs, which would help
flexible models far more than extra trees.

**F. Propagate ACS uncertainty (A10).** Sample each estimate from a normal distribution with standard deviation
`moe / 1.645`, redo the clustering and residual ranking many times, and flag ZIPs whose cluster or rank is unstable.

**Small changes.**

- New SQL question: add `queries/08_name.sql` with the standard header comment; `run_queries.py` picks it up automatically.
- New robustness check: append a dict (`finding`, `check`, `variant`, `result`, `survives`) in `interpret.robustness`.
- New figure: write a function in `figures.py` using `setup_fonts`, `style_axes` and the color tokens; call it from `main()`;
  save its data as a CSV twin.
- Change k or the names: edit `CHOSEN_K` and `CLUSTER_NAMES` in `cluster.py`, then run `python src/cluster.py`.

---

## 22. Exercises

Run these from the project root with the environment active. Answers are folded under each.

**1. (Predict, then check.)** What column types does DuckDB give the ABC file if you drop `all_varchar=true`?
```python
import duckdb
print(duckdb.sql("DESCRIBE SELECT * FROM read_csv('data/raw/abc/ABC-DailyDataExport.csv', skip=1)").fetchall()[:6])
```
<details><summary>Answer</summary>All `VARCHAR`: DuckDB's sniffer keeps leading-zero values as text today. So the option is a
guarantee rather than a rescue here. Try `pandas.read_csv` on a file with `00012` and watch it become `12`.</details>

**2. Reproduce the dedupe evidence in SQL.**
```sql
SELECT count(*) AS records, count(DISTINCT file_number) AS files,
       count(DISTINCT (file_number, channel)) AS file_channel, sum((master_ind = 'Y')::INT) AS masters
FROM abc_labeled
WHERE prem_state = 'CA' AND lic_or_app = 'LIC' AND type_status = 'ACTIVE'
  AND channel IN ('OFF_SALE', 'ON_SALE_CORE');
```
<details><summary>Answer</summary>72,464 / 69,643 / 70,402 / 70,406. The master count disagrees with the right answer
(70,402) in *both* directions across groups: some outlets have two masters, one has none.</details>

**3. What goes wrong if `zip_base` is built as `zip_outlets LEFT JOIN acs_clean` instead?**
<details><summary>Answer</summary>The 31 zero-outlet ZIPs vanish (they are not in `zip_outlets`), and ABC ZIPs with no Census match
appear with NULL demographics. Every density statistic is then biased upward.</details>

**4. How sensitive is the visitor-heavy flag to its multiplier?**
```sql
WITH s AS (SELECT zip5, ln(1+off_per_1k) lo, ln(1+on_per_1k) ln_ FROM zip_features),
q AS (SELECT quantile_cont(lo,0.25) a, quantile_cont(lo,0.75) b, quantile_cont(ln_,0.25) c, quantile_cont(ln_,0.75) d FROM s)
SELECT k, count(*) FILTER (WHERE lo > b + k*(b-a) OR ln_ > d + k*(d-c)) AS flagged
FROM s, q, (VALUES (1.5), (2.0), (3.0), (4.0)) AS t(k) GROUP BY k ORDER BY k;
```
<details><summary>Answer</summary>116 / 72 / 26 / 5 ZIPs. The choice of 3 is a judgment, which is why the model is also run with flagged ZIPs included.</details>

**5. Why is the baseline's R² negative?**
<details><summary>Answer</summary>R² measures error relative to predicting the *test* fold's own mean. The baseline predicts the
*training* mean, which differs from each test fold's mean, so it does slightly worse than that benchmark.</details>

**6. Why must the imputer be inside the pipeline instead of filling income once up front?**
<details><summary>Answer</summary>Filling with the median of all ZIPs uses test-fold values to compute the fill, leaking test
information into training. Inside the pipeline the median comes from training rows only.</details>

**7. A ZIP has 1,200 residents, expected count 1.0, actual 5. Another has 50,000 residents, expected 40, actual 60.
Which is more surprising, and which has the larger raw residual per 1,000?**
<details><summary>Answer</summary>z: first = (5-1)/1 = 4.0; second = (60-40)/sqrt(40) = 3.2. Raw residual per 1,000: first
= 4/1.2 = 3.3; second = 20/50 = 0.4. The small ZIP dominates the raw ranking; z is closer to a fair comparison, and across
ZIPs under 3,000 residents z is mostly noise anyway (sd 1.2).</details>

**8. Which ZIPs are the biggest in each archetype? Does that support the names?**
```sql
SELECT cluster, zip5, city, outlets FROM (
  SELECT c.cluster, f.zip5, f.city, f.outlets_off + f.outlets_on_core AS outlets,
         row_number() OVER (PARTITION BY c.cluster ORDER BY f.outlets_off + f.outlets_on_core DESC) AS rn
  FROM zip_features f JOIN zip_clusters c USING (zip5) WHERE c.cluster IS NOT NULL)
WHERE rn <= 5 ORDER BY cluster, rn;
```
<details><summary>Answer</summary>Cluster 1 leads with Tulare, Bakersfield, Merced, Turlock, Porterville (Central Valley cities).
Cluster 2 leads with Palm Springs, Paso Robles, South Lake Tahoe, Palm Desert, Sonoma (resort and retirement towns), which
supports its name and shows the cluster capturing tourism beyond the visitor flag.</details>

**9. How many ZIPs, other than flagged ones, have no off-sale outlet?**
```sql
SELECT count(*) FROM zip_features WHERE outlets_off = 0 AND NOT visitor_heavy;
```
<details><summary>Answer</summary>57. A model must predict a target that piles up at exactly zero, one reason a count model is attractive.</details>

**10. Which channel mix are you giving up by dropping the seasonal/special on-sale channel?**
```sql
SELECT channel, count(DISTINCT file_number) n FROM abc_labeled
WHERE prem_state='CA' AND lic_or_app='LIC' AND type_status='ACTIVE' GROUP BY 1 ORDER BY 2 DESC;
```
<details><summary>Answer</summary>`ON_SALE_OTHER` has 1,119 outlets (1,149 records), small next to 43,821 core on-sale and 26,581 off-sale outlets.
`EXCLUDE` (14,631) and `PRODUCER_RETAIL` (7,402) are larger but are not retail.</details>

**11. (Predict, then run.) Which predictor hurts the *linear* model more to remove: density or income?**
```python
import sys; sys.path.insert(0, "src")
import duckdb
from interpret import quick_cv
df = duckdb.connect("data/market_map.duckdb", read_only=True).sql("SELECT * FROM zip_features ORDER BY zip5").df()
for drop in ["log_pop_density", "log_income"]:
    keep = [c for c in ["log_population", "log_income", "median_age", "log_pop_density"] if c != drop]
    print(drop, quick_cv(df, keep, ("linear_regression",)))
```
<details><summary>Answer</summary>All four: 0.287. Without density: 0.251. Without income: 0.205. So income matters more to the
line, even though the forest's permutation importance ranked density first: the two overlap, and importance depends on the model.</details>

**12. Break it on purpose, then fix it.** In `ingest_abc.py` change `) = 1` to `) >= 1` in the `QUALIFY`; run `python -m pytest -q`;
read which tests fail and why; then restore the file (commit first, then `git restore src/ingest_abc.py`).
<details><summary>Answer</summary>The three dedupe tests that expect one row per (file number, channel) fail, because nothing is
deduplicated. A test that cannot fail proves nothing, which is why you run this experiment.</details>

**13. Why are PCA axis signs arbitrary, and what in the code protects the axis words?**
<details><summary>Answer</summary>An axis `v` and its mirror `-v` describe the same direction in space, so the algorithm may
return either. `oriented_pca()` flips the axes so PC1 correlates positively with income and PC2 with on-sale density.</details>

**14. Explain, in two sentences each, why (a) the forest does not beat the line, (b) Stockton does not look unusual, (c) the
archetype-residual table is not independent evidence.** Then compare with sections 11.6, 12.3 and 12.2.

**15. Extension.** Implement recipe A (the seasonal-housing share). Predict first: will the forest or the line gain more?
How would you know whether the gain is real and not noise? (Hint: compare against the fold-to-fold standard deviation, and
rerun the robustness suite.)

---

## 23. Glossary

| Term | Meaning |
|---|---|
| ABC | California Department of Alcoholic Beverage Control; publishes the license export |
| ACS | American Community Survey; the Census Bureau's survey behind the demographic estimates |
| Archetype | a cluster of similar ZIPs given a plain-language name |
| Channel | on-sale or off-sale grouping derived from the license type code |
| Clean outlet | one active, issued, California retail outlet in one channel, with a valid ZIP |
| County group | the unit held out together in cross-validation |
| File number | ABC's license identifier; used as the outlet identifier |
| Off-sale | sells sealed containers for consumption elsewhere (stores) |
| On-sale | sells for consumption on the premises (bars, restaurants) |
| OOF | out-of-fold: predicted by a model that did not train on that row |
| Outlet | one physical licensed premises in one channel |
| Population floor | minimum population (1,000) for a ZIP to enter the analysis |
| Raw layer | the untouched copy of the source data |
| Residual | actual minus predicted outlet density |
| Visitor-heavy | a ZIP whose outlets plausibly serve non-residents |
| ZCTA | ZIP Code Tabulation Area: the Census Bureau's area approximation of a ZIP code |
| ZIP vs ZCTA | mail-delivery area vs Census area; some ZIPs have no ZCTA |
