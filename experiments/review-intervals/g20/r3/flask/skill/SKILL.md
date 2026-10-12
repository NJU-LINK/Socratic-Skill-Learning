---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  across multiple coupled endpoints, with proper persistence, atomic state
  transitions, validation, and error handling. Tested via Flask's test client.
---

# Flask Stateful Service Skill

## Family Invariants

Every case in this family shares these properties:

1. **Flask app object**: `/app/solve.py` must export `app = Flask(__name__)`
2. **Test client binding**: Evaluation uses `from solve import app` then `app.test_client()`
3. **Stateful service**: Multiple behaviorally coupled endpoints sharing mutable domain state
4. **JSON I/O**: All request/response bodies are JSON
5. **Setup/lifecycle endpoint**: An endpoint that initializes persistent state (tables, files, seeds) — must be idempotent
6. **Validation & error handling**: Missing/invalid inputs and constraint violations produce JSON errors with correct HTTP status codes
7. **Atomic state transitions**: Mutations that touch multiple pieces of state must be atomic

## General Architecture Pattern

```python
import <persistence_imports>
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# --- Persistence layer (varies by persistence_model) ---
# See "Persistence Models" section below

# --- Setup / lifecycle endpoint ---
@app.route("/setup", methods=["GET"])  # path varies per case
def setup():
    # 1. Create schema/structure (idempotent)
    # 2. Seed initial data only if empty
    # 3. Commit and return 200
    ...

# --- Domain endpoints ---
# Each endpoint follows the two-phase validation pattern:
#   Phase 1: Parse & validate input (pure request-data checks)
#   Phase 2: BEGIN IMMEDIATE transaction
#     - State-dependent validation (existence, constraints, balance)
#     - Perform atomic state mutation
#     - COMMIT
#   Return structured JSON response
```

## Persistence Models

**Choosing the right model**: The task description usually specifies the persistence model explicitly. If not specified:
- **sqlite3**: Default choice for relational data with complex queries, transactions, or constraints
- **flask_sqlalchemy**: When the task mentions ORM, models, or relationships
- **in_memory**: When the task says "in-memory", "process-local", or "no persistence required"
- **file_manifest**: When the task mentions JSON files, manifests, or simple key-value storage
- **jsonl**: When the task mentions event logs, append-only data, or streaming

### sqlite3 (raw)

```python
import sqlite3, os

def get_db():
    if "db" not in g:
        # CRITICAL: Use a relative path resolved at connection time,
        # NOT pre-computed at module import time. The evaluator's test
        # code may connect to the same DB using a relative path from a
        # different cwd than where the module was imported.
        g.db = sqlite3.connect("<name>.db", isolation_level=None)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

**Key patterns:**
- Use `g` for per-request connection storage
- `row_factory = sqlite3.Row` for dict-like access
- **`isolation_level=None`** for manual transaction control — critical for explicit BEGIN/COMMIT/ROLLBACK
- **DB path must be relative** (e.g., `"bank.db"`) and resolved at connection time inside `get_db()`. NEVER pre-compute `DB_PATH = os.path.join(os.getcwd(), "<name>.db")` at module level — the evaluator may import the module from a different cwd than where tests run, causing the Flask app and the evaluator's direct `sqlite3.connect("<name>.db")` to target different files.
- Idempotent setup: `CREATE TABLE IF NOT EXISTS`, check `COUNT(*)` before seeding
- Atomic mutations: `db.execute("BEGIN IMMEDIATE")` ... `db.execute("COMMIT")` / `db.execute("ROLLBACK")`
- Note: With `isolation_level=None`, use `db.execute("COMMIT")` not `db.commit()` (the latter is a no-op in autocommit mode)
- Use parameterized queries (`?` placeholders) to prevent SQL injection

### flask_sqlalchemy

```python
from flask_sqlalchemy import SQLAlchemy

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///<name>.db"
db = SQLAlchemy(app)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields

# In endpoints:
# db.session.add(obj)
# db.session.commit()
# db.session.rollback() on error
```

**Key patterns:**
- Define ORM models as classes
- Use `db.session` for transaction management
- `db.create_all()` for schema creation (idempotent by default)
- Check existence before seeding: `Resource.query.count() == 0`
- **Two-phase validation**: Phase 1 (input checks) before session operations; Phase 2 (state checks + mutations) inside a single `db.session` scope with rollback on error

### in_memory

```python
# Module-level or app-level dictionaries
_store = {
    "resources": {},  # id -> resource dict
    "next_id": 1
}

# For thread safety in tests (usually single-threaded, but be safe):
import threading
_lock = threading.Lock()
```

**Key patterns:**
- Store state in module-level dicts or on `app.config`
- Reset state in setup endpoint (clear dicts, re-seed)
- Use deep copies when returning data to prevent aliasing
- No persistence across process restarts
- **Two-phase validation**: Phase 1 (input checks) before lock; Phase 2 (state checks + mutations) inside `with _lock:` block — ensures no concurrent modification between check and mutation

### file_manifest

```python
import json, os

# CRITICAL: Use relative paths, NOT pre-computed absolute paths at module level.
# Compute at access time to match the test runner's cwd.

def _read_manifest():
    if os.path.exists("manifest.json"):
        with open("manifest.json") as f:
            return json.load(f)
    return {"resources": []}

def _write_manifest(data):
    with open("manifest.json", "w") as f:
        json.dump(data, f)
```

### jsonl

```python
import json, os

# CRITICAL: Use relative paths, NOT pre-computed absolute paths at module level.

def _append_event(event):
    with open("events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")

def _read_events():
    if not os.path.exists("events.jsonl"):
        return []
    with open("events.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]
```

## Validation Strategy (Two-Phase Split)

**Core invariant:** Nothing between a state read and its dependent write should be outside the transaction. Split validation into two phases to prevent TOCTOU races.

### Phase 1: Input validation (before transaction)
Pure request-data checks — no DB state needed:
1. **Parse JSON body**: `request.get_json(silent=True)` — return 400 if None
2. **Required fields**: Check each required field is present — return 400
3. **Type validation**: Check types (int, float, str) — return 400. Note: in Python, `bool` is a subclass of `int`, so check `isinstance(x, bool)` first when rejecting booleans from numeric fields
4. **Range/value constraints**: Positive amounts, non-empty strings, etc. — return 400
5. **Cross-field rules** that don't touch DB (e.g., from_id ≠ to_id) — return 400

### Phase 2: State-dependent validation (inside BEGIN IMMEDIATE)
Must read from the locked transaction connection:
6. **Existence checks**: Resource exists — return 404 (ROLLBACK before returning)
7. **Uniqueness / constraint checks** — return 400/409 (ROLLBACK before returning)
8. **State checks**: Sufficient balance, not already processed, etc. — return 400 (ROLLBACK before returning)
9. **Perform mutations**
10. **COMMIT**

**Why `BEGIN IMMEDIATE`?** It acquires a RESERVED lock upfront, preventing concurrent writers from interleaving between reads and writes. Plain `BEGIN` (DEFERRED) acquires a SHARED lock on first read, then tries to upgrade to RESERVED on first write — two writers can both get SHARED locks, then deadlock on upgrade → `SQLITE_BUSY`.

**Error response pattern:**
```python
# Inside Phase 2, always ROLLBACK before returning an error
db.execute("ROLLBACK")
return jsonify({"error": "Descriptive message"}), <status_code>
```

### Validation Edge Cases

**Null vs missing fields**: 
- Missing field: `data.get("field")` returns `None`
- Explicit null: `data.get("field")` also returns `None`
- Treat both as "missing" unless the spec distinguishes them

**Type coercion**:
- JSON `"10"` (string) vs `10` (integer) — validate the actual type, don't coerce
- JSON `true`/`false` are booleans, not integers (even though `bool` is subclass of `int`)
- JSON `10.0` (float) vs `10` (integer) — check if spec requires specific type

**Empty/whitespace strings**:
- If spec says "non-empty", check `len(s.strip()) > 0` not just `len(s) > 0`
- If spec says "required", check presence not emptiness (unless specified)

**Numeric ranges**:
- `amount > 0` vs `amount >= 0` — read the spec carefully
- Integer vs float — check if spec requires specific type

## Atomic State Transitions

### SQLite3 transactions (with isolation_level=None)
```python
try:
    db.execute("BEGIN IMMEDIATE")  # RESERVED lock acquired NOW
    
    # All state reads happen INSIDE the transaction under the lock
    sender = db.execute("SELECT ... WHERE id = ?", (...)).fetchone()
    if sender is None:
        db.execute("ROLLBACK")
        return jsonify({"error": "..."}), 404
    
    # State-dependent checks
    if sender["balance"] < amount:
        db.execute("ROLLBACK")
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Mutations
    db.execute("UPDATE ... WHERE id = ?", (...))
    db.execute("INSERT INTO ...", (...))
    
    db.execute("COMMIT")
except Exception:
    db.execute("ROLLBACK")
    raise
```

**Key rules:**
- Always use `BEGIN IMMEDIATE` (not plain `BEGIN`) to prevent concurrent writer deadlocks
- All state-dependent reads and writes must be inside the same transaction
- Always `ROLLBACK` before returning an error from inside the transaction
- With `isolation_level=None`, use `db.execute("BEGIN/COMMIT/ROLLBACK")` — not `db.commit()` or `db.rollback()` which are no-ops in autocommit mode

### Flask-SQLAlchemy
```python
try:
    # Multiple session operations
    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

### In-memory
```python
with _lock:
    # All mutations happen together; no partial state visible
    # If validation fails mid-way, simply return error without modifying state
```

## Idempotent Setup

The setup endpoint must produce the same result regardless of how many times it's called:

- **Schema creation**: Use `CREATE TABLE IF NOT EXISTS` (idempotent by nature)
- **Seed data**: Check if data exists before inserting (`SELECT COUNT(*)` or similar)
- **Atomic seeding**: Wrap seed inserts in a transaction to prevent partial seeding if the process dies mid-seed:
  ```python
  existing = db.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()
  if existing["cnt"] == 0:
      db.execute("BEGIN IMMEDIATE")
      try:
          db.execute("INSERT INTO accounts ...")
          db.execute("INSERT INTO accounts ...")
          db.execute("COMMIT")
      except Exception:
          db.execute("ROLLBACK")
          raise
  ```
- **Files**: Check existence before creating; overwrite vs. skip based on spec
- **In-memory**: Clear and re-seed (or check if already seeded)

## Response Patterns

**Success responses** should include:
- The created/modified resource(s) with all relevant fields
- Generated IDs (transaction_id, resource id)
- Computed values (updated balances, totals)

**Common response shapes:**
```python
# Single resource created
return jsonify({"id": new_id, ...fields}), 201

# Resource modified
return jsonify({"resource": {...updated_fields}}), 200

# Operation result
return jsonify({"sender": {...}, "receiver": {...}, "transaction_id": ...}), 200

# List with optional filtering
return jsonify({"resources": [...]}), 200
```

### HTTP Status Code Patterns

**2xx Success**:
- `200 OK`: Standard success for GET, PUT, PATCH, DELETE
- `201 Created`: Resource successfully created (POST that creates)
- `204 No Content`: Success with no response body (rare in this family)

**4xx Client Errors**:
- `400 Bad Request`: Invalid input (missing fields, wrong types, constraint violations)
- `401 Unauthorized`: Authentication required (not in this family)
- `403 Forbidden`: Authenticated but not allowed (not in this family)
- `404 Not Found`: Resource doesn't exist
- `409 Conflict`: State conflict (duplicate, already processed, etc.)

**5xx Server Errors**:
- `500 Internal Server Error`: Unexpected exception (should not happen if code is correct)

### Error Message Consistency

**CRITICAL**: Error messages must match the spec EXACTLY. The evaluator often checks for specific error strings:

```python
# Spec says: {"error": "Cannot transfer to the same account"}
# Your code must return EXACTLY this string, not a variation
return jsonify({"error": "Cannot transfer to the same account"}), 400
```

Common patterns:
- "Missing required fields: field1, field2, field3"
- "Resource not found" / "Account not found"
- "Insufficient balance" / "Insufficient funds"
- "Invalid field type" / "field must be a string"
- "Duplicate resource" / "Resource already exists"

**Always check the spec for exact error messages** — don't paraphrase or reword.

## Testing Approach

When developing and verifying:

1. **Clean state per test**: Remove DB files, reset in-memory state
2. **Setup first**: Always call setup endpoint before domain operations
3. **Test happy paths**: Successful operations with correct responses
4. **Test each error condition**: Missing fields, invalid types, constraint violations
5. **Test idempotency**: Call setup multiple times, verify state consistency
6. **Test atomicity**: Verify that failed operations leave state unchanged
7. **Test state persistence**: Verify that mutations are visible to subsequent requests
8. **Test direct DB access**: The evaluator often connects to the DB file directly (outside the Flask test client) to verify state. Your solution must ensure the DB file is at the same relative path the evaluator expects.

### Evaluator Direct DB Access Pattern

The evaluator frequently tests state by connecting directly to the persistence layer:

```python
# Evaluator test pattern (NOT through Flask test client):
conn = sqlite3.connect("bank.db")  # or whatever the DB name is
cur = conn.cursor()
cur.execute("SELECT ... FROM ...")
```

This means:
- The DB file MUST be at a relative path that resolves correctly from the test runner's cwd
- NEVER pre-compute absolute paths at module import time
- The Flask app and the evaluator's direct connection must target the SAME file

```python
import pytest, os

@pytest.fixture
def client():
    # Clean slate
    if os.path.exists("bank.db"):
        os.remove("bank.db")
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.get("/setup")
        yield c
    # Cleanup
    if os.path.exists("bank.db"):
        os.remove("bank.db")
```

## Decision Checklist

When implementing a new case:

- [ ] Identify the persistence model from the task description
- [ ] Identify all resources and their fields/constraints
- [ ] Identify all endpoints and their HTTP methods
- [ ] Map out state transitions and their atomicity requirements
- [ ] List all error conditions with status codes and **exact error messages from spec**
- [ ] Implement setup endpoint with idempotency
- [ ] Implement domain endpoints with two-phase validation → precondition → mutation → response
- [ ] Verify atomicity of multi-step mutations (BEGIN IMMEDIATE for sqlite3)
- [ ] **CRITICAL: DB/file paths must be relative and resolved at access time, NOT pre-computed at module import**
- [ ] Test all error paths and happy paths
- [ ] Test direct DB/file access (evaluator pattern: connect outside Flask test client)

## Common Service Patterns

### Transfer/Transaction Systems
- Two-phase validation: input checks, then atomic state mutation
- Track both the operation and the resulting state
- Use transaction IDs for audit trails
- Example: bank transfers, inventory movements, state machines

### CRUD Resources
- Standard REST patterns: GET (list/read), POST (create), PUT/PATCH (update), DELETE
- Idempotent setup creates initial resources
- Unique constraints (e.g., unique names, URLs)
- Example: notes, users, products, URL shorteners

### Queue/Task Systems
- Resources have states (pending, processing, completed, failed)
- Atomic state transitions with proper locking
- Optional: TTL, retries, priority
- Example: job queues, task processors, workflow engines

### Aggregation/Analytics
- Compute aggregates (sums, counts, averages) from raw data
- May need to recalculate on each request or cache results
- Example: leaderboards, statistics, reports

### Relationship Management
- Resources have relationships (parent-child, many-to-many)
- Cascading operations (delete parent → delete children)
- Example: folders/files, categories/items, users/groups
