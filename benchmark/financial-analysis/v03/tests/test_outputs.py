from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED_NUMERIC = {
    "FY2022": -59.66,
    "FY2023": -78.92,
    "FY2024": -1210.48,
    "FY2025": 98.58,
}


def records():
    return load_csv(["fiscal_year", "net_income_growth_pct"])


def test_every_available_year_appears_once():
    indexed = index_unique(records())
    assert set(indexed) == {"FY2021", *EXPECTED_NUMERIC}
    assert len(indexed) == 5


def test_first_year_is_exactly_na():
    assert index_unique(records())["FY2021"]["net_income_growth_pct"] == "N/A"


def test_every_numeric_growth_rate_is_correct():
    indexed = index_unique(records())
    assert_numeric_series(
        {year: indexed[year] for year in EXPECTED_NUMERIC},
        "net_income_growth_pct",
        EXPECTED_NUMERIC,
    )


def test_sign_changes_and_large_loss_are_preserved():
    indexed = index_unique(records())
    assert float(indexed["FY2024"]["net_income_growth_pct"]) < -1000
    assert float(indexed["FY2025"]["net_income_growth_pct"]) > 0


def test_result_contains_only_declared_columns():
    assert all(set(row) == {"fiscal_year", "net_income_growth_pct"} for row in records())
