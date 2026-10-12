from technical_assertions import (
    assert_numeric_series,
    assert_source_alignment,
    load_csv_prices,
    load_results,
    sma,
)


def inputs():
    return load_csv_prices("stock_data.csv")


def output():
    return load_results(["date", "close", "sma5", "sma10"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_sma5_for_every_observation():
    prices = [close for _, close in inputs()]
    assert_numeric_series(output(), "sma5", sma(prices, 5))


def test_sma10_for_every_observation():
    prices = [close for _, close in inputs()]
    assert_numeric_series(output(), "sma10", sma(prices, 10))


def test_warmup_boundaries():
    rows = output()
    assert [row["sma5"] for row in rows[:4]] == ["N/A"] * 4
    assert rows[4]["sma5"] != "N/A"
    assert [row["sma10"] for row in rows[:9]] == ["N/A"] * 9
    assert rows[9]["sma10"] != "N/A"
