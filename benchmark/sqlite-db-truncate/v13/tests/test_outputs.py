import json
from pathlib import Path


OUTPUT = Path("/app/recover.json")
EXPECTED = {
    105: 75.25,
    106: 99.99,
    107: 0.5,
    108: 1.234,
}


def load_output():
    return json.loads(OUTPUT.read_text())


def test_recover_json_exists():
    assert OUTPUT.is_file(), "/app/recover.json does not exist"


def test_recover_json_schema():
    data = load_output()
    assert isinstance(data, list), "recover.json must contain a JSON array"
    for record in data:
        assert set(record) == {"id", "value"}, f"Unexpected record schema: {record}"
        assert isinstance(record["id"], int), f"id must be an integer: {record}"
        assert isinstance(record["value"], (int, float)), f"value must be numeric: {record}"


def test_no_duplicate_ids():
    ids = [record["id"] for record in load_output()]
    assert len(ids) == len(set(ids)), f"Duplicate ids: {ids}"


def test_complete_recoverable_id_set():
    ids = {record["id"] for record in load_output()}
    assert ids == set(EXPECTED), (
        f"Missing={sorted(set(EXPECTED) - ids)}; "
        f"unexpected={sorted(ids - set(EXPECTED))}"
    )


def test_every_recoverable_value():
    actual = {record["id"]: float(record["value"]) for record in load_output()}
    for record_id, expected in EXPECTED.items():
        assert abs(actual[record_id] - expected) < 0.001, (
            f"id={record_id}: expected {expected}, got {actual[record_id]}"
        )


def test_value_domain():
    for record in load_output():
        assert 100 <= record["id"] <= 200
        assert -1_000_000 <= float(record["value"]) <= 1_000_000
