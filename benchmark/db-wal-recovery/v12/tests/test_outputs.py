import json
import os

RECOVERED_PATH = "/app/recovered.json"
DB_PATH = "/app/main.db"

EXPECTED_CUSTOMERS = [
    {"id": 1, "name": "Alice", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"},
    {"id": 3, "name": "Carol", "email": "carol@example.com"},
    {"id": 4, "name": "David", "email": "david@example.com"},
    {"id": 5, "name": "Eve", "email": "eve@example.com"},
    {"id": 6, "name": "Frank", "email": "frank@example.com"},
    {"id": 7, "name": "Grace", "email": "grace@example.com"},
]

EXPECTED_ORDERS = [
    {"id": 1, "customer_id": 1, "product": "Widget A", "amount": 29.99},
    {"id": 2, "customer_id": 2, "product": "Gadget B", "amount": 49.99},
    {"id": 3, "customer_id": 1, "product": "Gizmo C", "amount": 19.99},
    {"id": 4, "customer_id": 3, "product": "Widget A", "amount": 29.99},
    {"id": 5, "customer_id": 5, "product": "Gadget B", "amount": 49.99},
    {"id": 6, "customer_id": 7, "product": "Widget A", "amount": 29.99},
]

EXPECTED_ORDER_ITEMS = [
    {"id": 1, "order_id": 1, "item": "Widget", "qty": 2, "price": 14.99},
    {"id": 2, "order_id": 1, "item": "Bracket", "qty": 4, "price": 5.0},
    {"id": 3, "order_id": 2, "item": "Gadget", "qty": 1, "price": 49.99},
    {"id": 4, "order_id": 3, "item": "Gizmo", "qty": 3, "price": 6.66},
    {"id": 5, "order_id": 4, "item": "Widget", "qty": 1, "price": 29.99},
    {"id": 6, "order_id": 5, "item": "Gadget", "qty": 2, "price": 24.99},
    {"id": 7, "order_id": 6, "item": "Screw", "qty": 8, "price": 1.25},
]


def load_recovered():
    with open(RECOVERED_PATH) as f:
        return json.load(f)


def test_file_exists():
    assert os.path.exists(RECOVERED_PATH)


def test_is_valid_json_dict():
    data = load_recovered()
    assert isinstance(data, dict)


def test_has_expected_tables():
    data = load_recovered()
    assert set(data.keys()) == {"customers", "orders", "order_items"}


def test_correct_record_counts():
    data = load_recovered()
    assert len(data["customers"]) == 7
    assert len(data["orders"]) == 6
    assert len(data["order_items"]) == 7


def test_customers_sorted_by_id():
    data = load_recovered()
    ids = [r["id"] for r in data["customers"]]
    assert ids == sorted(ids)


def test_orders_sorted_by_id():
    data = load_recovered()
    ids = [r["id"] for r in data["orders"]]
    assert ids == sorted(ids)


def test_order_items_sorted_by_id():
    data = load_recovered()
    ids = [r["id"] for r in data["order_items"]]
    assert ids == sorted(ids)


def test_customers_have_required_fields():
    data = load_recovered()
    for r in data["customers"]:
        assert "id" in r
        assert "name" in r
        assert "email" in r


def test_orders_have_required_fields():
    data = load_recovered()
    for r in data["orders"]:
        assert "id" in r
        assert "customer_id" in r
        assert "product" in r
        assert "amount" in r


def test_order_items_have_required_fields():
    data = load_recovered()
    for r in data["order_items"]:
        assert "id" in r
        assert "order_id" in r
        assert "item" in r
        assert "qty" in r
        assert "price" in r


def test_customers_data():
    data = load_recovered()
    for e, a in zip(EXPECTED_CUSTOMERS, data["customers"]):
        assert a["id"] == e["id"]
        assert a["name"] == e["name"]
        assert a["email"] == e["email"]


def test_orders_data():
    data = load_recovered()
    for e, a in zip(EXPECTED_ORDERS, data["orders"]):
        assert a["id"] == e["id"]
        assert a["customer_id"] == e["customer_id"]
        assert a["product"] == e["product"]
        assert abs(a["amount"] - e["amount"]) < 0.01


def test_order_items_data():
    data = load_recovered()
    for e, a in zip(EXPECTED_ORDER_ITEMS, data["order_items"]):
        assert a["id"] == e["id"]
        assert a["order_id"] == e["order_id"]
        assert a["item"] == e["item"]
        assert a["qty"] == e["qty"]
        assert abs(a["price"] - e["price"]) < 0.01


def test_no_duplicate_ids_in_customers():
    data = load_recovered()
    ids = [r["id"] for r in data["customers"]]
    assert len(ids) == len(set(ids))


def test_no_duplicate_ids_in_orders():
    data = load_recovered()
    ids = [r["id"] for r in data["orders"]]
    assert len(ids) == len(set(ids))


def test_no_duplicate_ids_in_order_items():
    data = load_recovered()
    ids = [r["id"] for r in data["order_items"]]
    assert len(ids) == len(set(ids))


def test_wal_data_recovered():
    data = load_recovered()
    assert len(data["customers"]) > 3
    assert len(data["orders"]) > 0
    assert len(data["order_items"]) > 0


def test_field_types():
    data = load_recovered()
    for r in data["customers"]:
        assert isinstance(r["id"], int)
        assert isinstance(r["name"], str)
        assert isinstance(r["email"], str)
    for r in data["orders"]:
        assert isinstance(r["id"], int)
        assert isinstance(r["customer_id"], int)
        assert isinstance(r["product"], str)
        assert isinstance(r["amount"], (int, float))
    for r in data["order_items"]:
        assert isinstance(r["id"], int)
        assert isinstance(r["order_id"], int)
        assert isinstance(r["item"], str)
        assert isinstance(r["qty"], int)
        assert isinstance(r["price"], (int, float))
