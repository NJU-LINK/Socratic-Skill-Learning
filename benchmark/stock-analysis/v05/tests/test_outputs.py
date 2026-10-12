from technical_assertions import (
    assert_numeric_series,
    assert_source_alignment,
    load_csv_prices,
    load_results,
    wilder_rsi,
)


def inputs():
    return load_csv_prices("aapl_prices.csv")


def output():
    return load_results(["date", "close", "rsi14"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_wilder_rsi_value():
    closes = [close for _, close in inputs()]
    assert_numeric_series(output(), "rsi14", wilder_rsi(closes))


def test_exact_warmup_boundary():
    rows = output()
    assert [row["rsi14"] for row in rows[:14]] == ["N/A"] * 14
    assert rows[14]["rsi14"] != "N/A"


def test_all_valid_rsi_values_are_bounded():
    values = [float(row["rsi14"]) for row in output() if row["rsi14"] != "N/A"]
    assert values
    assert all(0 <= value <= 100 for value in values)
