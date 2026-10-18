import ingest_abc as ia


def n_outlets(con):
    return con.sql("SELECT count(*) FROM clean_outlets").fetchone()[0]


def test_same_license_type_twice_counts_as_one_outlet(con, add):
    add(license_type="47", master_ind="Y")
    add(license_type="47", master_ind="N", dup_counts="001")
    ia.build_clean(con)
    assert n_outlets(con) == 1


def test_two_master_rows_still_count_as_one_outlet(con, add):
    # master_ind alone is NOT a safe dedupe key: both rows here are marked Y
    add(license_type="41", master_ind="Y")
    add(license_type="42", master_ind="Y")     # both ON_SALE_CORE
    ia.build_clean(con)
    assert n_outlets(con) == 1


def test_premises_with_two_channels_gives_one_row_per_channel(con, add):
    add(license_type="21")   # OFF_SALE
    add(license_type="42")   # ON_SALE_CORE, same file number
    ia.build_clean(con)
    rows = con.sql("SELECT channel FROM clean_outlets ORDER BY channel").fetchall()
    assert rows == [("OFF_SALE",), ("ON_SALE_CORE",)]


def test_master_record_is_the_one_kept(con, add):
    add(license_type="41", master_ind="N")
    add(license_type="42", master_ind="Y")
    ia.build_clean(con)
    assert con.sql("SELECT license_type FROM clean_outlets").fetchone()[0] == "42"


def test_outlet_with_no_master_row_is_not_lost(con, add):
    add(license_type="47", master_ind="N")
    ia.build_clean(con)
    assert n_outlets(con) == 1


def test_different_file_numbers_are_different_outlets(con, add):
    add(file_number="00000001")
    add(file_number="00000002")
    ia.build_clean(con)
    assert n_outlets(con) == 2
