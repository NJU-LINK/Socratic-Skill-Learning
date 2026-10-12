---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  across multiple behaviorally coupled endpoints. Covers all persistence models
  (sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl), validation
  patterns, atomic state transitions, idempotent setup, and error handling with
  proper HTTP status codes. Evaluated via Flask test_client.
---

# Flask Stateful JSON Service

## Family Overview

Every task in this family requires building a Flask application (`app` in
`/app/solve.py`) that implements a JSON HTTP service with **mutable domain
state** shared across multiple coupled endpoints. Tests import `app` and use
`app.test_client()`.

## Systematic Approach

### Step 1: Parse the Task Specification

Extract these elements from the task description:

| Element | What to look for |
|---------|-----------------|
| **Resources** | Entity names, fields, types, constraints (e.g., CHECK constraints) |
| **Endpoints** | Route paths, HTTP methods, request format, response schema |
| **Persistence** | Which model: sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl |
| **State transitions** | Atomicity requirements, idempotency, cascading effects |
| **Validation rules** | Required fields, type/range checks, existence checks, conflict detection |
| **Error responses** | Exact error messages, HTTP status codes for each failure mode |

### Step 2: Choose Persistence Strategy

#### sqlite3 (raw SQLite)

```python
import sqlite3
import os
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DB_PATH = os.path.join(os.getcwd(), 'database.db')

def get_db():
    if 'db' not in g:
        # CRITICAL: isolation_level=None disables Python's implicit transaction
        # management. Without this, Python auto-issues BEGIN before first DML,
        # and any explicit db.execute('BEGIN') will crash with
        # 'OperationalError: cannot start a transaction within a transaction'.
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row  # Access columns by name
        g.db.execute("PRAGMA foreign_keys = ON")  # Enable FK enforcement
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Key patterns:**
- **Always use `isolation_level=None`** — this gives you full manual control over transactions. Python's default (`isolation_level=""`) auto-starts transactions before DML, which conflicts with explicit `BEGIN` statements.
- Use `g` for per-request DB connections
- `row_factory = sqlite3.Row` for dict-like row access
- Manual `BEGIN`/`COMMIT`/`ROLLBACK` for atomic operations (see Step 5)
- `CREATE TABLE IF NOT EXISTS` for idempotent DDL
- `INSERT OR IGNORE` for idempotent seed data (avoids SELECT COUNT check, no race window)
- `PRAGMA foreign_keys = ON` to enforce FK constraints
- Clean up DB file in tests: remove before each test run

#### flask_sqlalchemy

```python
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    balance = db.Column(db.Float, nullable=False)

# If you need to create tables at import time (before any request):
with app.app_context():
    db.create_all()

# In routes:
# db.session.add(obj)
# db.session.commit()
# db.session.rollback()
# Model.query.filter_by(...).first()
```

**Key patterns:**
- Define models as classes inheriting from `db.Model`
- Use `db.session` for transactions (auto-begin, explicit commit/rollback)
- `db.create_all()` for setup (idempotent)
- Query with `.query.filter_by()`, `.get()`, `.all()`
- **App context**: `db.create_all()`, `db.session`, and model queries all require an active Flask application context. Inside route handlers, the request context provides this automatically. Outside route handlers (e.g., at import time, in test setup code, or in CLI commands), wrap with `with app.app_context():` or you'll get `RuntimeError: Working outside of application context`.
- **Idempotent seeding**: Use `db.session.merge()` or check `db.session.get(Model, id)` before adding:
  ```python
  if db.session.get(Account, 1) is None:
      db.session.add(Account(id=1, owner='Alice', balance=100.0))
      db.session.commit()
  ```
  Note: `Model.query.get()` is legacy in SQLAlchemy 2.0+. Prefer `db.session.get(Model, id)` or `db.session.execute(db.select(Model).filter_by(id=id)).scalar_one_or_none()`.

#### in_memory (process-local dictionaries)

```python
from flask import Flask, request, jsonify
import copy
import threading

app = Flask(__name__)

# Global state
store = {
    'entities': {},  # id -> entity dict
    'next_id': 1,
}
lock = threading.Lock()

def reset_state():
    global store
    store = {'entities': {}, 'next_id': 1}
```

**Key patterns:**
- Use module-level dicts for state
- `threading.Lock()` for thread safety if needed
- `copy.deepcopy()` when returning data to avoid mutation by callers
- Reset function for test isolation
- State persists across requests within the same process (test_client shares the process)

#### file_manifest

```python
import json
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_DIR = os.path.join(os.getcwd(), 'data')
MANIFEST_PATH = os.path.join(DATA_DIR, 'manifest.json')

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_manifest(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, 'w') as f:
        json.dump(data, f, indent=2)
```

**Key patterns:**
- JSON file as the single source of truth
- Read-modify-write with file locking for atomicity
- Manifest tracks metadata (list of files, counters, etc.)
- Atomic writes: write to temp file, then rename

#### jsonl

```python
import json
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_FILE = os.path.join(os.getcwd(), 'data.jsonl')

def read_all():
    records = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records

def append_record(record):
    with open(DATA_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

def rewrite_all(records):
    with open(DATA_FILE, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')
```

**Key patterns:**
- Append-only log for new records
- Full rewrite when updating/deleting (or maintain index)
- Each line is a valid JSON object
- Read all lines to reconstruct state

### Step 3: Implement Endpoints

#### Setup / Lifecycle Endpoint

Always make setup **idempotent**:

```python
@app.route('/setup', methods=['GET'])
def setup():
    # For sqlite3: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE for seeds
    # For flask_sqlalchemy: db.create_all() + conditional seed
    # For in_memory: reset to initial state
    # For file/jsonl: create/reset files
    return jsonify({"status": "ok"})
```

**Idempotency patterns:**
- SQLite: `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` for seed data (no SELECT needed, no race window, handles partial state)
- SQLAlchemy: `db.create_all()` is inherently idempotent; use `db.session.merge()` or check `db.session.get(Model, id)` before adding seeds
- In-memory: check if already initialized, or always reset
- File-based: check if file exists, or overwrite

**Preferred SQLite seed pattern:**
```python
@app.route('/setup', methods=['GET'])
def setup():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY, owner TEXT NOT NULL, balance REAL NOT NULL
    )''')
    # INSERT OR IGNORE: idempotent, no race, handles partial state
    db.execute('INSERT OR IGNORE INTO accounts (id, owner, balance) VALUES (1, ?, 100.0)', ('Alice',))
    db.execute('INSERT OR IGNORE INTO accounts (id, owner, balance) VALUES (2, ?, 50.0)', ('Bob',))
    return jsonify({"status": "ok"})
```

#### CRUD Endpoints

```python
# CREATE
@app.route('/resource', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    # Validate required fields
    # Check uniqueness constraints
    # Create and persist
    return jsonify(created_resource), 201

# READ (single)
@app.route('/resource/<int:id>', methods=['GET'])
def get_resource(id):
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(resource)

# READ (list with filters)
@app.route('/resources', methods=['GET'])
def list_resources():
    # Apply query parameter filters
    filter_field = request.args.get('field')
    results = query_all(filter_field=filter_field)
    return jsonify(results)

# UPDATE
@app.route('/resource/<int:id>', methods=['PUT', 'PATCH'])
def update_resource(id):
    data = request.get_json(silent=True)
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    # Apply updates, validate
    return jsonify(updated_resource)

# DELETE
@app.route('/resource/<int:id>', methods=['DELETE'])
def delete_resource(id):
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    remove(id)
    return jsonify({"status": "deleted"}), 200
```

### Step 4: Implement Validation and Error Handling

#### Standard validation pattern:

```python
@app.route('/action', methods=['POST'])
def action():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    # 1. Check required fields exist
    required = ['field_a', 'field_b']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # 2. Type validation
    if not isinstance(data['field_a'], int):
        return jsonify({"error": "field_a must be an integer"}), 400

    # 3. Range/value validation
    if data['amount'] <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    # 4. Existence validation (references to other resources)
    resource = lookup(data['resource_id'])
    if resource is None:
        return jsonify({"error": "Resource not found"}), 404

    # 5. Business logic validation
    if resource['balance'] < data['amount']:
        return jsonify({"error": "Insufficient balance"}), 400

    # 6. Conflict validation
    if data['source'] == data['destination']:
        return jsonify({"error": "Source and destination must differ"}), 400

    # Perform the action...
```

#### HTTP status code conventions:

| Status | When to use |
|--------|-------------|
| 200 | Successful GET, PUT, or state-changing POST |
| 201 | Successful resource creation |
| 204 | Successful deletion (no body) or sometimes 200 with message |
| 400 | Missing fields, invalid types/ranges, business rule violations |
| 404 | Referenced resource does not exist |
| 409 | Conflict (duplicate, unique constraint violation) |
| 500 | Internal server error (unexpected exceptions) |

### Step 5: Atomic State Transitions

#### sqlite3 atomic operations:

**Requires `isolation_level=None` in `get_db()` (see Step 2).**

```python
def atomic_transfer(db, from_id, to_id, amount):
    db.execute('BEGIN')
    try:
        # All mutations here
        db.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, from_id))
        db.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, to_id))
        db.execute('INSERT INTO transactions (from_id, to_id, amount) VALUES (?, ?, ?)',
                   (from_id, to_id, amount))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
```

**Why `isolation_level=None` is mandatory here:** Python's `sqlite3.connect()` defaults to `isolation_level=""` (deferred), which auto-issues `BEGIN` before the first DML statement. If you then call `db.execute('BEGIN')` explicitly, it crashes with `OperationalError: cannot start a transaction within a transaction`. Setting `isolation_level=None` disables this implicit behavior and gives you full manual control.

#### flask_sqlalchemy atomic operations:

```python
def atomic_operation():
    try:
        # All mutations via db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
```

#### in_memory atomic operations:

```python
# Use a lock to ensure atomicity
with lock:
    # All state mutations here
    pass
```

### Step 6: Response Formatting

Always return JSON with `jsonify()`. Match the exact response schema from the task spec:

```python
# Success response - match exact field names from spec
return jsonify({
    "id": resource['id'],
    "name": resource['name'],
    # ... exact fields specified
}), 200

# Error response - match exact error message from spec
return jsonify({"error": "Exact error message from spec"}), 400
```

## Critical Implementation Notes

### Test Client Usage

Tests will do:
```python
from solve import app
client = app.test_client()
resp = client.get('/setup')
resp = client.post('/endpoint', json={...})
```

The `app` object must be importable from `solve.py` at module level.

### Database File Location

For file-based persistence (sqlite3, file_manifest, jsonl):
- Use `os.path.join(os.getcwd(), 'filename')` for the DB path
- Tests may run from `/app` as CWD
- Clean up DB files between test runs if needed

### Idempotent Setup

The `/setup` endpoint must be safely callable multiple times:
- Use `CREATE TABLE IF NOT EXISTS` for SQL
- Use `INSERT OR IGNORE` for seed rows (no SELECT COUNT needed)
- For in-memory: either always reset or check initialization flag

### Request Parsing

```python
# JSON body
data = request.get_json(silent=True)  # Returns None if not valid JSON

# Query parameters
value = request.args.get('key')  # Returns None if missing
value = request.args.get('key', default)  # With default

# URL parameters
@app.route('/resource/<int:id>')  # Auto-converts to int
@app.route('/resource/<path:filepath>')  # Captures slashes
```

### Common Pitfalls

1. **Forgetting `db.commit()`** after INSERT/UPDATE/DELETE in raw sqlite3
2. **Not handling `get_json(silent=True)` returning None** for malformed JSON
3. **Not checking for None** when accessing optional fields with `.get()`
4. **Race conditions** in in-memory stores without locks
5. **Non-idempotent setup** that fails on second call
6. **Forgetting to clean up** DB files between test runs (use `os.remove` in setup if needed)
7. **Returning wrong status codes** (e.g., 200 instead of 201 for creation)
8. **Not matching exact error messages** from the spec
9. **SQLite `isolation_level` trap**: Using `sqlite3.connect(path)` without `isolation_level=None` causes Python to auto-start transactions before DML. Any subsequent explicit `db.execute('BEGIN')` crashes with `OperationalError: cannot start a transaction within a transaction`. Always use `isolation_level=None` when you need manual transaction control.
10. **Flask-SQLAlchemy app context**: `db.create_all()`, `db.session`, and model queries all require an active Flask application context. Inside route handlers this is automatic, but any code outside a request handler (import-time setup, test fixtures, CLI commands) needs `with app.app_context():` or it raises `RuntimeError: Working outside of application context`.
11. **Non-atomic seed with SELECT COUNT + INSERT**: Using `SELECT COUNT(*)` to check before seeding is fragile — it has a race window and doesn't fix partial state. Use `INSERT OR IGNORE` (sqlite3) or `db.session.merge()` (SQLAlchemy) for truly idempotent seeding.

## Checklist Before Submitting

- [ ] `app` is defined at module level in `/app/solve.py`
- [ ] All routes from the spec are implemented with correct HTTP methods
- [ ] Setup endpoint is idempotent
- [ ] All validation rules from the spec are implemented
- [ ] Error responses use exact messages and status codes from spec
- [ ] Success responses match the exact schema from spec
- [ ] State transitions are atomic where required
- [ ] Persistence works correctly (DB file path, table creation, etc.)
- [ ] No leftover state from previous test runs (clean DB in setup)
- [ ] sqlite3 connections use `isolation_level=None` for manual transaction control
- [ ] Flask-SQLAlchemy code uses `app.app_context()` when outside request handlers
