from technical_assertions import (
    assert_label_series,
    assert_numeric_series,
    assert_source_alignment,
    crossing_labels,
    load_csv_prices,
    load_results,
    macd,
)


def inputs():
    return load_csv_prices("googl_prices.csv")


def expected():
    return macd([close for _, close in inputs()])


def output():
    return load_results(["date", "close", "macd", "signal", "action"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_macd_value():
    line, _ = expected()
    assert_numeric_series(output(), "macd", line)


def test_every_signal_value():
    _, signal = expected()
    assert_numeric_series(output(), "signal", signal)


def test_only_discrete_crossings_create_actions():
    line, signal = expected()
    labels = crossing_labels(line, signal, "buy", "sell", "hold")
    assert_label_series(output(), "action", labels)


def test_action_waits_for_nine_valid_macd_values():
    rows = output()
    assert [row["action"] for row in rows[:33]] == ["N/A"] * 33
    assert rows[33]["action"] == "hold"


def test_all_valid_actions_are_declared():
    assert set(row["action"] for row in output()) <= {"N/A", "buy", "sell", "hold"}
