from technical_assertions import (
    assert_label_series,
    assert_numeric_series,
    assert_source_alignment,
    crossing_labels,
    load_csv_prices,
    load_results,
    sma,
)


def inputs():
    return load_csv_prices("aapl_prices.csv")


def expected():
    closes = [close for _, close in inputs()]
    return sma(closes, 20), sma(closes, 50)


def output():
    return load_results(["date", "close", "sma20", "sma50", "cross_signal"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_long_window_sma_value():
    short, long = expected()
    assert_numeric_series(output(), "sma20", short)
    assert_numeric_series(output(), "sma50", long)


def test_only_discrete_crossing_events_are_labeled():
    short, long = expected()
    labels = crossing_labels(short, long, "golden", "death", "none")
    assert_label_series(output(), "cross_signal", labels)


def test_first_jointly_valid_row_is_not_a_cross():
    assert output()[49]["cross_signal"] == "none"


def test_persistent_relation_is_not_repeated_as_crosses():
    labels = [row["cross_signal"] for row in output()]
    assert labels.count("golden") == 1
    assert labels.count("death") == 0
