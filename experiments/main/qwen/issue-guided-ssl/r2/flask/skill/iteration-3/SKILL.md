---
name: flask
description: >
  Build stateful JSON HTTP services with Flask. Covers all five persistence models
  (SQLite3, Flask-SQLAlchemy, in-memory dicts, file manifest, JSONL) with correct
  transaction semantics, idempotent setup endpoints, CRUD operations, atomic state
  transitions, validation ordering, query parameter handling, and structured error
  contracts. Generalizes to any resource model (accounts, tasks, notes, catalogs,
  carts, URL mappings, logs) with mutable shared state.
---

# Flask Stateful JSON HTTP Service

## Family Invariants

Every case in this family implements a JSON HTTP service where:
- Requests share mutable domain state (not stateless)
- Multiple behaviorally coupled endpoints, or a middleware + lifecycle endpoint
- State is persisted (SQLite3, Flask-SQLAlchemy, in-memory dicts, file manifest, or JSONL)
- The Flask app object is named `app` and evaluated via `app.test_client()`
- All responses are JSON with appropriate HTTP status codes
- Error messages must match the task specification exactly

## Architecture Template

### File Structure
```
/app/solve.py   # Flask app with `app` object, all routes, persistence logic
```

### Application Skeleton
```python
import sqlite3  # or use in-memory dicts
import os
from flask import Flask, request, jsonify, g, redirect

app = Flask(__name__)

# For SQLite3:
def get_db():
    """Per-request database connection via Flask g context."""
    if 'db' not in g:
        db_path = os.path.join(os.getcwd(), '<dbname>.db')
        g.db = sqlite3.connect(db_path, isolation_level=None)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# For in-memory:
# state = {"resources": {}, "counter": 0}
# No teardown needed
```

### Request Body Parsing

Always use `force=True, silent=True` with `get_json()`:

```python
data = request.get_json(force=True, silent=True) or {}
```

- **`force=True`**: Parse JSON regardless of Content-Type header. Flask's test client doesn't always set `application/json`, and without this, `get_json()` returns `None` for requests with other Content-Types.
- **`silent=True`**: Return `None` instead of raising `BadRequest` on malformed input. This ensures your validation code controls the error response, not Flask's default error handler.
- **`or {}`**: Convert `None` (from parse failure) to an empty dict so missing-field checks work uniformly.

Without this pattern:
- A test sending `{"from_id": 1}` without Content-Type → `get_json()` returns `None` → your code gets `NoneType` instead of a dict
- Malformed JSON raises `BadRequest` → Flask returns HTML error page, not your JSON error contract

## Persistence Models

### SQLite3 (persistence_model: sqlite3)

#### Critical: Transaction Semantics

Python's `sqlite3` module has a default `isolation_level=""` (DEFERRED) that **auto-issues BEGIN before DML** (INSERT/UPDATE/DELETE) but **NOT before SELECT**. This means a SELECT-then-UPDATE sequence is NOT atomic by default — the read happens outside any transaction.

**The fix**: Always use `isolation_level=None` (manual/autocommit mode) and manage transactions explicitly:

```python
g.db = sqlite3.connect(db_path, isolation_level=None)
```

#### Atomic Operation Template (BEGIN IMMEDIATE)

For any read-check-write operation (transfers, updates, conditional mutations):

```python
@app.route('/<action>', methods=['POST'])
def action():
    data = request.get_json(force=True, silent=True) or {}
    
    # --- Phase 1: Input validation (before any DB work) ---
    # 1a. Missing required fields
    if data.get('field') is None:
        return jsonify({"error": "Missing required field: field"}), 400
    # 1b. Logical constraints (type checks, range checks, cross-field rules)
    if not valid(data['field']):
        return jsonify({"error": "..."}), 400
    
    db = get_db()
    try:
        # --- Phase 2: Acquire lock and perform atomic operation ---
        db.execute("BEGIN IMMEDIATE")  # RESERVED lock — serializes writers
        
        # 2a. Existence checks (inside transaction, after lock)
        resource = db.execute("SELECT ... WHERE ...", (...)).fetchone()
        if resource is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Not found"}), 404
        
        # 2b. State-dependent checks (inside transaction, after lock)
        if resource['balance'] < amount:
            db.execute("ROLLBACK")
            return jsonify({"error": "Insufficient ..."}), 400
        
        # 2c. Mutations
        db.execute("UPDATE ... SET ... WHERE ...", (...))
        cursor = db.execute("INSERT INTO ... VALUES ...", (...))
        
        # 2d. Fetch updated state for response
        updated = db.execute("SELECT ... WHERE id = ?", (...)).fetchone()
        
        db.execute("COMMIT")
        return jsonify({...}), 200
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

**Why BEGIN IMMEDIATE (not BEGIN or BEGIN DEFERRED)?**
- `BEGIN DEFERRED` acquires no lock until the first write. Two concurrent operations could both read, then both try to write → SQLITE_BUSY.
- `BEGIN IMMEDIATE` acquires a RESERVED lock immediately, serializing all concurrent writers.

#### Idempotent Setup Endpoint

```python
@app.route('/setup', methods=['GET'])
def setup():
    db = get_db()
    
    # CREATE TABLE IF NOT EXISTS — safe to call repeatedly
    db.execute("""
        CREATE TABLE IF NOT EXISTS <table> (
            id INTEGER PRIMARY KEY,
            ...
        )
    """)
    
    # INSERT OR IGNORE — idempotent seeding
    db.execute("INSERT OR IGNORE INTO <table> (...) VALUES (...)", (...))
    
    return jsonify({"status": "ok"}), 200
```

#### Database Path

Compute the path at request time inside `get_db()`, not at module import time, because tests may change the working directory:

```python
def get_db():
    if 'db' not in g:
        db_path = os.path.join(os.getcwd(), 'bank.db')  # computed per-request
        g.db = sqlite3.connect(db_path, isolation_level=None)
        ...
```

### In-Memory (persistence_model: in_memory)

For simpler cases or when the task doesn't require persistent storage across restarts:

```python
# Module-level state
state = {
    "resources": {},  # id -> resource dict
    "counter": 0      # auto-increment ID
}

@app.route('/setup', methods=['GET'])
def setup():
    # Reset state for idempotent setup
    state["resources"] = {}
    state["counter"] = 0
    
    # Seed initial data
    state["resources"][1] = {"id": 1, "name": "Alice", "balance": 100.0}
    state["resources"][2] = {"id": 2, "name": "Bob", "balance": 50.0}
    state["counter"] = 2
    
    return jsonify({"status": "ok"}), 200

@app.route('/resource', methods=['POST'])
def create_resource():
    data = request.get_json(force=True, silent=True) or {}
    
    # Validation (no transaction needed for in-memory)
    if data.get('name') is None:
        return jsonify({"error": "Missing required field: name"}), 400
    
    # Create resource
    state["counter"] += 1
    resource_id = state["counter"]
    resource = {
        "id": resource_id,
        "name": data['name'],
        # ... other fields
    }
    state["resources"][resource_id] = resource
    
    return jsonify(resource), 201
```

**Key differences from SQLite3:**
- No transaction management needed (single-threaded test client)
- State resets on each test run (no persistence across processes)
- Simpler error handling (no ROLLBACK needed)
- Still follow the same validation ordering pattern

### Flask-SQLAlchemy (persistence_model: flask_sqlalchemy)

```python
from flask_sqlalchemy import SQLAlchemy

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # ... other fields

@app.route('/setup', methods=['GET'])
def setup():
    db.create_all()
    # Seed data
    if not Resource.query.first():
        db.session.add(Resource(name="Alice"))
        db.session.commit()
    return jsonify({"status": "ok"}), 200

@app.route('/resource', methods=['POST'])
def create_resource():
    data = request.get_json(force=True, silent=True) or {}
    
    if data.get('name') is None:
        return jsonify({"error": "Missing required field: name"}), 400
    
    try:
        resource = Resource(name=data['name'])
        db.session.add(resource)
        db.session.commit()
        return jsonify({"id": resource.id, "name": resource.name}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
```

### File Manifest (persistence_model: file_manifest)

For cases where state is stored as a JSON manifest file:

```python
import json
import os

MANIFEST_FILE = os.path.join(os.getcwd(), 'manifest.json')

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    return {"counter": 0, "items": {}}

def save_manifest(manifest):
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)

@app.route('/setup', methods=['GET'])
def setup():
    manifest = {
        "counter": 2,
        "items": {
            "1": {"id": 1, "name": "Alice", "balance": 100.0},
            "2": {"id": 2, "name": "Bob", "balance": 50.0}
        }
    }
    save_manifest(manifest)
    return jsonify({"status": "ok"}), 200

@app.route('/items', methods=['POST'])
def create_item():
    data = request.get_json(force=True, silent=True) or {}
    
    if data.get('name') is None:
        return jsonify({"error": "Missing required field: name"}), 400
    
    manifest = load_manifest()
    manifest["counter"] += 1
    item_id = manifest["counter"]
    
    item = {"id": item_id, "name": data['name'], "balance": data.get('balance', 0.0)}
    manifest["items"][str(item_id)] = item
    save_manifest(manifest)
    
    return jsonify(item), 201

@app.route('/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    manifest = load_manifest()
    item = manifest["items"].get(str(item_id))
    
    if item is None:
        return jsonify({"error": "Item not found"}), 404
    
    return jsonify(item), 200

@app.route('/items/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    data = request.get_json(force=True, silent=True) or {}
    
    manifest = load_manifest()
    item = manifest["items"].get(str(item_id))
    
    if item is None:
        return jsonify({"error": "Item not found"}), 404
    
    if 'name' in data:
        item['name'] = data['name']
    if 'balance' in data:
        item['balance'] = data['balance']
    
    save_manifest(manifest)
    return jsonify(item), 200
```

**Key characteristics:**
- Entire state serialized as JSON in a single file
- Load-modify-save pattern for mutations
- No transaction management needed (single-threaded test client)
- Simple but not efficient for large datasets
- State persists across requests within the same process

### JSONL (persistence_model: jsonl)

For append-only logs or event streams stored as JSON Lines:

```python
import json
import os

JSONL_FILE = os.path.join(os.getcwd(), 'log.jsonl')

def load_records():
    """Load all records from JSONL file."""
    if not os.path.exists(JSONL_FILE):
        return []
    records = []
    with open(JSONL_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def save_records(records):
    """Overwrite JSONL file with all records."""
    with open(JSONL_FILE, 'w') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')

def append_record(record):
    """Append a single record to JSONL file."""
    with open(JSONL_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

@app.route('/setup', methods=['GET'])
def setup():
    # Clear and seed
    records = [
        {"id": 1, "level": "INFO", "message": "System started"},
        {"id": 2, "level": "WARNING", "message": "Low disk space"}
    ]
    save_records(records)
    return jsonify({"status": "ok"}), 200

@app.route('/logs', methods=['POST'])
def create_log():
    data = request.get_json(force=True, silent=True) or {}
    
    if data.get('message') is None:
        return jsonify({"error": "Missing required field: message"}), 400
    
    records = load_records()
    log_id = max([r['id'] for r in records], default=0) + 1
    
    log_entry = {
        "id": log_id,
        "level": data.get('level', 'INFO'),
        "message": data['message']
    }
    
    append_record(log_entry)
    return jsonify(log_entry), 201

@app.route('/logs', methods=['GET'])
def list_logs():
    level_filter = request.args.get('level')
    records = load_records()
    
    if level_filter:
        records = [r for r in records if r.get('level') == level_filter]
    
    return jsonify(records), 200

@app.route('/logs/<int:log_id>', methods=['GET'])
def get_log(log_id):
    records = load_records()
    log = next((r for r in records if r['id'] == log_id), None)
    
    if log is None:
        return jsonify({"error": "Log not found"}), 404
    
    return jsonify(log), 200
```

**Key characteristics:**
- Each record is a separate JSON line (one record per line)
- Efficient append operations (no need to rewrite entire file)
- Load-all pattern for queries and updates
- Natural fit for append-only logs, event streams, audit trails
- No transaction management needed (single-threaded test client)

## CRUD Endpoint Patterns

Most resource models require CRUD operations. Here are the standard patterns:

### POST /resource (Create)

```python
@app.route('/resource', methods=['POST'])
def create_resource():
    data = request.get_json(force=True, silent=True) or {}
    
    # 1. Missing required fields
    if data.get('name') is None:
        return jsonify({"error": "Missing required field: name"}), 400
    
    # 2. Logical constraints
    if len(data['name']) < 3:
        return jsonify({"error": "Name must be at least 3 characters"}), 400
    
    db = get_db()
    try:
        # 3. Acquire lock for atomic read-check-write
        db.execute("BEGIN IMMEDIATE")
        
        # 4. Uniqueness checks (inside transaction, after lock)
        existing = db.execute("SELECT id FROM resources WHERE name = ?", (data['name'],)).fetchone()
        if existing:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource with this name already exists"}), 409
        
        # 5. Create
        cursor = db.execute("INSERT INTO resources (name) VALUES (?)", (data['name'],))
        resource_id = cursor.lastrowid
        
        resource = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        db.execute("COMMIT")
        
        return jsonify(dict(resource)), 201
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

**Note**: CREATE uses `BEGIN IMMEDIATE` when checking uniqueness at the application level (read-then-write). If you rely on a database UNIQUE constraint instead, you can omit the explicit transaction and catch `sqlite3.IntegrityError`.

### GET /resource (List with optional filters)

```python
@app.route('/resource', methods=['GET'])
def list_resources():
    # Query parameters for filtering
    status = request.args.get('status')
    category = request.args.get('category')
    
    query = "SELECT * FROM resources WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    if category:
        query += " AND category = ?"
        params.append(category)
    
    resources = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in resources]), 200
```

### GET /resource/<id> (Get by ID)

```python
@app.route('/resource/<int:resource_id>', methods=['GET'])
def get_resource(resource_id):
    resource = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    
    if resource is None:
        return jsonify({"error": "Resource not found"}), 404
    
    return jsonify(dict(resource)), 200
```

### PUT /resource/<id> (Update)

```python
@app.route('/resource/<int:resource_id>', methods=['PUT'])
def update_resource(resource_id):
    data = request.get_json(force=True, silent=True) or {}
    
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        resource = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if resource is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        # Update fields
        if 'name' in data:
            db.execute("UPDATE resources SET name = ? WHERE id = ?", (data['name'], resource_id))
        
        if 'status' in data:
            db.execute("UPDATE resources SET status = ? WHERE id = ?", (data['status'], resource_id))
        
        updated = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        db.execute("COMMIT")
        
        return jsonify(dict(updated)), 200
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

### DELETE /resource/<id> (Delete)

```python
@app.route('/resource/<int:resource_id>', methods=['DELETE'])
def delete_resource(resource_id):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        resource = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if resource is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
        db.execute("COMMIT")
        
        return jsonify({"status": "deleted"}), 200
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

## Validation Ordering Pattern

Always validate in this order to produce the correct error for the first failing constraint:

1. **Parse request** — extract JSON body or query parameters, handle missing/malformed input
2. **Missing required fields** — check all required keys exist and are not None
3. **Logical constraints** — type checks, range checks, cross-field rules (no DB needed)
4. **Uniqueness checks** — verify no conflicts with existing resources (requires DB, inside transaction)
5. **Existence checks** — verify referenced resources exist (requires DB, inside transaction)
6. **State-dependent checks** — balance sufficient, status allows operation, etc. (inside transaction)

This ordering ensures the most specific, actionable error is returned first.

## Error Contract Pattern

Every error returns JSON with an `"error"` key and the appropriate HTTP status:

| Condition | Status | Response |
|-----------|--------|----------|
| Missing fields | 400 | `{"error": "Missing required fields: ..."}` |
| Invalid values | 400 | `{"error": "Amount must be positive"}` |
| Logical violation | 400 | `{"error": "Cannot transfer to the same account"}` |
| Uniqueness violation | 409 | `{"error": "Resource already exists"}` |
| Resource not found | 404 | `{"error": "Resource not found"}` |
| Insufficient state | 400 | `{"error": "Insufficient balance"}` |
| Server error | 500 | `{"error": "..."}` |

**Critical**: Error messages must match the task specification exactly. Tests check for exact string matches.

**Key invariant**: On any error path inside a transaction, always ROLLBACK before returning, so persistent state remains consistent.

## Redirect Endpoints

Some endpoints may need to return redirects instead of JSON:

```python
from flask import redirect, url_for

@app.route('/old-path', methods=['GET'])
def old_path():
    return redirect(url_for('new_path'), code=301)  # Permanent redirect

@app.route('/create-and-redirect', methods=['POST'])
def create_and_redirect():
    # ... create resource ...
    return redirect(url_for('get_resource', resource_id=new_id), code=302)  # Temporary redirect
```

## Query Parameter Handling

For GET endpoints with filters:

```python
@app.route('/resources', methods=['GET'])
def list_resources():
    # Single value
    status = request.args.get('status')
    
    # Multiple values (e.g., ?status=active&status=pending)
    statuses = request.args.getlist('status')
    
    # With default value
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    
    # Build query dynamically
    query = "SELECT * FROM resources WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, (page - 1) * limit])
    
    resources = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in resources]), 200
```

## Uniqueness Constraints

For fields that must be unique (usernames, slugs, URLs):

```python
@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json(force=True, silent=True) or {}
    
    if data.get('username') is None:
        return jsonify({"error": "Missing required field: username"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        # Check uniqueness
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (data['username'],)
        ).fetchone()
        
        if existing:
            db.execute("ROLLBACK")
            return jsonify({"error": "Username already exists"}), 409
        
        # Create user
        cursor = db.execute(
            "INSERT INTO users (username) VALUES (?)", (data['username'],)
        )
        user_id = cursor.lastrowid
        
        db.execute("COMMIT")
        return jsonify({"id": user_id, "username": data['username']}), 201
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

For SQLite3, you can also use UNIQUE constraints in the schema:

```python
db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        ...
    )
""")
```

Then catch IntegrityError:

```python
import sqlite3

try:
    db.execute("INSERT INTO users (username) VALUES (?)", (username,))
    db.execute("COMMIT")
except sqlite3.IntegrityError:
    db.execute("ROLLBACK")
    return jsonify({"error": "Username already exists"}), 409
```

## Adaptation to Different Resource Models

The pattern is the same regardless of what's being managed:

1. **Define schema** — tables/collections with fields, constraints, and relationships
2. **Setup endpoint** — create schema + seed data idempotently
3. **CRUD endpoints** — create, read (list + get by ID), update, delete
4. **Mutation endpoints** — validate → lock → check → mutate → commit → respond
5. **Query endpoints** — read state with optional filters via query parameters

The resource model (accounts, tasks, notes, carts, URLs, logs) only changes:
- Table schemas and field names
- Validation rules and error messages
- Response shapes
- Business logic in the mutation step
- Which CRUD operations are needed (some resources may be read-only or append-only)

## Checklist for New Cases

- [ ] `app` Flask object exported from `/app/solve.py`
- [ ] Persistence model correctly implemented (sqlite3 with isolation_level=None, or in-memory, or flask_sqlalchemy, or file_manifest with load/save, or jsonl with load/append)
- [ ] `BEGIN IMMEDIATE` for all read-check-write operations (sqlite3 only)
- [ ] ROLLBACK on every error path inside a transaction (sqlite3 only)
- [ ] Setup endpoint is idempotent (IF NOT EXISTS + INSERT OR IGNORE for sqlite3, or reset state for in-memory, or overwrite file for file_manifest/jsonl)
- [ ] Validation ordering: missing → logical → uniqueness → existence → state-dependent
- [ ] All errors return JSON `{"error": "..."}` with correct HTTP status
- [ ] Error messages match task specification exactly
- [ ] Database/file path computed at request time (sqlite3/file_manifest/jsonl)
- [ ] Response includes all fields specified by the case
- [ ] State remains consistent after any error (no partial mutations)
- [ ] Query parameters handled correctly for filter endpoints
- [ ] Uniqueness constraints enforced (if required by task)
- [ ] Redirects return correct status codes (301/302) if required
