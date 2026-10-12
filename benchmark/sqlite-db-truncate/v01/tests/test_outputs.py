import json
from pathlib import Path


OUTPUT = Path("/app/recover.json")
EXPECTED = {
    "testword02": 10.0,
    "testword03": 25.0,
    "testword04": 42.0,
    "testword05": 50.0,
    "testword06": 75.0,
    "testword07": 99.0,
    "testword08": 99.99,
    "testword09": 0.5,
}


def load_output():
    return json.loads(OUTPUT.read_text())


def test_recover_json_exists():
    assert OUTPUT.is_file(), "/app/recover.json does not exist"


def test_recover_json_schema():
    data = load_output()
    assert isinstance(data, list), "recover.json must contain a JSON array"
    for record in data:
        assert set(record) == {"word", "value"}, f"Unexpected record schema: {record}"
        assert isinstance(record["word"], str), f"word must be a string: {record}"
        assert isinstance(record["value"], (int, float)), f"value must be numeric: {record}"


def test_complete_recoverable_word_set():
    words = [record["word"] for record in load_output()]
    assert len(words) == len(set(words)), f"Duplicate words: {words}"
    assert set(words) == set(EXPECTED), (
        f"Missing={sorted(set(EXPECTED) - set(words))}; "
        f"unexpected={sorted(set(words) - set(EXPECTED))}"
    )


def test_every_recoverable_value():
    actual = {record["word"]: float(record["value"]) for record in load_output()}
    for word, expected in EXPECTED.items():
        assert abs(actual[word] - expected) < 0.001, (
            f"{word}: expected {expected}, got {actual[word]}"
        )


def test_word_format():
    for word in (record["word"] for record in load_output()):
        assert len(word) == 10 and word.startswith("testword") and word[8:].isdigit()
