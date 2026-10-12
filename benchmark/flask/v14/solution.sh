#!/bin/bash
set -uo pipefail

cat > /app/solve.py <<'PYEOF'
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

UPLOAD_DIR = "uploads"
MANIFEST_PATH = os.path.join(UPLOAD_DIR, "manifest.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_setup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
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


def _valid_filename(filename):
    return (
        isinstance(filename, str)
        and bool(filename)
        and ".." not in filename
        and "/" not in filename
        and "\\" not in filename
    )


def _path(filename):
    return os.path.join(UPLOAD_DIR, filename)


@app.get("/setup")
def setup():
    _ensure_setup()
    return jsonify({"status": "ok"})


@app.post("/files/upload")
def upload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not _valid_filename(data.get("filename")):
        return jsonify({"error": "Missing or invalid filename"}), 400
    if not isinstance(data.get("content"), str):
        return jsonify({"error": "Missing or invalid content"}), 400
    if "type" in data and not isinstance(data["type"], str):
        return jsonify({"error": "Invalid type"}), 400

    filename = data["filename"]
    content = data["content"]
    manifest = _read_manifest()
    if filename in manifest:
        return jsonify({"error": "File already exists"}), 409

    now = _now()
    metadata = {
        "filename": filename,
        "size": len(content.encode("utf-8")),
        "type": data.get("type", "unknown"),
        "created_at": now,
        "updated_at": now,
    }
    with open(_path(filename), "w", encoding="utf-8") as handle:
        handle.write(content)
    manifest[filename] = metadata
    _write_manifest(manifest)
    return jsonify(metadata), 201


@app.get("/files")
def list_files():
    return jsonify(list(_read_manifest().values()))


@app.get("/files/download/<path:filename>")
def download(filename):
    manifest = _read_manifest()
    if filename not in manifest or not os.path.isfile(_path(filename)):
        return jsonify({"error": "File not found"}), 404
    with open(_path(filename), encoding="utf-8") as handle:
        content = handle.read()
    return jsonify(
        {
            "filename": filename,
            "content": content,
            "metadata": manifest[filename],
        }
    )


@app.get("/files/metadata/<path:filename>")
def metadata(filename):
    manifest = _read_manifest()
    if filename not in manifest:
        return jsonify({"error": "File not found"}), 404
    return jsonify(manifest[filename])


@app.delete("/files/<path:filename>")
def delete(filename):
    manifest = _read_manifest()
    if filename not in manifest:
        return jsonify({"error": "File not found"}), 404
    if os.path.exists(_path(filename)):
        os.remove(_path(filename))
    del manifest[filename]
    _write_manifest(manifest)
    return jsonify({"status": "deleted"})


@app.post("/files/batch-delete")
def batch_delete():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("filenames"), list):
        return jsonify({"error": "Filenames are required"}), 400
    manifest = _read_manifest()
    deleted = []
    not_found = []
    for filename in data["filenames"]:
        if filename in manifest:
            if os.path.exists(_path(filename)):
                os.remove(_path(filename))
            del manifest[filename]
            deleted.append(filename)
        else:
            not_found.append(filename)
    _write_manifest(manifest)
    return jsonify({"deleted": deleted, "not_found": not_found})


@app.get("/files/search")
def search():
    query = request.args.get("q", "").casefold()
    return jsonify(
        [
            metadata
            for filename, metadata in _read_manifest().items()
            if query in filename.casefold()
        ]
    )
PYEOF
