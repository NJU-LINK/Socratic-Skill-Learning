from bank_filter_test_support import (
    assert_complete,
    assert_exact_and_sorted,
    assert_identity_variation_is_covered,
    assert_precise,
    assert_schema_and_source_preservation,
    assert_valid_artifact,
)


EXPECTED_LINES = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 25, 27, 30, 32, 35, 36, 38, 41, 44]


def test_output_artifact_is_valid_json_array():
    assert_valid_artifact()


def test_all_account_chain_transactions_are_present():
    assert_complete(EXPECTED_LINES)


def test_name_only_finance_distractors_are_excluded():
    assert_precise(EXPECTED_LINES)


def test_exact_rows_and_chronological_order():
    assert_exact_and_sorted(EXPECTED_LINES)


def test_schema_and_csv_strings_are_preserved():
    assert_schema_and_source_preservation()


def test_internal_ledger_names_and_accounts_are_covered():
    assert_identity_variation_is_covered(EXPECTED_LINES)
