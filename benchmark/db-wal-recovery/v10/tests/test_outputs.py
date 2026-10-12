import base64

from dbwal_assertions import load_output


EXPECTED = [
    {"id": 1, "name": "Apple", "price": 1.99, "data": "AAECAw=="},
    {"id": 2, "name": "Banana", "price": 0.99, "data": "BAUGBw=="},
    {"id": 3, "name": "Cherry", "price": 3.49, "data": "CAkKCw=="},
    {"id": 4, "name": "Date", "price": 2.99, "data": "DA0ODw=="},
    {"id": 5, "name": "Elderberry", "price": 4.99, "data": "EBESEw=="},
    {"id": 6, "name": "Fig", "price": 1.49, "data": "FBUWFw=="},
    {"id": 7, "name": "Grape", "price": 2.49, "data": "GBkaGw=="},
    {"id": 8, "name": "Honeydew", "price": 3.99, "data": "HB0eHw=="},
    {"id": 9, "name": "Kiwi", "price": 0.79, "data": "ICEiIw=="},
    {"id": 10, "name": "Lemon", "price": 1.29, "data": "JCUmJw=="},
    {"id": 11, "name": "Mango", "price": 5.49, "data": "KCkqKw=="},
]


def test_output_is_complete_array():
    data = load_output()
    assert isinstance(data, list)
    assert len(data) == 11


def test_ids_are_complete_unique_and_sorted():
    ids = [row["id"] for row in load_output()]
    assert ids == list(range(1, 12))
    assert len(ids) == len(set(ids))


def test_records_have_exact_schema_and_types():
    for row in load_output():
        assert set(row) == {"id", "name", "price", "data"}
        assert isinstance(row["id"], int) and not isinstance(row["id"], bool)
        assert isinstance(row["name"], str)
        assert isinstance(row["price"], (int, float))
        assert isinstance(row["data"], str)


def test_every_blob_is_canonical_base64():
    for row in load_output():
        decoded = base64.b64decode(row["data"], validate=True)
        assert base64.b64encode(decoded).decode("ascii") == row["data"]


def test_all_scalar_values_are_correct():
    data = load_output()
    assert [(row["id"], row["name"], row["price"]) for row in data] == [
        (row["id"], row["name"], row["price"]) for row in EXPECTED
    ]


def test_all_blob_values_are_correct():
    assert [row["data"] for row in load_output()] == [row["data"] for row in EXPECTED]


def test_wal_only_rows_are_present():
    assert load_output()[5:] == EXPECTED[5:]


def test_entire_output_is_exact():
    assert load_output() == EXPECTED
