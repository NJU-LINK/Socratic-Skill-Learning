import os
import sqlite3
import sys

import pytest

sys.path.insert(0, "/app")
from solve import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return app.test_client()


def _add(client, item, quantity, price):
    return client.post(
        "/cart/add",
        json={"item": item, "quantity": quantity, "price": price},
    )


def test_add_creates_persistent_cart_line(client):
    response = _add(client, "Apple", 2, 1.5)
    assert response.status_code == 201
    data = response.get_json()
    assert data["item"] == "Apple"
    assert data["quantity"] == 2
    assert data["price"] == 1.5
    assert isinstance(data["id"], int)
    with sqlite3.connect("cart.db") as connection:
        assert connection.execute(
            "SELECT item, quantity, price FROM cart_items"
        ).fetchall() == [("Apple", 2, 1.5)]


def test_duplicate_add_accumulates_quantity_and_retains_original_price(client):
    first = _add(client, "Coffee", 2, 4.25).get_json()
    response = _add(client, "Coffee", 3, 99.0)
    assert response.status_code == 201
    data = response.get_json()
    assert data == {
        "id": first["id"],
        "item": "Coffee",
        "quantity": 5,
        "price": 4.25,
    }
    assert len(client.get("/cart").get_json()) == 1


def test_list_and_total_reconcile_with_distinct_line_count(client):
    _add(client, "A", 2, 1.25)
    _add(client, "B", 3, 2.0)
    lines = client.get("/cart").get_json()
    assert {line["item"] for line in lines} == {"A", "B"}
    assert all(
        line["total"] == round(line["quantity"] * line["price"], 2)
        for line in lines
    )
    assert client.get("/cart/total").get_json() == {
        "total": 8.5,
        "item_count": 2,
    }


def test_update_replaces_quantity_and_invalid_update_preserves_state(client):
    created = _add(client, "Mutable", 2, 3.0).get_json()
    response = client.put(f"/cart/{created['id']}", json={"quantity": 7})
    assert response.status_code == 200
    assert response.get_json()["quantity"] == 7
    for quantity in (0, -1, 1.5):
        response = client.put(
            f"/cart/{created['id']}", json={"quantity": quantity}
        )
        assert response.status_code == 400
    assert client.get("/cart").get_json()[0]["quantity"] == 7


def test_delete_removes_line_and_unknown_ids_are_404(client):
    created = _add(client, "Gone", 1, 2.0).get_json()
    assert client.delete(f"/cart/{created['id']}").get_json() == {
        "status": "deleted"
    }
    assert client.get("/cart").get_json() == []
    assert client.delete(f"/cart/{created['id']}").status_code == 404
    assert client.put("/cart/999999", json={"quantity": 2}).status_code == 404


def test_checkout_returns_snapshot_and_empties_cart(client):
    _add(client, "First", 2, 1.5)
    _add(client, "Second", 1, 4.0)
    response = client.post("/cart/checkout")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "checked_out"
    assert data["total"] == 7.0
    assert {
        (line["item"], line["quantity"], line["price"], line["total"])
        for line in data["items"]
    } == {
        ("First", 2, 1.5, 3.0),
        ("Second", 1, 4.0, 4.0),
    }
    assert client.get("/cart").get_json() == []
    empty = client.post("/cart/checkout")
    assert empty.status_code == 400
    assert empty.get_json() == {"error": "Cart is empty"}


def test_clear_is_idempotent(client):
    _add(client, "Disposable", 1, 1.0)
    assert client.get("/cart/clear").get_json() == {"status": "cleared"}
    assert client.get("/cart/clear").get_json() == {"status": "cleared"}
    assert client.get("/cart").get_json() == []


def test_invalid_adds_do_not_create_cart_lines(client):
    invalid = [
        {"item": "missing"},
        {"item": "x", "quantity": 0, "price": 1},
        {"item": "x", "quantity": 1.5, "price": 1},
        {"item": "x", "quantity": 1, "price": 0},
        {"item": "x", "quantity": 1, "price": "bad"},
    ]
    for payload in invalid:
        response = client.post("/cart/add", json=payload)
        assert response.status_code == 400
        assert "error" in response.get_json()
    assert client.get("/cart").get_json() == []
