from technical_assertions import (
    assert_numeric_series,
    assert_source_alignment,
    bollinger,
    load_csv_prices,
    load_results,
)


def inputs():
    return load_csv_prices("googl_prices.csv")


def expected():
    return bollinger([close for _, close in inputs()])


def output():
    return load_results(["date", "close", "middle", "upper", "lower"])


def test_complete_source_alignment():
    assert_source_alignment(output(), inputs())


def test_every_middle_band_value():
    middle, _, _ = expected()
    assert_numeric_series(output(), "middle", middle)


def test_every_population_upper_band_value():
    _, upper, _ = expected()
    assert_numeric_series(output(), "upper", upper)


def test_every_population_lower_band_value():
    _, _, lower = expected()
    assert_numeric_series(output(), "lower", lower)


def test_exact_twenty_observation_warmup():
    rows = output()
    for column in ["middle", "upper", "lower"]:
        assert [row[column] for row in rows[:19]] == ["N/A"] * 19
        assert rows[19][column] != "N/A"
