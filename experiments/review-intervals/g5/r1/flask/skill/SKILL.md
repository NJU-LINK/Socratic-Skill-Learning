---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  through multiple behaviorally coupled endpoints. Covers SQLite3 and in-memory
  persistence, atomic state transitions, idempotent setup, ordered validation,
  and consistent error handling — all testable via Flask's test client.
---

# Flask Stateful JSON Service

## Family Definition

Every case in this family requires `/app/solve.py` to export a Flask application
named `app`. Tests import it via `from solve import app` and exercise it through
`app.test_client()`. The service manages mutable domain state across multiple
coupled endpoints — not single-route demos or stateless wrappers.

## Decision Framework: Mapping Task Specs to Implementation

When reading a new task spec, identify these dimensions to select the right
patterns:

**1. Persistence model** — What storage backend?
- SQLite3 → use `isolation_level=None`, `BEGIN IMMEDIATE`, parameterized queries
- In-memory → module-level dicts, reset on `/setup`
- JSONL → append-only file, read-all for queries
- File manifest → data file + JSON sidecar for metadata
- Flask-SQLAlchemy → ORM models, `db.session`

**2. Endpoint contracts** — What routes and methods?
- GET /setup → idempotent initialization
- POST /resource → CREATE with JSON body
- GET /resource or GET /resource/<id> → READ with optional query filters
- PUT/PATCH /resource/<id> → UPDATE (full or partial)
- DELETE /resource/<id> → DELETE with dependency checks
- POST /transition → state transition (e.g., transfer, checkout)

**3. State transition semantics** — What operations?
- Atomic transfers → read both, validate, update both, insert record
- Idempotent setup → check-then-seed or INSERT OR IGNORE
- CRUD updates → check existence, validate, update, return updated
- Uniqueness → check inside transaction, return 409 on conflict
- Counters → increment atomically with BEGIN IMMEDIATE
- Aggregates → SUM/COUNT queries, return computed values
- Checkout → validate inventory, decrement, create order
- Cascading validation → check dependencies before delete

**4. Validation and failure behavior** — What error conditions?
- Missing fields → 400
- Invalid types → 400 (validate BEFORE domain logic)
- Domain constraints → 400 (same-account, positive amount, etc.)
- Resource not found → 404
- Uniqueness violation → 409
- State conflict → 409 (insufficient balance, already checked out)

**5. Response schemas** — What do success responses look like?
- Copy the exact structure from the spec (field names, nesting, types)
- Tests assert on specific fields: `data["sender"]["balance"]`
- Include all required fields (id, balance, transaction_id, etc.)

Use this framework to decompose any task spec into concrete implementation
choices.

## Core Architecture Pattern

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# Lifecycle endpoint (setup/reset)
@app.route("/setup", methods=["GET"])
def setup(): ...

# Domain endpoints (CRUD, transitions, queries)
@app.route("/resource", methods=["POST"])
def create_resource(): ...
```

### Key Structural Rules

1. **Always export `app` at module level** — tests do `from solve import app`
2. **Use `request.get_json()`** for JSON body parsing; return 400 if None
3. **Use `jsonify()`** for all JSON responses
4. **Open and close connections per request** — never hold global connections
5. **Use `try/finally`** to guarantee connection cleanup

## Persistence Patterns

### SQLite3 (raw) — Most Common

```python
import sqlite3

DB_PATH = "service.db"  # or whatever the task specifies

def get_connection():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row  # dict-like access
    return conn
```

**Critical: `isolation_level=None`** — Python's sqlite3 defaults to auto-BEGIN
on DML, which conflicts with explicit transaction control. Setting it to None
gives full manual control over BEGIN/COMMIT/ROLLBACK.

**Critical: Always use parameterized queries** — Never interpolate user input
into SQL strings. Use `?` placeholders for all values:

```python
# CORRECT: parameterized
conn.execute("UPDATE t SET name = ? WHERE id = ?", (user_name, user_id))

# WRONG: string interpolation — SQL injection vulnerability
conn.execute(f"UPDATE t SET name = '{user_name}' WHERE id = {user_id}")
```

This applies to all user-supplied data: names, descriptions, notes, etc.

### In-Memory (dict-based)

```python
# Module-level state
_resources = {}
_next_id = 1

def reset_state():
    global _resources, _next_id
    _resources = {}
    _next_id = 1
```

**Idempotent setup for in-memory state:** The `/setup` endpoint must reset
module-level globals to prevent stale data from prior test cases:

```python
@app.route("/setup", methods=["GET"])
def setup():
    global _resources, _next_id
    _resources = {}
    _next_id = 1
    # Seed initial data...
    _resources[1] = {"id": 1, "name": "Alice", "balance": 100.0}
    _next_id = 2
    return jsonify({"status": "ok"}), 200
```

Without this reset, tests running in the same process will see leftover state.

### Flask-SQLAlchemy

```python
from flask_sqlalchemy import SQLAlchemy
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///service.db"
db = SQLAlchemy(app)
```

### JSONL (JSON Lines)

Each record is one JSON object per line. Good for append-heavy workloads.

```python
import json, os

DATA_FILE = "data.jsonl"

def read_all():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return [json.loads(line) for line in f if line.strip()]

def append(record):
    with open(DATA_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

def write_all(records):
    with open(DATA_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
```

### File Manifest

A data file plus a manifest (JSON sidecar) tracking metadata like schema
version, record count, or last-modified timestamp.

```python
import json, os

DATA_FILE = "data.json"
MANIFEST_FILE = "manifest.json"

def read_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return {"version": 1, "count": 0}

def write_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f)

def read_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)
```

Use the manifest to track schema version, seed-data presence, or record counts
for idempotent setup checks.

## Idempotent Setup

The `/setup` endpoint must be callable multiple times without side effects.
Two patterns:

**Pattern A: Check-then-seed (preferred)**
```python
@app.route("/setup", methods=["GET"])
def setup():
    conn = get_connection()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS ...")
        count = conn.execute("SELECT COUNT(*) FROM resource").fetchone()[0]
        if count == 0:
            conn.execute("INSERT INTO resource ...")
        return jsonify({"status": "ok"}), 200
    finally:
        conn.close()
```

**Pattern B: INSERT OR IGNORE / INSERT OR REPLACE**
```python
conn.execute("INSERT OR IGNORE INTO resource (id, ...) VALUES (?, ...)", ...)
```

Pattern A is safer when tests may have modified data between setup calls.

## Atomic State Transitions

When an operation must read-then-write atomically (transfers, counters, etc.):

```python
conn = get_connection()
try:
    conn.execute("BEGIN IMMEDIATE")  # Write-intent lock, not plain BEGIN
    
    # Read current state
    row = conn.execute("SELECT ... WHERE id = ?", (id,)).fetchone()
    
    # Validate business rules
    if not row:
        conn.execute("ROLLBACK")
        return jsonify({"error": "Not found"}), 404
    
    # Mutate state
    conn.execute("UPDATE ... WHERE id = ?", (new_value, id))
    
    conn.execute("COMMIT")
    return jsonify({...}), 200
    
except Exception as e:
    conn.execute("ROLLBACK")
    return jsonify({"error": str(e)}), 500
finally:
    conn.close()
```

**Why `BEGIN IMMEDIATE`?** Plain `BEGIN` acquires a shared read lock. Two
concurrent writers could both read the same state, both pass validation, and
both write — violating invariants. `BEGIN IMMEDIATE` acquires a reserved
write-intent lock, serializing concurrent writers.

## CRUD Operations

The family includes full CRUD (Create, Read, Update, Delete) endpoints. The
skill covers CREATE (POST) and READ (GET with filters). Here are UPDATE and
DELETE patterns.

### UPDATE (PUT/PATCH)

```python
@app.route("/resource/<int:id>", methods=["PUT", "PATCH"])
def update_resource(id):
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # Validate types before using values
    if "name" in data and not isinstance(data["name"], str):
        return jsonify({"error": "name must be a string"}), 400
    
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Check existence
        row = conn.execute("SELECT * FROM resource WHERE id = ?", (id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        # Build update dynamically (for PATCH semantics)
        updates = []
        params = []
        for field in ["name", "status", "value"]:  # allowed fields
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])
        
        if not updates:
            conn.execute("ROLLBACK")
            return jsonify({"error": "No fields to update"}), 400
        
        params.append(id)
        conn.execute(f"UPDATE resource SET {', '.join(updates)} WHERE id = ?", params)
        
        conn.execute("COMMIT")
        
        # Return updated resource
        updated = conn.execute("SELECT * FROM resource WHERE id = ?", (id,)).fetchone()
        return jsonify(dict(updated)), 200
        
    except Exception as e:
        conn.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
```

**Key points:**
- Use PUT for full replacement, PATCH for partial updates
- Validate types before using values
- Check existence before updating
- Return the updated resource (tests often assert on the response)
- Use `BEGIN IMMEDIATE` for atomicity

### DELETE

```python
@app.route("/resource/<int:id>", methods=["DELETE"])
def delete_resource(id):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Check existence
        row = conn.execute("SELECT * FROM resource WHERE id = ?", (id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        # Check for dependencies (cascading validation)
        dep_count = conn.execute(
            "SELECT COUNT(*) FROM dependent WHERE resource_id = ?", (id,)
        ).fetchone()[0]
        if dep_count > 0:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Cannot delete: resource has dependencies"}), 409
        
        conn.execute("DELETE FROM resource WHERE id = ?", (id,))
        conn.execute("COMMIT")
        
        return jsonify({"status": "deleted"}), 200  # or 204 No Content
        
    except Exception as e:
        conn.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
```

**Key points:**
- Check existence before deleting
- Check for dependencies (cascading validation) — return 409 Conflict if present
- Use `BEGIN IMMEDIATE` for atomicity
- Return 200 with JSON or 204 No Content (match the spec)

## Uniqueness Constraints

Some resources have unique fields (e.g., URL shorteners, usernames). When
creating or updating, check for conflicts:

```python
@app.route("/urls", methods=["POST"])
def create_url():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    short_url = data.get("short_url")
    if not isinstance(short_url, str):
        return jsonify({"error": "short_url must be a string"}), 400
    
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Check uniqueness
        existing = conn.execute(
            "SELECT id FROM urls WHERE short_url = ?", (short_url,)
        ).fetchone()
        if existing:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Short URL already exists"}), 409
        
        # Insert
        cursor = conn.execute(
            "INSERT INTO urls (short_url, target_url) VALUES (?, ?)",
            (short_url, data["target_url"])
        )
        conn.execute("COMMIT")
        
        return jsonify({"id": cursor.lastrowid, "short_url": short_url}), 201
        
    except Exception as e:
        conn.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
```

**Key points:**
- Check uniqueness inside the transaction (after `BEGIN IMMEDIATE`)
- Return 409 Conflict for uniqueness violations
- Use parameterized queries for the uniqueness check

## Validation Order

Always validate in this sequence to match test expectations:

1. **Missing/invalid fields** → 400
2. **Type validation** → 400 (if types are wrong, domain logic will crash)
3. **Domain-specific constraints** (e.g., same-account, positive amount) → 400
4. **Resource existence** (check ALL referenced resources) → 404
5. **State-dependent rules** (e.g., sufficient balance, not already done) → 400/409
6. **Perform the operation**

Checking existence before state-dependent rules prevents NoneType errors and
wrong status codes for non-existent resources.

### Type Validation

After confirming fields exist, validate their types **before** any domain logic
that uses the value. A string `"1"` compared with `== 1` is `False` in Python,
a string `"10"` compared with `<= 0` raises `TypeError`, and a string passed as
a SQL integer parameter may silently work or fail depending on the binding.

```python
# After confirming fields exist, validate their types
if not isinstance(from_id, int) or not isinstance(to_id, int):
    return jsonify({"error": "from_id and to_id must be integers"}), 400

if not isinstance(amount, (int, float)):
    return jsonify({"error": "amount must be a number"}), 400
```

**Subtlety:** `isinstance(True, int)` returns `True` in Python since `bool` is a
subclass of `int`. If a test sends `{"from_id": true, ...}`, the type check
passes but the semantic is wrong. Guard with:

```python
if not isinstance(from_id, int) or isinstance(from_id, bool):
    return jsonify({"error": "from_id must be an integer"}), 400
```

Most tests don't test this edge case, but it's worth being aware of when
type validation is strict.

## Error Response Pattern

```python
# 400 — Bad request (client error in input)
return jsonify({"error": "descriptive message"}), 400

# 404 — Resource not found
return jsonify({"error": "Resource not found"}), 404

# 409 — Conflict (state prevents operation)
return jsonify({"error": "Conflict message"}), 409

# 500 — Server error (unexpected)
return jsonify({"error": "Internal error"}), 500
```

Match the exact error message strings from the task specification — tests
often assert on them.

## Success Response Schema

**Copy the success response schema verbatim from the task spec.** Field names,
nesting, and types must match exactly. Tests typically do:

```python
data = resp.get_json()
assert data["sender"]["balance"] == expected_balance
assert data["transaction_id"] == expected_id
```

If the spec says `{"sender": {"id": ..., "balance": ...}}`, returning
`{"status": "ok", "from_balance": 75.0}` will fail even though the transfer
succeeded. Match the exact structure specified.

## Request Handling Checklist

For each endpoint:

- [ ] Parse JSON body with `request.get_json()`
- [ ] Check for None (invalid/missing JSON)
- [ ] Validate all required fields are present
- [ ] **Validate field types** (before any domain logic)
- [ ] Validate field ranges and constraints
- [ ] Apply domain-specific constraints
- [ ] Check resource existence
- [ ] Check state-dependent rules
- [ ] Perform atomic operation if needed
- [ ] Return correct status code and response schema
- [ ] Close database connection in `finally`

## Testing Locally

```python
from solve import app

client = app.test_client()

# Setup
resp = client.get('/setup')
assert resp.status_code == 200

# Happy path
resp = client.post('/endpoint', json={...})
assert resp.status_code == 200
data = resp.get_json()
# Assert on response fields

# Error cases
resp = client.post('/endpoint', json={})
assert resp.status_code == 400
assert "error" in resp.get_json()
```

## Query and Filter Endpoints

GET endpoints often accept query parameters for filtering:

```python
@app.route("/resources", methods=["GET"])
def list_resources():
    # Query parameters
    status = request.args.get("status")
    owner_id = request.args.get("owner_id", type=int)
    
    # Build dynamic query
    query = "SELECT * FROM resources WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    if owner_id:
        query += " AND owner_id = ?"
        params.append(owner_id)
    
    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return jsonify([dict(r) for r in rows]), 200
    finally:
        conn.close()
```

Always use `request.args.get()` with appropriate type conversion. Return an
empty list `[]` when no resources match — don't return 404 for empty results.

## Redirects

Some endpoints may require HTTP redirects:

```python
from flask import redirect, url_for

@app.route("/old-path", methods=["GET"])
def old_path():
    return redirect(url_for("new_endpoint"), code=301)  # permanent
    # or code=302 for temporary
```

Use `url_for()` to reference endpoints by function name, not hardcoded paths.

## Common Pitfalls

1. **Forgetting `isolation_level=None`** — causes "cannot start a transaction
   within a transaction" errors with explicit BEGIN/COMMIT
2. **Non-idempotent setup** — calling /setup twice duplicates seed data
3. **Plain `BEGIN` instead of `BEGIN IMMEDIATE`** — allows concurrent write
   conflicts
4. **Checking balance before existence** — causes NoneType errors or wrong
   status codes
5. **Not closing connections** — leaks file descriptors, especially in tests
6. **Hardcoding DB path** — use the path specified in the task (often CWD)
7. **Forgetting `row_factory = sqlite3.Row`** — can't access columns by name
8. **Skipping type validation** — string `"10"` compared with `<= 0` raises
   TypeError; validate types BEFORE any domain logic that uses the value
9. **`isinstance(True, int)` returns True** — bool is a subclass of int in
   Python; guard with `isinstance(x, int) and not isinstance(x, bool)` if
   strict integer validation is needed
