import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, "/app")
from solve import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return app.test_client()


def _create(client, title="alpha", content="Hello"):
    return client.post("/notes", json={"title": title, "content": content})


def test_setup_is_idempotent_and_does_not_overwrite_state(client):
    assert client.get("/setup").get_json() == {"status": "ok"}
    assert json.loads(open("notes/manifest.json", encoding="utf-8").read()) == {}
    _create(client)
    before = open("notes/manifest.json", "rb").read()
    assert client.get("/setup").get_json() == {"status": "ok"}
    assert open("notes/manifest.json", "rb").read() == before


def test_create_persists_unicode_content_and_exact_manifest_contract(client):
    content = "你好, café"
    response = _create(client, "unicode", content)
    assert response.status_code == 201
    metadata = response.get_json()
    assert metadata["title"] == "unicode"
    assert metadata["size"] == len(content.encode("utf-8"))
    datetime.fromisoformat(metadata["created_at"])
    datetime.fromisoformat(metadata["updated_at"])
    assert open("notes/unicode.txt", encoding="utf-8").read() == content
    manifest = json.loads(open("notes/manifest.json", encoding="utf-8").read())
    assert manifest == {"unicode": metadata}
    assert "unicode.txt" not in manifest


def test_list_and_get_return_current_content_and_metadata(client):
    _create(client, "one", "First")
    _create(client, "two", "Second")
    listed = client.get("/notes").get_json()
    assert {item["title"] for item in listed} == {"one", "two"}
    response = client.get("/notes/two")
    assert response.status_code == 200
    data = response.get_json()
    assert data["title"] == "two"
    assert data["content"] == "Second"
    assert data["metadata"]["title"] == "two"


def test_update_preserves_creation_and_updates_file_size(client):
    created = _create(client, "change", "old").get_json()
    content = "longer 世界"
    response = client.put("/notes/change", json={"content": content})
    assert response.status_code == 200
    updated = response.get_json()
    assert updated["created_at"] == created["created_at"]
    assert updated["size"] == len(content.encode("utf-8"))
    assert client.get("/notes/change").get_json()["content"] == content
    assert open("notes/change.txt", encoding="utf-8").read() == content


def test_search_is_case_insensitive_and_uses_current_file_contents(client):
    _create(client, "match", "Alpha NEEDLE beta")
    _create(client, "other", "unrelated")
    assert client.post("/notes/search", json={"query": "needle"}).get_json() == [
        "match"
    ]
    client.put("/notes/match", json={"content": "removed"})
    assert client.post("/notes/search", json={"query": "NEEDLE"}).get_json() == []


def test_duplicate_and_invalid_creates_leave_existing_state_unchanged(client):
    _create(client, "stable", "original")
    before_manifest = open("notes/manifest.json", "rb").read()
    assert _create(client, "stable", "replacement").status_code == 409
    for payload in (
        {"content": "missing"},
        {"title": "../escape", "content": "x"},
        {"title": "bad/name", "content": "x"},
        {"title": "bad\\name", "content": "x"},
        {"title": "", "content": "x"},
        {"title": "numeric-content", "content": 4},
    ):
        assert client.post("/notes", json=payload).status_code == 400
    assert open("notes/stable.txt", encoding="utf-8").read() == "original"
    assert open("notes/manifest.json", "rb").read() == before_manifest
    assert not os.path.exists("../escape.txt")


def test_delete_removes_file_and_manifest_entry(client):
    _create(client, "gone", "delete me")
    assert client.delete("/notes/gone").get_json() == {"status": "deleted"}
    assert not os.path.exists("notes/gone.txt")
    assert "gone" not in json.loads(
        open("notes/manifest.json", encoding="utf-8").read()
    )
    assert client.get("/notes/gone").status_code == 404
    assert client.delete("/notes/gone").status_code == 404


def test_missing_update_and_search_fields_are_json_errors(client):
    _create(client)
    for response in (
        client.put("/notes/alpha", json={}),
        client.put("/notes/missing", json={"content": "x"}),
        client.post("/notes/search", json={}),
    ):
        assert response.status_code in (400, 404)
        assert "error" in response.get_json()
