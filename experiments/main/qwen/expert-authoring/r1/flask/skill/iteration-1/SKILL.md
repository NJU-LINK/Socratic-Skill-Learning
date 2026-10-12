---
name: flask
description: >
  Build Flask JSON HTTP services with shared mutable domain state,
  multiple coupled endpoints, and robust validation. Covers all persistence
  backends (sqlite3, Flask-SQLAlchemy, in-memory, file, JSONL), idempotent
  lifecycle endpoints, atomic state transitions, and consistent error handling.
  Evaluation uses Flask's test client against an `app` object in /app/solve.py.
---

# Flask Stateful JSON Service

## 1. Family Invariants

Every case in this family shares these properties — treat them as non-negotiable:

| Invariant | Detail |
|---|---|
| **Artifact** | `/app/solve.py` exporting `app = Flask(__name__)` at module level |
| **Interface** | Evaluation imports `from solve import app` and uses `app.test_client()` — no live server |
| **Protocol** | All data exchange is JSON (`request.get_json()` in, `jsonify()` out) |
| **State** | Requests share mutable domain state that persists across the test session |
| **Coupling** | At least two endpoints are behaviorally coupled (shared state, one affects the other) |
| **Errors** | Every error returns a JSON body `{"error": "..."}` with the correct HTTP status |

Things **outside** this family: single-route demos, stateless calculators, auth-only snippets, HTML template rendering.

## 2. Reading the Task Spec — Decision Checklist

Before writing code, extract these from the task instruction:

1. **Resource model** — What entities exist? What are their fields, types, and invariants?
2. **Persistence model** — sqlite3 / Flask-SQLAlchemy / in-memory dict / file / JSONL?
3. **Endpoints** — List each route: method, path, request shape, response shape, status codes.
4. **Lifecycle endpoint** — Usually `GET /setup` or similar. Must be idempotent. What does it seed?
5. **State transitions** — What operations mutate state? What atomicity/ordering constraints exist?
6. **Validation rules** — For each mutation, what inputs are checked, in what order, with what error response?
7. **Response schemas** — Exact field names and nesting in success and error responses.

Write these down as a checklist before coding. Every bullet in the task instruction maps to a test.

## 3. Persistence Strategies

### 3.1 Raw sqlite3

```python
import sqlite3, os
from flask import Flask, request, jsonify, g

DB_PATH = os.path.join(os.getcwd(), "thedb.db")  # use CWD unless spec says otherwise

app = Flask(__name__)

def get_db():
    """Per-request connection, stored on Flask g object."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)  # manual tx control
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

**Key rules for sqlite3:**
- Use `isolation_level=None` to get manual `BEGIN`/`COMMIT`/`ROLLBACK` control.
- Without `isolation_level=None`, Python's sqlite3 module auto-starts transactions on DML and you must call `conn.commit()` — easy to forget, leads to invisible uncommitted state.
- Always `COMMIT` on success, `ROLLBACK` in `except` blocks.
- Use `CREATE TABLE IF NOT EXISTS` for idempotent setup.
- Use `INSERT OR IGNORE` or check-before-insert for idempotent seeding.
- `sqlite3.Row` gives dict-like access to columns.

### 3.2 Flask-SQLAlchemy

```python
from flask_sqlalchemy import SQLAlchemy

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///thedb.db"
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(80), nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)
```

**Key rules for Flask-SQLAlchemy:**
- `db.create_all()` is idempotent — safe to call multiple times.
- Use `db.session.commit()` to persist; `db.session.rollback()` on error.
- For idempotent seeding, check before insert: `if not Account.query.get(1): ...`
- URI `sqlite:///:memory:` for in-memory (single-process only; test client is single-process so this works).
- URI `sqlite:///path.db` for file-based (path relative to instance folder).

### 3.3 In-Memory (dict/list)

```python
# Module-level mutable state
accounts = {}      # id -> {id, owner, balance}
transactions = []  # list of transaction dicts
next_tx_id = 1     # manual autoincrement
```

**Key rules for in-memory:**
- State must be module-level (survives across requests within the process).
- Provide a reset mechanism in the setup endpoint (clear dicts, re-seed).
- Manual autoincrement counters for IDs.
- No persistence across process restarts (fine for test client).
- Thread safety is not usually required (test client is synchronous).

### 3.4 File / JSONL

```python
import json, os

DATA_FILE = os.path.join(os.getcwd(), "data.json")

def load_state():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return default_state()

def save_state(state):
    with open(DATA_FILE, "w") as f:
        json.dump(state, f)
```

**Key rules for file-based:**
- Read at start of request, write at end of successful mutation.
- For JSONL (append-only log), read all lines to reconstruct state, append new entries.
- Use `os.path.exists` for idempotent setup.
- Write atomically when possible (write to temp file, then `os.replace`).

## 4. Endpoint Patterns

### 4.1 Lifecycle / Setup Endpoint

Usually `GET /setup`. Must be **idempotent**:

- **sqlite3**: `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` or `DELETE` + re-`INSERT`.
- **Flask-SQLAlchemy**: `db.create_all()` + check-before-seed or `db.drop_all()` + recreate.
- **In-memory**: Reset dicts/lists, re-populate seed data.
- **File**: Overwrite or create file with seed data.

The setup endpoint should always return a success response (200 or 201) even when called repeatedly.

### 4.2 Request Parsing

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid JSON body"}), 400

# Extract required fields
from_id = data.get("from_id")
to_id = data.get("to_id")
amount = data.get("amount")

# Check required fields present
if from_id is None or to_id is None or amount is None:
    return jsonify({"error": "Missing required fields"}), 400
```

**Use `silent=True`** to prevent Flask from auto-returning a 400 HTML error on bad JSON. Handle it yourself with JSON.

### 4.3 Response Construction

- Use `jsonify()` for all responses (sets `Content-Type: application/json` automatically).
- For success: `return jsonify({...}), 200` or `return jsonify({...}), 201`.
- For errors: `return jsonify({"error": "specific message"}), STATUS_CODE`.
- Match the exact field names and nesting from the task spec.

### 4.4 HTTP Methods

- Register all needed methods in the route decorator: `@app.route("/path", methods=["GET", "POST"])`.
- Default is only `GET`. Forgetting `methods=["POST"]` is a common bug.
- If a route only accepts POST but gets a GET, Flask returns 405 automatically — this is correct behavior.

## 5. State Transition Patterns

### 5.1 Atomic Multi-Step Operations

When an operation modifies multiple rows/entities, wrap it in a transaction:

**sqlite3 pattern:**
```python
db = get_db()
try:
    db.execute("BEGIN")
    # ... multiple reads and writes ...
    db.execute("COMMIT")
except Exception:
    db.execute("ROLLBACK")
    raise
```

**Flask-SQLAlchemy pattern:**
```python
try:
    # ... modify db.session objects ...
    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

### 5.2 Idempotent Operations

If the spec requires an operation to be safely repeatable:
- Check if already done before executing.
- Use unique constraints to prevent duplicates.
- Return success even if already done (don't error on "already exists" unless spec says to).

### 5.3 Autoincrement IDs

- **sqlite3**: `INTEGER PRIMARY KEY AUTOINCREMENT` — `cursor.lastrowid` after INSERT.
- **Flask-SQLAlchemy**: `db.Column(db.Integer, primary_key=True)` — `obj.id` after `db.session.flush()`.
- **In-memory**: Maintain a module-level counter variable.

## 6. Validation Decision Tree

Apply validation checks in this order (stop at first failure, return immediately):

```
1. Parse JSON body → if malformed/missing: 400
2. Check required fields present → if missing: 400
3. Type validation → if wrong type: 400
4. Domain/range validation (e.g., amount > 0) → if invalid: 400 with spec message
5. Identity checks (e.g., from_id ≠ to_id) → if violated: 400 with spec message
6. Existence checks (e.g., account exists) → if not found: 404 with spec message
7. State checks (e.g., sufficient balance) → if insufficient: 400 with spec message
8. Execute the operation
```

**Critical rules:**
- Match the **exact error messages** from the spec. Tests often check string equality.
- Match the **exact HTTP status codes** from the spec. Don't substitute 422 for 400 unless told to.
- **Never mutate state before all validations pass.** Validate first, then execute.
- On error, the persistent state must remain **consistent** — no partial writes.

## 7. Self-Verification Protocol

After writing `/app/solve.py`, always run a smoke test before considering the task done:

```python
# /app/verify.py (temporary, delete after)
from solve import app
import json

client = app.test_client()

# 1. Setup
r = client.get("/setup")
assert r.status_code == 200, f"Setup failed: {r.status_code}"
print("✓ Setup OK")

# 2. Setup idempotency
r = client.get("/setup")
assert r.status_code == 200, f"Setup not idempotent: {r.status_code}"
print("✓ Setup idempotent")

# 3. Happy path
r = client.post("/your_endpoint", json={...})
assert r.status_code == 200, f"Happy path failed: {r.status_code} {r.data}"
data = r.get_json()
assert "expected_field" in data, f"Missing field in response: {data}"
print("✓ Happy path OK")

# 4. Each error condition
r = client.post("/your_endpoint", json={})  # missing fields
assert r.status_code == 400
print("✓ Missing fields → 400")

# 5. State consistency after error
# (check that a failed operation didn't corrupt state)
r = client.get("/some_read_endpoint")
# verify state unchanged
print("✓ State consistent after error")

print("\nAll smoke tests passed!")
```

Run it: `cd /app && python verify.py`

**Then run the actual test suite** if one is provided or discoverable:
```bash
cd /app && python -m pytest -xvs 2>&1 | head -100
```

## 8. Common Pitfalls and How to Avoid Them

| Pitfall | Symptom | Fix |
|---|---|---|
| Forgetting `methods=["POST"]` | 405 Method Not Allowed | Always specify methods explicitly |
| sqlite3 implicit transactions | State not persisted between requests | Use `isolation_level=None` + manual `BEGIN`/`COMMIT`, or call `conn.commit()` |
| `request.get_json()` without `silent=True` | HTML 400 error on bad/missing JSON | Use `silent=True`, check for `None` |
| Not rolling back on exception | Corrupted state after partial failure | Wrap mutations in try/except with ROLLBACK |
| Seed data duplicated on second `/setup` | Duplicate key errors or doubled data | Use `INSERT OR IGNORE` or check-before-insert |
| Hardcoded DB path mismatch | `no such table` errors | Use `os.path.join(os.getcwd(), "dbfile.db")` or spec-stated path |
| Returning Python dict instead of `jsonify()` | May work in Flask 3.0 but inconsistent Content-Type | Always use `jsonify()` or explicit headers |
| Forgetting `g` teardown | "Too many open files" or locked DB | Use `@app.teardown_appcontext` to close connections |
| Checking existence after mutation | State already changed, can't roll back cleanly | Validate ALL conditions BEFORE any mutation |
| Wrong error message string | Test assertion fails on message comparison | Copy exact strings from the spec |

## 9. File Structure Template

```
/app/solve.py          # REQUIRED — the Flask application
/app/thedb.db          # Created at runtime if sqlite3/file persistence
```

Minimal solve.py skeleton:

```python
import os
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# --- Persistence setup (choose one) ---
# --- Route definitions ---
# --- Validation helpers ---
# --- Main logic ---

if __name__ == "__main__":
    app.run()
```

## 10. Adapting to Unseen Cases

When you encounter a new case in this family:

1. **Extract the resource model** — What are the entities and their relationships?
2. **Identify the persistence backend** — Which of the five strategies applies?
3. **Map every endpoint** — Method, path, request body, query params, response shape.
4. **Build the validation tree** — For each mutating endpoint, list every error condition with its status code and message.
5. **Identify atomicity boundaries** — Which operations must be all-or-nothing?
6. **Identify idempotency requirements** — Which operations must be safely repeatable?
7. **Write the setup endpoint first** — It seeds the state everything else depends on.
8. **Implement endpoints in dependency order** — Read endpoints before mutation endpoints.
9. **Self-verify** — Run the smoke test protocol.
10. **Match the spec exactly** — Field names, error messages, status codes, nesting.
