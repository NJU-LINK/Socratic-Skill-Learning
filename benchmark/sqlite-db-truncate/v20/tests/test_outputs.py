import json
from pathlib import Path


OUTPUT = Path("/app/recover.json")
USERS = {
    1: ("Alice Johnson#", 95.5),
    2: ("Bob Smith#", 87.3),
    3: ("Charlie Brown#", 76.1),
    4: ("Diana Prince#", 92.0),
    5: ("Eve Taylor#", 68.4),
    6: ("Frank Miller#", 55.8),
}
PRODUCTS = {
    "P106-Thingy": (19.99, 100),
    "P107-Whatsit": (79.95, 22),
    "P108-Dohickey": (199.0, 8),
    "P109-Knob": (3.99, 500),
    "P110-Lever": (45.5, 18),
    "P111-Button": (99.99, 15),
    "P112-Switch": (1249.0, 3),
}
LOGS = {
    1: ("System started on port 3000", "A"),
    2: ("User login alice@example.com", "B"),
    3: ("Backup completed snapshot BKP-2024-0301", "D"),
    4: ("Config updated max_connections", "C"),
    5: ("WARNING High memory usage 85", "E"),
    6: ("Daily metrics 15234 requests", "G"),
    7: ("User logout bob@example.com", "A"),
    8: ("Scheduled maintenance starting", "B"),
    9: ("CRITICAL disk usage exceeded 90", "D"),
    10: ("Crash report core dump 0x4A2F", "C"),
    11: ("Deploy v2.5.0-rc3 12 new features", "E"),
}


def load_output():
    return json.loads(OUTPUT.read_text())


def test_file_exists():
    assert OUTPUT.is_file(), "/app/recover.json does not exist"


def test_top_level_schema():
    data = load_output()
    assert isinstance(data, dict), "recover.json must contain a JSON object"
    assert set(data) == {"users", "products", "logs"}
    assert all(isinstance(data[key], list) for key in data)


def test_complete_user_set():
    users = load_output()["users"]
    ids = [record.get("id") for record in users]
    assert len(ids) == len(set(ids)), f"Duplicate user ids: {ids}"
    assert set(ids) == set(USERS), f"Expected user ids {sorted(USERS)}, got {sorted(ids)}"


def test_user_schema_and_values():
    users = {record["id"]: record for record in load_output()["users"]}
    for user_id, (name_prefix, score) in USERS.items():
        record = users[user_id]
        assert set(record) == {"id", "name", "score"}
        assert isinstance(record["name"], str) and record["name"].startswith(name_prefix)
        assert isinstance(record["score"], (int, float))
        assert abs(float(record["score"]) - score) < 0.01


def test_complete_product_set():
    products = load_output()["products"]
    prefixes = [record.get("code", "").split("#", 1)[0] for record in products]
    assert len(prefixes) == len(set(prefixes)), f"Duplicate product codes: {prefixes}"
    assert set(prefixes) == set(PRODUCTS), (
        f"Expected product codes {sorted(PRODUCTS)}, got {sorted(prefixes)}"
    )


def test_product_schema_and_values():
    products = {
        record["code"].split("#", 1)[0]: record
        for record in load_output()["products"]
    }
    for code, (price, quantity) in PRODUCTS.items():
        record = products[code]
        assert set(record) == {"code", "price", "quantity"}
        assert isinstance(record["code"], str)
        assert isinstance(record["price"], (int, float))
        assert isinstance(record["quantity"], int)
        assert abs(float(record["price"]) - price) < 0.1
        assert record["quantity"] == quantity


def test_complete_log_set():
    logs = load_output()["logs"]
    ids = [record.get("entry_id") for record in logs]
    assert len(ids) == len(set(ids)), f"Duplicate log ids: {ids}"
    assert set(ids) == set(LOGS), f"Expected log ids {sorted(LOGS)}, got {sorted(ids)}"


def test_log_schema_and_values():
    logs = {record["entry_id"]: record for record in load_output()["logs"]}
    for entry_id, (prefix, filler) in LOGS.items():
        record = logs[entry_id]
        assert set(record) == {"entry_id", "message"}
        assert isinstance(record["message"], str)
        assert record["message"].startswith(prefix)
        assert sum(char == filler for char in record["message"][-50:]) >= 10


def test_exact_total_recoverable_count():
    data = load_output()
    assert sum(len(data[key]) for key in ("users", "products", "logs")) == 24
