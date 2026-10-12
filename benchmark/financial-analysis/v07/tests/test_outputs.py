from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED = {
    "FY2020": 27.84,
    "FY2021": 26.64,
    "FY2022": 30.60,
    "FY2023": 33.41,
    "FY2024": 35.63,
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


def test_chinese_statement_endpoints_are_both_recovered():
    indexed = index_unique(records())
    assert abs(float(indexed["FY2020"]["roe_pct"]) - 27.84) < 0.011
    assert abs(float(indexed["FY2024"]["roe_pct"]) - 35.63) < 0.011
