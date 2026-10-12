from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED = {
    "FY2021": 22.20,
    "FY2022": 5.36,
    "FY2023": 1.77,
    "FY2024": 7.37,
    "FY2025": 10.66,
}


def records():
    return load_csv(["fiscal_year", "operating_margin_pct"])


def test_every_available_year_appears_once():
    indexed = index_unique(records())
    assert set(indexed) == set(EXPECTED)
    assert len(indexed) == 5


def test_every_operating_margin_is_correct():
    assert_numeric_series(index_unique(records()), "operating_margin_pct", EXPECTED)


def test_result_contains_only_declared_columns():
    assert all(set(row) == {"fiscal_year", "operating_margin_pct"} for row in records())


def test_merged_header_extremes_are_both_recovered():
    indexed = index_unique(records())
    assert abs(float(indexed["FY2021"]["operating_margin_pct"]) - 22.20) < 0.011
    assert abs(float(indexed["FY2025"]["operating_margin_pct"]) - 10.66) < 0.011
