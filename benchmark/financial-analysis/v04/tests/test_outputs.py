from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED = {
    "FY2021": 27.55,
    "FY2022": 34.22,
    "FY2023": 24.81,
    "FY2024": 27.05,
    "FY2025": 31.76,
}


def records():
    return load_csv(["fiscal_year", "roe_pct"])


def test_every_joined_year_appears_once():
    indexed = index_unique(records())
    assert set(indexed) == set(EXPECTED)
    assert len(indexed) == 5


def test_every_roe_value_is_correct():
    assert_numeric_series(index_unique(records()), "roe_pct", EXPECTED)


def test_result_contains_only_declared_columns():
    assert all(set(row) == {"fiscal_year", "roe_pct"} for row in records())


def test_join_uses_each_years_matching_equity():
    indexed = index_unique(records())
    assert abs(float(indexed["FY2022"]["roe_pct"]) - 34.22) < 0.011
    assert abs(float(indexed["FY2023"]["roe_pct"]) - 24.81) < 0.011
