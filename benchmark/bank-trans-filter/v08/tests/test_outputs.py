from bank_filter_test_support import (
    assert_complete,
    assert_exact_and_sorted,
    assert_identity_variation_is_covered,
    assert_precise,
    assert_schema_and_source_preservation,
    assert_valid_artifact,
)


EXPECTED_LINES = [3, 5, 9, 10, 12, 14, 17, 19, 20, 22, 25, 27, 28, 31, 32, 34]


def test_output_artifact_is_valid_json_array():
    assert_valid_artifact()


def test_all_target_transactions_are_present():
    assert_complete(EXPECTED_LINES)


def test_shared_account_distractors_are_excluded():
    assert_precise(EXPECTED_LINES)


def test_exact_rows_and_chronological_order():
    assert_exact_and_sorted(EXPECTED_LINES)


def test_schema_and_csv_strings_are_preserved():
    assert_schema_and_source_preservation()


def test_multiple_evidence_clusters_are_covered():
    assert_identity_variation_is_covered(EXPECTED_LINES)
