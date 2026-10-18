import duckdb
import pytest

import ingest_abc as ia


@pytest.fixture
def con():
    """A fresh, empty in-memory database for every test, with the real channel lookup loaded."""
    c = duckdb.connect()
    ia.build_lookup(c)
    c.sql("""
        CREATE TABLE abc_std (
            license_type VARCHAR, file_number VARCHAR, lic_or_app VARCHAR,
            type_status VARCHAR, type_orig_iss_date DATE, dup_counts VARCHAR,
            master_ind VARCHAR, prem_state VARCHAR, prem_zip VARCHAR,
            prem_county VARCHAR, prem_census_tract VARCHAR
        )
    """)
    yield c
    c.close()


@pytest.fixture
def add(con):
    """Return a function that inserts one fake license record.
    Defaults describe a valid, active, off-sale California license; override what a test cares about."""
    def _add(**overrides):
        row = dict(
            license_type="21", file_number="00000001", lic_or_app="LIC",
            type_status="ACTIVE", type_orig_iss_date="2020-01-01", dup_counts=None,
            master_ind="Y", prem_state="CA", prem_zip="90001",
            prem_county="LOS ANGELES", prem_census_tract=None,
        )
        row.update(overrides)
        cols = ", ".join(row)
        marks = ", ".join("?" * len(row))
        con.execute(f"INSERT INTO abc_std ({cols}) VALUES ({marks})", list(row.values()))
    return _add
