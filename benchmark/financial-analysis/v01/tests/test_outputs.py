from financial_assertions import assert_numeric_series, index_unique, load_csv


EXPECTED = {
    "FY2022": 64.93,
    "FY2023": 56.93,
    "FY2024": 72.72,
    "FY2025": 74.99,
    "FY2026": 71.06,
}


def records():
    return load_csv(["fiscal_year", "gross_margin_pct"])


def test_latest_year_selects_gross_margin_branch():
    rows = records()
    assert "gross_margin_pct" in rows[0]
    assert "net_margin_pct" not in rows[0]


def test_every_available_year_appears_once():
    indexed = index_unique(records())
    assert set(indexed) == set(EXPECTED)
    assert len(indexed) == 5


def test_every_gross_margin_is_correct():
    assert_numeric_series(index_unique(records()), "gross_margin_pct", EXPECTED)


def test_result_contains_only_declared_columns():
    assert all(set(row) == {"fiscal_year", "gross_margin_pct"} for row in records())


def test_latest_year_is_not_silently_omitted():
    indexed = index_unique(records())
    assert abs(float(indexed["FY2026"]["gross_margin_pct"]) - 71.06) < 0.011
