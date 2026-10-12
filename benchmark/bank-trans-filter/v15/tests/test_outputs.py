from bank_filter_test_support import (
    assert_complete,
    assert_exact_and_sorted,
    assert_identity_variation_is_covered,
    assert_precise,
    assert_schema_and_source_preservation,
    assert_valid_artifact,
)


EXPECTED_LINES = [64, 97, 179, 220, 226, 235, 275, 294, 302]


def test_output_artifact_is_valid_json_array():
    assert_valid_artifact()


def test_all_target_transactions_are_present():
    assert_complete(EXPECTED_LINES)


def test_poisoned_shared_account_row_is_excluded():
    assert_precise(EXPECTED_LINES)


def test_exact_rows_and_chronological_order():
    assert_exact_and_sorted(EXPECTED_LINES)


def test_schema_and_csv_strings_are_preserved():
    assert_schema_and_source_preservation()


def test_account_linked_name_variations_are_covered():
    assert_identity_variation_is_covered(EXPECTED_LINES)
