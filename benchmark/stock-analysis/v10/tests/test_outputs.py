from technical_assertions import (
    assert_label_series,
    assert_numeric_series,
    assert_source_alignment,
    load_csv_prices,
    load_results,
    wilder_rsi,
)


def inputs():
    return load_csv_prices("msft_prices.csv")


def expected_rsi():
    return wilder_rsi([close for _, close in inputs()])


def expected_labels():
    return [
        "N/A" if value is None
        else "overbought" if value > 70
        else "oversold" if value < 30
        else "neutral"
        for value in expected_rsi()
    ]


def output():
    return load_results(["date", "close", "rsi14", "signal"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_wilder_rsi_value():
    assert_numeric_series(output(), "rsi14", expected_rsi())


def test_every_unrounded_threshold_label():
    assert_label_series(output(), "signal", expected_labels())


def test_exact_warmup_boundary():
    rows = output()
    assert [row["rsi14"] for row in rows[:14]] == ["N/A"] * 14
    assert [row["signal"] for row in rows[:14]] == ["N/A"] * 14


def test_all_valid_labels_are_declared():
    assert set(row["signal"] for row in output()) <= {
        "N/A", "overbought", "oversold", "neutral",
    }
