import pytest

import ingest_abc as ia


def test_zip_plus_four_is_trimmed_to_five_digits(con, add):
    add(prem_zip="90033-2028")
    ia.build_clean(con)
    assert con.sql("SELECT zip5 FROM clean_outlets").fetchone()[0] == "90033"


def test_leading_zeros_survive(con, add):
    add(prem_zip="01234")
    ia.build_clean(con)
    assert con.sql("SELECT zip5 FROM clean_outlets").fetchone()[0] == "01234"


@pytest.mark.parametrize("bad", [None, "", "9021", "ABCDE", "9O210"])
def test_malformed_zips_go_to_bad_zip_not_clean_outlets(con, add, bad):
    add(prem_zip=bad)
    ia.build_clean(con)
    assert con.sql("SELECT count(*) FROM clean_outlets").fetchone()[0] == 0
    assert con.sql("SELECT count(*) FROM bad_zip").fetchone()[0] == 1


def test_no_outlet_is_silently_lost_between_clean_and_bad(con, add):
    add(file_number="00000001", prem_zip="90001")
    add(file_number="00000002", prem_zip=None)
    add(file_number="00000003", prem_zip="XYZ")
    ia.build_clean(con)
    clean = con.sql("SELECT count(*) FROM clean_outlets").fetchone()[0]
    bad = con.sql("SELECT count(*) FROM bad_zip").fetchone()[0]
    deduped = con.sql("SELECT count(*) FROM outlets_deduped").fetchone()[0]
    assert clean + bad == deduped
