import json
import os

EXPECTED = [
    {"id": 1, "name": "apple", "value": 150},
    {"id": 2, "name": "banana", "value": 250},
    {"id": 3, "name": "cherry", "value": 300},
    {"id": 4, "name": "date", "value": 400},
    {"id": 5, "name": "elderberry", "value": 500},
    {"id": 6, "name": "fig", "value": 600},
    {"id": 7, "name": "grape", "value": 700},
    {"id": 8, "name": "honeydew", "value": 800},
    {"id": 9, "name": "kiwi", "value": 900},
    {"id": 10, "name": "lemon", "value": 1000},
    {"id": 11, "name": "mango", "value": 1100},
]

OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "/app/recovered.json")


def load_output(path):
    with open(path) as f:
        return json.load(f)


def test_output_exists():
    assert os.path.exists(OUTPUT_FILE), f"{OUTPUT_FILE} not found"


def test_output_is_valid_json():
    data = load_output(OUTPUT_FILE)
    assert isinstance(data, list), "output should be a JSON array"


def test_output_has_11_records():
    data = load_output(OUTPUT_FILE)
    assert len(data) == 11, f"expected 11 records, got {len(data)}"


def test_records_sorted_by_id():
    data = load_output(OUTPUT_FILE)
    ids = [r["id"] for r in data]
    assert ids == sorted(ids), "records not sorted by id"


def test_all_fields_present():
    data = load_output(OUTPUT_FILE)
    for row in data:
        assert "id" in row, f"missing id in {row}"
        assert "name" in row, f"missing name in {row}"
        assert "value" in row, f"missing value in {row}"


def test_field_types():
    data = load_output(OUTPUT_FILE)
    for row in data:
        assert isinstance(row["id"], int), f"id should be int, got {type(row['id'])}"
        assert isinstance(row["name"], str), f"name should be str, got {type(row['name'])}"
        assert isinstance(row["value"], int), f"value should be int, got {type(row['value'])}"


def test_correct_data():
    data = load_output(OUTPUT_FILE)
    for expected, actual in zip(EXPECTED, data):
        assert expected == actual, f"mismatch at id {expected['id']}: expected {expected}, got {actual}"


def test_not_hardcoded():
    data = load_output(OUTPUT_FILE)
    values = {r["name"]: r["value"] for r in data}
    assert values.get("apple") == 150
    assert values.get("mango") == 1100
    assert values.get("date") == 400
