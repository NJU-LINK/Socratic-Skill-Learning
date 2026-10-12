from technical_assertions import (
    assert_numeric_series,
    assert_source_alignment,
    load_csv_prices,
    load_results,
    macd,
)


def inputs():
    return load_csv_prices("msft_prices.csv")


def expected():
    return macd([close for _, close in inputs()])


def output():
    return load_results(["date", "close", "macd", "signal"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_macd_value():
    line, _ = expected()
    assert_numeric_series(output(), "macd", line)


def test_every_signal_ema_value():
    _, signal = expected()
    assert_numeric_series(output(), "signal", signal)


def test_macd_warmup_boundary():
    rows = output()
    assert [row["macd"] for row in rows[:25]] == ["N/A"] * 25
    assert rows[25]["macd"] != "N/A"


def test_signal_requires_nine_valid_macd_values():
    rows = output()
    assert [row["signal"] for row in rows[:33]] == ["N/A"] * 33
    assert rows[33]["signal"] != "N/A"
