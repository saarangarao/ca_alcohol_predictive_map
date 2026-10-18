import pytest

import ingest_abc as ia


@pytest.mark.parametrize("code, expected", [
    ("20", "OFF_SALE"),
    ("21", "OFF_SALE"),
    ("41", "ON_SALE_CORE"),
    ("47", "ON_SALE_CORE"),
    ("02", "PRODUCER_RETAIL"),   # leading zero must survive the lookup load
    ("58", "EXCLUDE"),
])
def test_known_license_types_get_the_expected_channel(con, add, code, expected):
    add(license_type=code)
    ia.build_clean(con)
    assert con.sql("SELECT channel FROM abc_labeled").fetchone()[0] == expected


def test_unknown_license_type_is_flagged_not_dropped(con, add):
    add(license_type="73")
    ia.build_clean(con)
    assert con.sql("SELECT channel FROM abc_labeled").fetchone()[0] == "UNMAPPED"


def test_non_retail_channels_never_reach_clean_outlets(con, add):
    add(license_type="58", file_number="00000001")   # EXCLUDE
    add(license_type="73", file_number="00000002")   # UNMAPPED
    ia.build_clean(con)
    assert con.sql("SELECT count(*) FROM clean_outlets").fetchone()[0] == 0
