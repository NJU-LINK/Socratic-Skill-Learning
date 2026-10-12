from technical_assertions import (
    assert_label_series,
    assert_numeric_series,
    assert_source_alignment,
    load_csv_prices,
    load_results,
    pointwise_above,
    sma,
)


def inputs():
    return load_csv_prices("googl_prices.csv")


def expected():
    closes = [close for _, close in inputs()]
    return sma(closes, 5), sma(closes, 10)


def output():
    return load_results(["date", "close", "sma5", "sma10", "signal"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_sma_value():
    short, long = expected()
    assert_numeric_series(output(), "sma5", short)
    assert_numeric_series(output(), "sma10", long)


def test_every_unrounded_comparison_label():
    short, long = expected()
    assert_label_series(output(), "signal", pointwise_above(short, long))


def test_signal_warmup_matches_long_window():
    assert [row["signal"] for row in output()[:9]] == ["N/A"] * 9


def test_equal_display_values_do_not_replace_raw_comparison():
    rows = {row["date"]: row for row in output()}
    assert rows["2024-06-20"]["sma5"] == rows["2024-06-20"]["sma10"]
    assert rows["2024-06-20"]["signal"] == "0"
