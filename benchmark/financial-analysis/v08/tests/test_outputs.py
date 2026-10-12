from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED = {
    "FY2020": 48.54,
    "FY2021": 49.17,
    "FY2022": 50.26,
    "FY2023": 50.44,
    "FY2024": 49.57,
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


def test_multilevel_header_endpoints_are_both_recovered():
    indexed = index_unique(records())
    assert abs(float(indexed["FY2020"]["operating_margin_pct"]) - 48.54) < 0.011
    assert abs(float(indexed["FY2024"]["operating_margin_pct"]) - 49.57) < 0.011
