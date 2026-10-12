import json
import os

OUTPUT_PATH = "/app/recover.json"

expected = [
    {"word": "testword00", "value": 5},
    {"word": "testword01", "value": 127},
    {"word": "testword02", "value": 128},
    {"word": "testword03", "value": 300},
    {"word": "testword04", "value": 10000},
    {"word": "testword05", "value": 100000},
    {"word": "testword06", "value": 500000},
    {"word": "testword07", "value": 999999},
]


def test_recover_json_exists():
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} does not exist"


def test_recover_json_valid():
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "recover.json should contain a list"
    assert len(data) > 0, "recover.json should not be empty"
    for item in data:
        assert "word" in item, f"Each item must have 'word': {item}"
        assert "value" in item, f"Each item must have 'value': {item}"
        assert isinstance(item["value"], (int, float)), f"value must be numeric: {item}"


def test_recover_json_all_expected_records():
    with open(OUTPUT_PATH) as f:
        data = json.load(f)

    expected_tuples = set()
    for item in expected:
        expected_tuples.add((item["word"], item["value"]))

    data_tuples = set()
    for item in data:
        data_tuples.add((item["word"], item["value"]))

    matches = expected_tuples & data_tuples

    assert len(matches) == len(expected), (
        f"Only {len(matches)} out of {len(expected)} records matched. "
        f"Missing: {expected_tuples - data_tuples}"
        f"Extra: {data_tuples - expected_tuples}"
    )


def test_recover_json_no_duplicate_words():
    with open(OUTPUT_PATH) as f:
        data = json.load(f)

    words = [item["word"] for item in data]
    assert len(words) == len(set(words)), f"Duplicate words found: {words}"


def test_recover_json_correct_values_for_each_word():
    with open(OUTPUT_PATH) as f:
        data = json.load(f)

    for item in data:
        w = item["word"]
        v = item["value"]
        expected_item = next((e for e in expected if e["word"] == w), None)
        assert expected_item is not None, f"Unexpected word in output: {w}"
        assert v == expected_item["value"], (
            f"Value mismatch for {w}: got {v}, expected {expected_item['value']}"
        )
