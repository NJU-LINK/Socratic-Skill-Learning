import os
import sys
import uuid

import pytest

for candidate in ("/app/catalog.db", "/app/instance/catalog.db"):
    try:
        os.remove(candidate)
    except FileNotFoundError:
        pass

sys.path.insert(0, "/app")
from solve import app

DATABASE_CREATED_AT_IMPORT = os.path.exists("/app/catalog.db")


@pytest.fixture(scope="module")
def client():
    return app.test_client()


def _setup(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_database_uses_declared_path_and_setup_has_no_import_side_effect(client):
    assert not DATABASE_CREATED_AT_IMPORT
    _setup(client)
    assert os.path.isfile("/app/catalog.db")


def test_setup_is_idempotent_and_seeds_three_populated_categories(client):
    _setup(client)
    before_products = len(client.get("/products").get_json())
    _setup(client)
    categories = client.get("/categories").get_json()
    assert {category["name"] for category in categories} == {
        "Electronics",
        "Books",
        "Clothing",
    }
    assert all(category["product_count"] >= 3 for category in categories)
    assert len(client.get("/products").get_json()) == before_products


def test_product_representations_include_relational_context(client):
    _setup(client)
    products = client.get("/products").get_json()
    assert products
    item = products[0]
    assert set(item) == {
        "id",
        "name",
        "price",
        "stock",
        "category_id",
        "category_name",
    }
    detail = client.get(f"/products/{item['id']}")
    assert detail.status_code == 200
    data = detail.get_json()
    assert data["id"] == item["id"]
    assert data["category"] == {
        "id": item["category_id"],
        "name": item["category_name"],
        "description": next(
            category["description"]
            for category in client.get("/categories").get_json()
            if category["id"] == item["category_id"]
        ),
    }


def test_combined_filters_apply_category_price_and_stock(client):
    _setup(client)
    categories = client.get("/categories").get_json()
    first, second = categories[:2]
    token = uuid.uuid4().hex[:8]
    cases = [
        (f"target-{token}", 25.0, 3, first["id"]),
        (f"zero-{token}", 26.0, 0, first["id"]),
        (f"expensive-{token}", 80.0, 3, first["id"]),
        (f"other-{token}", 25.0, 3, second["id"]),
    ]
    for name, price, stock, category_id in cases:
        assert client.post(
            "/products",
            json={
                "name": name,
                "price": price,
                "stock": stock,
                "category_id": category_id,
            },
        ).status_code == 201
    results = client.get(
        f"/products?category_id={first['id']}&min_price=24&max_price=30&in_stock=true"
    ).get_json()
    names = {item["name"] for item in results}
    assert f"target-{token}" in names
    assert f"zero-{token}" not in names
    assert f"expensive-{token}" not in names
    assert f"other-{token}" not in names
    assert all(
        item["category_id"] == first["id"]
        and 24 <= item["price"] <= 30
        and item["stock"] > 0
        for item in results
    )


def test_create_product_persists_exact_values(client):
    _setup(client)
    category_id = client.get("/categories").get_json()[0]["id"]
    payload = {
        "name": f"created-{uuid.uuid4().hex}",
        "price": 0,
        "stock": 0,
        "category_id": category_id,
    }
    response = client.post("/products", json=payload)
    assert response.status_code == 201
    created = response.get_json()
    assert {key: created[key] for key in payload} == payload
    assert client.get(f"/products/{created['id']}").status_code == 200


def test_create_validation_rejects_bad_state_without_adding_rows(client):
    _setup(client)
    category_id = client.get("/categories").get_json()[0]["id"]
    before = len(client.get("/products").get_json())
    invalid = [
        {"name": "missing"},
        {"name": "x", "price": -1, "stock": 1, "category_id": category_id},
        {"name": "x", "price": 1, "stock": -1, "category_id": category_id},
        {"name": "x", "price": 1, "stock": 1.5, "category_id": category_id},
        {"name": "x", "price": 1, "stock": 1, "category_id": 999999},
    ]
    for payload in invalid:
        response = client.post("/products", json=payload)
        assert response.status_code == 400
        assert "error" in response.get_json()
    assert len(client.get("/products").get_json()) == before


def test_stats_reconcile_with_current_product_collection(client):
    _setup(client)
    products = client.get("/products").get_json()
    stats = client.get("/products/stats").get_json()
    assert stats["total_products"] == len(products)
    assert stats["total_categories"] == len(client.get("/categories").get_json())
    assert stats["avg_price"] == round(
        sum(item["price"] for item in products) / len(products), 2
    )
    assert stats["total_stock"] == sum(item["stock"] for item in products)
    cheapest = min(products, key=lambda item: item["price"])
    expensive = max(products, key=lambda item: item["price"])
    assert stats["cheapest"] == {
        "name": cheapest["name"],
        "price": cheapest["price"],
    }
    assert stats["most_expensive"] == {
        "name": expensive["name"],
        "price": expensive["price"],
    }


def test_unknown_product_is_json_404(client):
    _setup(client)
    response = client.get("/products/99999999")
    assert response.status_code == 404
    assert "error" in response.get_json()
