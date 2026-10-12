from technical_assertions import (
    assert_numeric_series,
    assert_source_alignment,
    ema,
    load_csv_prices,
    load_results,
)


def inputs():
    return load_csv_prices("tsla_prices.csv")


def output():
    return load_results(["date", "close", "ema12", "ema26"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_full_precision_sma_seeded_ema12():
    closes = [close for _, close in inputs()]
    assert_numeric_series(output(), "ema12", ema(closes, 12))


def test_full_precision_sma_seeded_ema26():
    closes = [close for _, close in inputs()]
    assert_numeric_series(output(), "ema26", ema(closes, 26))


def test_exact_warmup_boundaries():
    rows = output()
    assert [row["ema12"] for row in rows[:11]] == ["N/A"] * 11
    assert rows[11]["ema12"] != "N/A"
    assert [row["ema26"] for row in rows[:25]] == ["N/A"] * 25
    assert rows[25]["ema26"] != "N/A"
