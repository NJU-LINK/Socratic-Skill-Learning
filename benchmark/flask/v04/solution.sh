#!/bin/bash
set -uo pipefail

cat > /app/solve.py <<'PYEOF'
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

NOTES_DIR = "notes"
MANIFEST_PATH = os.path.join(NOTES_DIR, "manifest.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_setup():
    os.makedirs(NOTES_DIR, exist_ok=True)
    if not os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
            json.dump({}, handle)


def _read_manifest():
    _ensure_setup()
    with open(MANIFEST_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _write_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)


def _valid_title(title):
    return (
        isinstance(title, str)
        and bool(title)
        and ".." not in title
        and "/" not in title
        and "\\" not in title
    )


def _note_path(title):
    return os.path.join(NOTES_DIR, f"{title}.txt")


@app.get("/setup")
def setup():
    _ensure_setup()
    return jsonify({"status": "ok"})


@app.post("/notes")
def create_note():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not _valid_title(data.get("title")):
        return jsonify({"error": "Missing or invalid title"}), 400
    if not isinstance(data.get("content"), str):
        return jsonify({"error": "Missing or invalid content"}), 400

    title = data["title"]
    content = data["content"]
    manifest = _read_manifest()
    if title in manifest:
        return jsonify({"error": "Note already exists"}), 409

    now = _now()
    metadata = {
        "title": title,
        "created_at": now,
        "updated_at": now,
        "size": len(content.encode("utf-8")),
    }
    with open(_note_path(title), "w", encoding="utf-8") as handle:
        handle.write(content)
    manifest[title] = metadata
    _write_manifest(manifest)
    return jsonify(metadata), 201


@app.get("/notes")
def list_notes():
    return jsonify(list(_read_manifest().values()))


@app.get("/notes/<title>")
def get_note(title):
    manifest = _read_manifest()
    path = _note_path(title)
    if title not in manifest or not os.path.isfile(path):
        return jsonify({"error": "Note not found"}), 404
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    return jsonify({"title": title, "content": content, "metadata": manifest[title]})


@app.put("/notes/<title>")
def update_note(title):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        return jsonify({"error": "Missing or invalid content"}), 400
    manifest = _read_manifest()
    if title not in manifest:
        return jsonify({"error": "Note not found"}), 404

    content = data["content"]
    with open(_note_path(title), "w", encoding="utf-8") as handle:
        handle.write(content)
    manifest[title]["updated_at"] = _now()
    manifest[title]["size"] = len(content.encode("utf-8"))
    _write_manifest(manifest)
    return jsonify(manifest[title])


@app.delete("/notes/<title>")
def delete_note(title):
    manifest = _read_manifest()
    if title not in manifest:
        return jsonify({"error": "Note not found"}), 404
    path = _note_path(title)
    if os.path.exists(path):
        os.remove(path)
    del manifest[title]
    _write_manifest(manifest)
    return jsonify({"status": "deleted"})


@app.post("/notes/search")
def search_notes():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("query"), str):
        return jsonify({"error": "Query is required"}), 400
    query = data["query"].casefold()
    results = []
    for title in _read_manifest():
        path = _note_path(title)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            if query in handle.read().casefold():
                results.append(title)
    return jsonify(results)
PYEOF
