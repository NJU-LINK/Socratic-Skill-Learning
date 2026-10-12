import json
from pathlib import Path


OUTPUT = Path("/app/recovered.json")

STANDARD_ITEMS = [
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

GREEK_ITEMS = [
    {"id": 1, "name": "alpha", "value": 111},
    {"id": 2, "name": "beta", "value": 222},
    {"id": 3, "name": "gamma", "value": 333},
    {"id": 4, "name": "delta", "value": 444},
    {"id": 5, "name": "epsilon", "value": 555},
    {"id": 6, "name": "zeta", "value": 666},
    {"id": 7, "name": "eta", "value": 777},
    {"id": 8, "name": "theta", "value": 888},
    {"id": 9, "name": "iota", "value": 999},
    {"id": 10, "name": "kappa", "value": 1010},
    {"id": 11, "name": "lambda", "value": 1111},
]


def load_output():
    assert OUTPUT.is_file(), f"{OUTPUT} not found"
    with OUTPUT.open() as stream:
        return json.load(stream)


def assert_item_schema(records, numeric_field="value"):
    assert isinstance(records, list)
    for index, record in enumerate(records):
        assert isinstance(record, dict), f"record {index} is not an object"
        assert set(record) == {"id", "name", numeric_field}
        assert isinstance(record["id"], int) and not isinstance(record["id"], bool)
        assert isinstance(record["name"], str)
        assert isinstance(record[numeric_field], (int, float))
