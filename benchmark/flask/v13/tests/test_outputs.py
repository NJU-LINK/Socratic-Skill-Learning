import json
import sys
from collections import Counter
from datetime import datetime

import pytest

sys.path.insert(0, "/app")
from solve import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return app.test_client()


def _setup(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def _entries():
    with open("logs/app.log", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_setup_seeds_valid_mixed_jsonl_and_is_idempotent(client):
    _setup(client)
    entries = _entries()
    assert len(entries) >= 10
    assert {"INFO", "WARN", "ERROR"} <= {entry["level"] for entry in entries}
    assert {"api", "db", "auth"} <= {entry["module"] for entry in entries}
    for entry in entries:
        assert set(entry) >= {"level", "module", "message", "timestamp"}
        datetime.fromisoformat(entry["timestamp"])
    before = open("logs/app.log", "rb").read()
    _setup(client)
    assert open("logs/app.log", "rb").read() == before


def test_list_filters_are_and_combined_then_limited(client):
    _setup(client)
    all_entries = client.get("/logs").get_json()
    target_level = all_entries[0]["level"]
    target_module = all_entries[0]["module"]
    expected = [
        entry
        for entry in all_entries
        if entry["level"] == target_level and entry["module"] == target_module
    ][:2]
    response = client.get(
        f"/logs?level={target_level}&module={target_module}&limit=2"
    )
    assert response.status_code == 200
    assert response.get_json() == expected


def test_post_appends_exact_entry_and_get_reads_it_fresh(client):
    _setup(client)
    payload = {"level": "CRITICAL", "module": "system", "message": "disk full"}
    response = client.post("/logs", json=payload)
    assert response.status_code == 201
    created = response.get_json()
    assert {key: created[key] for key in payload} == payload
    datetime.fromisoformat(created["timestamp"])
    assert _entries()[-1] == created
    assert client.get("/logs").get_json()[-1] == created


def test_post_validation_does_not_append(client):
    _setup(client)
    before = open("logs/app.log", "rb").read()
    invalid = [
        {},
        {"level": "INFO", "module": "api"},
        {"level": "INVALID", "module": "api", "message": "x"},
        {"level": "INFO", "module": "invalid", "message": "x"},
    ]
    for payload in invalid:
        response = client.post("/logs", json=payload)
        assert response.status_code == 400
        assert "error" in response.get_json()
    assert open("logs/app.log", "rb").read() == before


def test_stats_exactly_reconcile_with_file(client):
    _setup(client)
    entries = _entries()
    response = client.get("/logs/stats")
    assert response.status_code == 200
    assert response.get_json() == {
        "total": len(entries),
        "by_level": dict(Counter(entry["level"] for entry in entries)),
        "by_module": dict(Counter(entry["module"] for entry in entries)),
    }


def test_analysis_exactly_reconciles_and_preserves_tie_order(client):
    _setup(client)
    entries = _entries()
    by_level = Counter(entry["level"] for entry in entries)
    by_module = Counter(entry["module"] for entry in entries)
    first_seen = list(dict.fromkeys(entry["module"] for entry in entries))
    expected_modules = sorted(
        first_seen, key=lambda module: -by_module[module]
    )
    data = client.get("/logs/analyze").get_json()
    assert data["error_rate"] == pytest.approx(by_level["ERROR"] / len(entries))
    assert data["levels_distribution"] == pytest.approx(
        {level: count / len(entries) for level, count in by_level.items()}
    )
    assert list(data["top_modules"]) == expected_modules
    assert data["top_modules"] == {
        module: by_module[module] for module in expected_modules
    }


def test_empty_file_returns_zeroed_stats_and_analysis(client):
    assert client.get("/logs/stats").get_json() == {
        "total": 0,
        "by_level": {},
        "by_module": {},
    }
    assert client.get("/logs/analyze").get_json() == {
        "error_rate": 0,
        "top_modules": {},
        "levels_distribution": {},
    }
