#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
app.json.sort_keys = False

LOG_DIR = 'logs'
LOG_FILE = os.path.join(LOG_DIR, 'app.log')

VALID_LEVELS = {'INFO', 'WARN', 'ERROR', 'DEBUG', 'CRITICAL'}
VALID_MODULES = {'api', 'db', 'auth', 'system'}

SEED_DATA = [
    {"level": "INFO", "module": "api", "message": "Request received", "timestamp": "2026-01-01T12:00:00"},
    {"level": "INFO", "module": "api", "message": "Processing data", "timestamp": "2026-01-01T12:00:01"},
    {"level": "WARN", "module": "db", "message": "Slow query detected", "timestamp": "2026-01-01T12:00:02"},
    {"level": "ERROR", "module": "db", "message": "Connection timeout", "timestamp": "2026-01-01T12:00:03"},
    {"level": "INFO", "module": "auth", "message": "User login", "timestamp": "2026-01-01T12:00:04"},
    {"level": "INFO", "module": "api", "message": "Response sent", "timestamp": "2026-01-01T12:00:05"},
    {"level": "WARN", "module": "auth", "message": "Failed login attempt", "timestamp": "2026-01-01T12:00:06"},
    {"level": "ERROR", "module": "api", "message": "Internal server error", "timestamp": "2026-01-01T12:00:07"},
    {"level": "INFO", "module": "db", "message": "Query completed", "timestamp": "2026-01-01T12:00:08"},
    {"level": "INFO", "module": "db", "message": "Connection pool refreshed", "timestamp": "2026-01-01T12:00:09"},
    {"level": "WARN", "module": "system", "message": "Disk space low", "timestamp": "2026-01-01T12:00:10"},
    {"level": "DEBUG", "module": "api", "message": "Debug message", "timestamp": "2026-01-01T12:00:11"},
]


def read_logs():
    if not os.path.exists(LOG_FILE):
        return []
    entries = []
    with open(LOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


@app.route('/setup')
def setup():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f:
            for entry in SEED_DATA:
                f.write(json.dumps(entry) + '\n')
    return jsonify({"status": "ok"})


@app.route('/logs')
def list_logs():
    entries = read_logs()
    level = request.args.get('level')
    module = request.args.get('module')
    limit = request.args.get('limit')
    if level:
        entries = [e for e in entries if e.get('level') == level]
    if module:
        entries = [e for e in entries if e.get('module') == module]
    if limit is not None:
        try:
            entries = entries[:int(limit)]
        except (ValueError, TypeError):
            pass
    return jsonify(entries)


@app.route('/logs/stats')
def log_stats():
    entries = read_logs()
    total = len(entries)
    by_level = {}
    by_module = {}
    for e in entries:
        lvl = e.get('level', 'UNKNOWN')
        mod = e.get('module', 'UNKNOWN')
        by_level[lvl] = by_level.get(lvl, 0) + 1
        by_module[mod] = by_module.get(mod, 0) + 1
    return jsonify({"total": total, "by_level": by_level, "by_module": by_module})


@app.route('/logs/analyze')
def analyze_logs():
    entries = read_logs()
    total = len(entries)
    if total == 0:
        return jsonify({"error_rate": 0, "top_modules": {}, "levels_distribution": {}})
    error_count = sum(1 for e in entries if e.get('level') == 'ERROR')
    error_rate = error_count / total
    by_module = {}
    by_level = {}
    for e in entries:
        mod = e.get('module', 'UNKNOWN')
        lvl = e.get('level', 'UNKNOWN')
        by_module[mod] = by_module.get(mod, 0) + 1
        by_level[lvl] = by_level.get(lvl, 0) + 1
    top_modules = dict(sorted(by_module.items(), key=lambda x: -x[1]))
    levels_distribution = {k: v / total for k, v in by_level.items()}
    return jsonify({"error_rate": error_rate, "top_modules": top_modules, "levels_distribution": levels_distribution})


@app.route('/logs', methods=['POST'])
def add_log():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    level = data.get('level')
    module = data.get('module')
    message = data.get('message')
    if not level or not module or not message:
        return jsonify({"error": "Missing required fields: level, module, message"}), 400
    if level not in VALID_LEVELS:
        return jsonify({"error": f"Invalid level: {level}"}), 400
    if module not in VALID_MODULES:
        return jsonify({"error": f"Invalid module: {module}"}), 400
    entry = {
        "level": level,
        "module": module,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    return jsonify(entry), 201
PYEOF
