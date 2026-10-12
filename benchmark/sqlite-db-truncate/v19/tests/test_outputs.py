import json
import os
import pytest

OUTPUT_PATH = "/app/recover.json"

expected = [
    {"word": "testword01", "value": 5},
    {"word": "testword02", "value": 10},
    {"word": "testword03", "value": 25},
    {"word": "testword04", "value": 42},
    {"word": "testword05", "value": 50},
    {"word": "testword06", "value": 75},
    {"word": "testword07", "value": 99},
    {"word": "testword08", "value": 99.99},
    {"word": "testword09", "value": 0.5},
    {"word": "testword10", "value": 128},
    {"word": "testword11", "value": 200.0},
    {"word": "testword12", "value": 3.14},
]


def load_output():
    with open(OUTPUT_PATH) as f:
        return json.load(f)


def test_recover_json_exists():
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} does not exist"


def test_recover_json_valid():
    data = load_output()
    assert isinstance(data, list), "recover.json should contain a list"
    assert len(data) > 0, "recover.json should not be empty"
    for item in data:
        assert "word" in item, f"Each item must have 'word': {item}"
        assert "value" in item, f"Each item must have 'value': {item}"
        assert isinstance(item["value"], (int, float)), f"value must be numeric: {item}"


def test_recover_json_correct_count():
    data = load_output()
    assert len(data) == 12, f"Expected 12 records, got {len(data)}: {[r['word'] for r in data]}"


def test_recover_json_no_duplicate_words():
    data = load_output()
    words = [item["word"] for item in data]
    assert len(words) == len(set(words)), f"Duplicate words found: {words}"


def test_recover_json_word_format():
    data = load_output()
    for item in data:
        w = item["word"]
        assert w.startswith("testword"), f"Word must start with 'testword': {w}"
        assert len(w) == 10, f"Word must be exactly 10 chars: {w}"
        assert w[8:].isdigit(), f"Word must end with 2 digits: {w}"


def test_recover_json_all_expected_present():
    data = load_output()

    expected_tuples = set()
    for item in expected:
        expected_tuples.add((item["word"], float(item["value"])))

    data_tuples = set()
    for item in data:
        data_tuples.add((item["word"], float(item["value"])))

    matches = expected_tuples & data_tuples
    missing = expected_tuples - data_tuples

    assert len(matches) == 12, (
        f"Only {len(matches)} out of 12 records matched. "
        f"Missing: {missing}. "
        f"Unexpected extra items: {data_tuples - expected_tuples}"
    )


def test_recover_json_values_match():
    data = load_output()
    expected_by_word = {e["word"]: e["value"] for e in expected}

    for item in data:
        w = item["word"]
        v = item["value"]
        expected_val = expected_by_word.get(w)
        if expected_val is not None:
            assert abs(float(v) - float(expected_val)) < 0.001, (
                f"Value mismatch for {w}: got {v}, expected {expected_val}"
            )


def test_recover_json_sorted_by_word():
    data = load_output()
    words = [item["word"] for item in data]
    assert words == sorted(words), f"Output should be sorted by word: {words}"
