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


def _upload(client, filename, content="content", file_type=None):
    payload = {"filename": filename, "content": content}
    if file_type is not None:
        payload["type"] = file_type
    return client.post("/files/upload", json=payload)


def test_setup_is_idempotent_and_preserves_manifest(client):
    assert client.get("/setup").get_json() == {"status": "ok"}
    assert json.loads(open("uploads/manifest.json", encoding="utf-8").read()) == {}
    _upload(client, "kept.txt")
    before = open("uploads/manifest.json", "rb").read()
    assert client.get("/setup").get_json() == {"status": "ok"}
    assert open("uploads/manifest.json", "rb").read() == before


def test_upload_uses_utf8_byte_size_and_persists_exact_metadata(client):
    content = "café 世界"
    response = _upload(client, "unicode.txt", content, "text")
    assert response.status_code == 201
    metadata = response.get_json()
    assert metadata["filename"] == "unicode.txt"
    assert metadata["size"] == len(content.encode("utf-8"))
    assert metadata["type"] == "text"
    datetime.fromisoformat(metadata["created_at"])
    datetime.fromisoformat(metadata["updated_at"])
    assert open("uploads/unicode.txt", encoding="utf-8").read() == content
    manifest = json.loads(open("uploads/manifest.json", encoding="utf-8").read())
    assert manifest["unicode.txt"] == metadata


def test_default_type_list_download_and_metadata_are_consistent(client):
    response = _upload(client, "plain.txt", "hello")
    assert response.get_json()["type"] == "unknown"
    listed = client.get("/files").get_json()
    assert listed == [response.get_json()]
    assert client.get("/files/metadata/plain.txt").get_json() == response.get_json()
    downloaded = client.get("/files/download/plain.txt").get_json()
    assert downloaded == {
        "filename": "plain.txt",
        "content": "hello",
        "metadata": response.get_json(),
    }


def test_duplicate_and_invalid_uploads_leave_state_unchanged(client):
    _upload(client, "stable.txt", "original")
    before = open("uploads/manifest.json", "rb").read()
    assert _upload(client, "stable.txt", "replacement").status_code == 409
    invalid = [
        {"content": "x"},
        {"filename": "../escape", "content": "x"},
        {"filename": "nested/file", "content": "x"},
        {"filename": "bad\\file", "content": "x"},
        {"filename": "", "content": "x"},
        {"filename": "numeric.txt", "content": 4},
    ]
    for payload in invalid:
        response = client.post("/files/upload", json=payload)
        assert response.status_code == 400
        assert "error" in response.get_json()
    assert open("uploads/stable.txt", encoding="utf-8").read() == "original"
    assert open("uploads/manifest.json", "rb").read() == before
    assert not os.path.exists("../escape")


def test_batch_delete_preserves_request_order_and_updates_both_stores(client):
    for filename in ("first.txt", "second.txt", "third.txt"):
        _upload(client, filename)
    response = client.post(
        "/files/batch-delete",
        json={
            "filenames": [
                "second.txt",
                "missing-a.txt",
                "first.txt",
                "missing-b.txt",
            ]
        },
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "deleted": ["second.txt", "first.txt"],
        "not_found": ["missing-a.txt", "missing-b.txt"],
    }
    assert {item["filename"] for item in client.get("/files").get_json()} == {
        "third.txt"
    }
    assert not os.path.exists("uploads/first.txt")
    assert not os.path.exists("uploads/second.txt")


def test_search_is_case_insensitive_filename_substring(client):
    _upload(client, "Quarterly_Report.TXT")
    _upload(client, "notes.txt")
    results = client.get("/files/search?q=REPORT").get_json()
    assert [item["filename"] for item in results] == ["Quarterly_Report.TXT"]


def test_delete_and_unknown_reads_keep_manifest_consistent(client):
    _upload(client, "gone.txt")
    assert client.delete("/files/gone.txt").get_json() == {"status": "deleted"}
    assert not os.path.exists("uploads/gone.txt")
    assert "gone.txt" not in json.loads(
        open("uploads/manifest.json", encoding="utf-8").read()
    )
    for path in (
        "/files/download/gone.txt",
        "/files/metadata/gone.txt",
        "/files/gone.txt",
    ):
        response = (
            client.delete(path)
            if path == "/files/gone.txt"
            else client.get(path)
        )
        assert response.status_code == 404
        assert "error" in response.get_json()


def test_batch_delete_requires_an_array(client):
    for payload in ({}, {"filenames": "one.txt"}):
        response = client.post("/files/batch-delete", json=payload)
        assert response.status_code == 400
        assert "error" in response.get_json()
