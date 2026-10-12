import json
import os
import sqlite3

RECOVERED_PATH = "/app/recovered.json"

EXPECTED = [
    {"id": 1, "name": "apple", "price": 150},
    {"id": 2, "name": "banana", "price": 250},
    {"id": 3, "name": "cherry", "price": 120},
    {"id": 4, "name": "date", "price": 30},
    {"id": 5, "name": "elderberry", "price": 200},
    {"id": 6, "name": "fig", "price": 90},
    {"id": 7, "name": "grape", "price": 45},
    {"id": 8, "name": "honeydew", "price": 60},
    {"id": 9, "name": "kiwi", "price": 300},
]

EXPENSIVE_ITEMS = [r for r in EXPECTED if r["price"] > 100]

DB_PATH = "/app/main.db"


def load_recovered():
    with open(RECOVERED_PATH) as f:
        return json.load(f)


def test_file_exists():
    assert os.path.exists(RECOVERED_PATH), f"{RECOVERED_PATH} not found"


def test_is_valid_json_array():
    data = load_recovered()
    assert isinstance(data, list), "recovered.json should be a JSON array"


def test_has_9_records():
    data = load_recovered()
    assert len(data) == 9, f"Expected 9 records, got {len(data)}"


def test_records_sorted_by_id():
    data = load_recovered()
    ids = [r["id"] for r in data]
    assert ids == sorted(ids), "Records not sorted by id"


def test_ids_are_1_to_9():
    data = load_recovered()
    ids = [r["id"] for r in data]
    assert ids == [1, 2, 3, 4, 5, 6, 7, 8, 9], f"Expected ids 1-9, got {ids}"


def test_each_record_has_required_fields():
    data = load_recovered()
    for i, record in enumerate(data):
        assert isinstance(record, dict), f"Record {i} is not a dict"
        assert "id" in record, f"Record {i} missing 'id'"
        assert "name" in record, f"Record {i} missing 'name'"
        assert "price" in record, f"Record {i} missing 'price'"


def test_field_types():
    data = load_recovered()
    for record in data:
        assert isinstance(record["id"], int), f"id {record['id']} is not int"
        assert isinstance(record["name"], str), f"name for id {record['id']} is not str"
        assert isinstance(record["price"], (int, float)), f"price for id {record['id']} is not numeric"


def test_correct_data():
    data = load_recovered()
    for expected, actual in zip(EXPECTED, data):
        assert actual["id"] == expected["id"], f"id mismatch at position"
        assert actual["name"] == expected["name"], f"id={expected['id']} name mismatch: {actual['name']} != {expected['name']}"
        assert actual["price"] == expected["price"], f"id={expected['id']} price mismatch: {actual['price']} != {expected['price']}"


def test_updated_prices_applied():
    data = load_recovered()
    by_id = {r["id"]: r for r in data}
    assert by_id[1]["price"] == 150, "Apple price should be 150 (WAL update applied)"
    assert by_id[2]["price"] == 250, "Banana price should be 250 (WAL update applied)"


def test_wal_inserts_recovered():
    data = load_recovered()
    by_id = {r["id"]: r for r in data}
    assert by_id[6]["name"] == "fig", "fig WAL insert not found"
    assert by_id[7]["name"] == "grape", "grape WAL insert not found"
    assert by_id[8]["name"] == "honeydew", "honeydew WAL insert not found"
    assert by_id[9]["name"] == "kiwi", "kiwi WAL insert not found"


def test_no_duplicate_ids():
    data = load_recovered()
    ids = [r["id"] for r in data]
    assert len(ids) == len(set(ids)), "Duplicate ids found"


def test_not_just_base_data():
    data = load_recovered()
    assert len(data) > 5, "Only base records recovered - WAL data not applied"


def test_fake_checkpoint_was_stripped():
    data = load_recovered()
    assert len(data) == 9, "Fake checkpoint frame may not have been stripped"


def test_expensive_items_view():
    conn = sqlite3.connect(DB_PATH)
    try:
        view_rows = conn.execute("SELECT id, name, price FROM expensive_items ORDER BY id").fetchall()
        assert len(view_rows) == len(EXPENSIVE_ITEMS), (
            f"expensive_items: expected {len(EXPENSIVE_ITEMS)} rows, got {len(view_rows)}"
        )
        for (rid, rname, rprice), exp in zip(view_rows, EXPENSIVE_ITEMS):
            assert rid == exp["id"], f"id mismatch in view: {rid} != {exp['id']}"
            assert rname == exp["name"], f"name mismatch in view: {rname} != {exp['name']}"
            assert rprice == exp["price"], f"price mismatch in view: {rprice} != {exp['price']}"
    finally:
        conn.close()
