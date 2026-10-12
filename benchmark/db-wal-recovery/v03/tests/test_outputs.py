from dbwal_assertions import load_output


EXPECTED_USERS = [
    {"id": 1, "name": "Alice", "email": "alice@ex.com"},
    {"id": 2, "name": "Bob", "email": "bob@ex.com"},
    {"id": 3, "name": "Charlie", "email": "charlie@ex.com"},
    {"id": 4, "name": "Diana", "email": "diana@ex.com"},
    {"id": 5, "name": "Eve", "email": "eve@ex.com"},
    {"id": 6, "name": "Frank", "email": "frank@ex.com"},
    {"id": 7, "name": "Grace", "email": "grace@ex.com"},
]

EXPECTED_PRODUCTS = [
    {"id": 1, "name": "Widget", "price": 9.99},
    {"id": 2, "name": "Gadget", "price": 24.99},
    {"id": 3, "name": "Doohickey", "price": 4.99},
    {"id": 4, "name": "Thingamajig", "price": 14.99},
    {"id": 5, "name": "Whatsit", "price": 7.99},
    {"id": 6, "name": "Contraption", "price": 39.99},
    {"id": 7, "name": "Gizmo", "price": 19.99},
]

EXPECTED_ORDERS = [
    {"id": 1, "user_id": 1, "product_id": 1, "quantity": 2, "total": 19.98},
    {"id": 2, "user_id": 2, "product_id": 2, "quantity": 1, "total": 24.99},
    {"id": 3, "user_id": 3, "product_id": 3, "quantity": 5, "total": 24.95},
    {"id": 4, "user_id": 1, "product_id": 4, "quantity": 1, "total": 14.99},
    {"id": 5, "user_id": 2, "product_id": 5, "quantity": 3, "total": 23.97},
    {"id": 6, "user_id": 3, "product_id": 6, "quantity": 1, "total": 39.99},
    {"id": 7, "user_id": 4, "product_id": 1, "quantity": 2, "total": 19.98},
    {"id": 8, "user_id": 5, "product_id": 2, "quantity": 1, "total": 24.99},
    {"id": 9, "user_id": 6, "product_id": 3, "quantity": 4, "total": 19.96},
    {"id": 10, "user_id": 7, "product_id": 4, "quantity": 2, "total": 29.98},
    {"id": 11, "user_id": 1, "product_id": 7, "quantity": 1, "total": 19.99},
]


def test_output_has_exact_table_set():
    data = load_output()
    assert isinstance(data, dict)
    assert set(data) == {"users", "products", "orders"}


def test_all_users_are_exact():
    assert load_output()["users"] == EXPECTED_USERS


def test_all_products_are_exact():
    assert load_output()["products"] == EXPECTED_PRODUCTS


def test_all_orders_are_exact():
    assert load_output()["orders"] == EXPECTED_ORDERS


def test_all_tables_are_sorted_and_have_exact_columns():
    data = load_output()
    schemas = {
        "users": {"id", "name", "email"},
        "products": {"id", "name", "price"},
        "orders": {"id", "user_id", "product_id", "quantity", "total"},
    }
    for table, expected_keys in schemas.items():
        assert [row["id"] for row in data[table]] == sorted(row["id"] for row in data[table])
        assert all(set(row) == expected_keys for row in data[table])


def test_foreign_keys_resolve_against_recovered_tables():
    data = load_output()
    users = {row["id"] for row in data["users"]}
    products = {row["id"] for row in data["products"]}
    assert all(row["user_id"] in users for row in data["orders"])
    assert all(row["product_id"] in products for row in data["orders"])


def test_wal_only_suffixes_are_present():
    data = load_output()
    assert [row["id"] for row in data["users"][-4:]] == [4, 5, 6, 7]
    assert [row["id"] for row in data["products"][-4:]] == [4, 5, 6, 7]
    assert [row["id"] for row in data["orders"][-8:]] == list(range(4, 12))
