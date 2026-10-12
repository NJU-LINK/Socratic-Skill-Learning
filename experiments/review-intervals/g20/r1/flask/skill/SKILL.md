---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  across multiple behaviorally coupled endpoints. Covers all persistence models
  (sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl), input validation,
  atomic state transitions, idempotent setup, and test-client evaluation.
---

# Flask Stateful Service Skill

## Family Overview

Every task in this family requires building a Flask application (`/app/solve.py`) that:
- Exports a Flask `app` object consumed via `app.test_client()`
- Manages mutable domain state through multiple coupled endpoints
- Handles validation, error responses, and state consistency
- Includes a setup/lifecycle endpoint and at least one state-mutating endpoint

## Methodology: Reading a Task Specification

Extract these dimensions from the task.yaml instruction:

1. **Resource model**: What entities exist? What are their fields, types, constraints?
2. **Persistence model**: Which of the five persistence strategies to use
3. **Endpoint contracts**: Route paths, HTTP methods, request/response schemas, status codes
4. **State transition semantics**: Atomicity requirements, idempotency, cascading rules
5. **Validation & failure behavior**: Exact error messages, status codes, and which fields trigger them

## Universal Flask App Skeleton

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# Persistence layer initialization goes here (varies by model)

@app.route("/setup", methods=["GET"])
def setup():
    """Idempotent initialization. Must be safe to call multiple times."""
    # Create schema / initialize state
    # Seed data only if not already present
    return jsonify({"status": "ok"}), 200

# Additional routes follow the task's endpoint_contract spec
```

## Persistence Model Implementations

### Critical: File Path Resolution Timing

**Never compute file paths at module import time when they depend on `os.getcwd()`.**

The test environment may import your module from one directory (e.g., `/app`) but change the working directory before making requests or opening direct database connections. If you set `DB_PATH = os.path.join(os.getcwd(), "bank.db")` at module level, the path is frozen at import time and won't match where the test expects the file.

**Wrong** (path frozen at import time):
```python
DB_PATH = os.path.join(os.getcwd(), "bank.db")  # Frozen when module loads

def get_db():
    g.db = sqlite3.connect(DB_PATH)  # Always uses the import-time path
```

**Correct** (path computed at request time):
```python
def get_db_path():
    return os.path.join(os.getcwd(), "bank.db")  # Computed per-request

def get_db():
    g.db = sqlite3.connect(get_db_path())  # Uses current cwd
```

This ensures the Flask app and any direct `sqlite3.connect("bank.db")` calls in tests resolve to the same file, regardless of when the module was imported.

### sqlite3 (raw SQLite)

**Connection pattern**: Use Flask's `g` object for per-request connections.

**Critical: `isolation_level=None`**

Python's `sqlite3` module has a default `isolation_level=""` that causes it to auto-manage transactions: before any DML (INSERT/UPDATE/DELETE), Python auto-starts an implicit transaction if one isn't already active. This conflicts with explicit `BEGIN`/`COMMIT`/`ROLLBACK` control. If any DML executes before your explicit `BEGIN`, you get `"cannot start a transaction within a transaction"`.

Always use `isolation_level=None` to disable Python's implicit transaction layer:

```python
import sqlite3, os
from flask import g

def get_db_path():
    """Compute path at request time, not import time."""
    return os.path.join(os.getcwd(), "task.db")

def get_db():
    if "db" not in g:
        # isolation_level=None: Python never auto-starts/commits transactions.
        # All transaction control is explicit via BEGIN/COMMIT/ROLLBACK.
        g.db = sqlite3.connect(get_db_path(), isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

**Why this matters**: With the default `isolation_level=""`, any DML before an explicit `BEGIN` (e.g., a "touch timestamp" UPDATE, or a denormalized counter increment) causes Python to start an implicit transaction. Then `BEGIN` fails with `"cannot start a transaction within a transaction"`. Setting `isolation_level=None` eliminates this entire class of bugs — you have full, predictable control.

**Setup**: `CREATE TABLE IF NOT EXISTS` + conditional seeding (check `SELECT COUNT(*)` before inserting). Setup connections can also use `isolation_level=None` and explicit `BEGIN`/`COMMIT`, or simply use autocommit (each statement commits immediately) since setup is typically single-statement.

**Atomicity**: Explicit `BEGIN` / `COMMIT` / `ROLLBACK`:
```python
db = get_db()
db.execute("BEGIN")
try:
    # ... reads and writes ...
    db.execute("COMMIT")
except Exception:
    db.execute("ROLLBACK")
    raise
```

**Key detail**: When returning from within a transaction (e.g., error responses), always `ROLLBACK` before returning. The connection is per-request via `g`, so uncommitted transactions are abandoned on close, but explicit rollback is safer and clearer.

**Getting inserted row IDs**: After an INSERT, use `cursor.lastrowid` (cleaner) instead of `SELECT last_insert_rowid()`:
```python
cursor = db.execute("INSERT INTO ...", (...))
new_id = cursor.lastrowid
```
Both work, but `cursor.lastrowid` is more Pythonic and avoids an extra query.

**Thread safety note**: For production servers (not test client), add `check_same_thread=False` to `sqlite3.connect()` if connections might be shared across threads. For test-client evaluation, this is not needed.

### flask_sqlalchemy

**Setup pattern**:
```python
from flask_sqlalchemy import SQLAlchemy

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///task.db"
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields ...

@app.route("/setup")
def setup():
    with app.app_context():
        db.create_all()
        if Account.query.count() == 0:
            # seed data
            db.session.commit()
    return jsonify({"status": "ok"})
```

**Atomicity**: Use `db.session` transaction management:
```python
try:
    # ... operations ...
    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

**Important**: Within request handlers, `db.session` is automatically managed. For setup outside a request context, wrap in `app.app_context()`.

### in_memory

**Pattern**: Module-level or app-level dictionaries. Use `app.config` or a dedicated state holder.

```python
# State holder
_state = {"accounts": {}, "next_id": 1}

@app.route("/setup")
def setup():
    if not _state["accounts"]:
        _state["accounts"][1] = {"id": 1, "owner": "Alice", "balance": 100.0}
        _state["next_id"] = 2
    return jsonify({"status": "ok"})
```

**Atomicity**: For multi-step mutations, snapshot-then-swap or validate-then-mutate:
```python
# Validate all preconditions first, then mutate
# Since Python dict operations are single-threaded in CPython,
# the GIL provides basic atomicity for simple operations.
# For compound operations, validate everything before any mutation.
```

**Key concern**: In-memory state is lost on process restart. This is expected per spec. Tests that call `/setup` first will reinitialize.

### file_manifest

**Pattern**: JSON file(s) with a manifest tracking state metadata.

```python
import json, os

def get_data_path():
    return os.path.join(os.getcwd(), "data.json")

def get_manifest_path():
    return os.path.join(os.getcwd(), "manifest.json")

def load_data():
    path = get_data_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_data(data):
    # Write to temp file, then atomic rename
    path = get_data_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
```

**Atomicity**: Write to a temporary file, then `os.replace()` (atomic on POSIX). The manifest tracks version/sequence for consistency.

### jsonl

**Pattern**: Append-only log file. State is derived by replaying entries.

```python
import json, os

def get_log_path():
    return os.path.join(os.getcwd(), "state.jsonl")

def append_entry(entry):
    with open(get_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")

def replay_state():
    """Rebuild current state from the JSONL log."""
    state = {}
    path = get_log_path()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                entry = json.loads(line.strip())
                # Apply entry to state
    return state
```

**Atomicity**: Append operations are atomic for small writes (< PIPE_BUF). For compound operations, append all entries in sequence; if a write fails mid-sequence, the replay logic should handle partial states or use a marker entry.

## Validation Pattern

Always validate in this order:
1. **Parse request**: `request.get_json(silent=True)` — return 400 if None and body expected
2. **Required fields**: Check each required field is present and non-None — return 400
3. **Type validation**: Check types match expected (int, float, str, etc.) — return 400
4. **Value validation**: Check ranges, positivity, uniqueness constraints — return 400
5. **Existence checks**: Verify referenced resources exist — return 404
6. **Business logic**: Check state-dependent conditions (balance, capacity, etc.) — return 400

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid or missing JSON body"}), 400

# Required fields
for field in ("field_a", "field_b"):
    if field not in data or data[field] is None:
        return jsonify({"error": f"Missing required field: {field}"}), 400

# Type checks
if not isinstance(data["amount"], (int, float)):
    return jsonify({"error": "amount must be a number"}), 400

# Value checks (use exact error messages from task spec)
if data["amount"] <= 0:
    return jsonify({"error": "Amount must be positive"}), 400
```

**Critical**: Use the exact error message strings specified in the task. Tests will match them verbatim.

**Python gotcha — booleans are ints**: In Python, `bool` is a subclass of `int`, so `isinstance(True, int)` returns `True`. If a task expects numeric fields, explicitly reject booleans:
```python
if isinstance(value, bool) or not isinstance(value, (int, float)):
    return jsonify({"error": "..."}), 400
```
Without this check, `True`/`False` would pass numeric validation and be treated as `1`/`0`.

## Response Patterns

### Success responses
- Return the specified JSON schema with correct status code (usually 200)
- Include computed/derived values (new balances, generated IDs, timestamps)
- For created resources, consider 201 status if specified

### Error responses
- Always return JSON: `{"error": "exact message from spec"}`
- Use the status code specified in the task (400 for validation, 404 for not found, 409 for conflicts)
- Error responses must NOT modify persistent state

## Idempotent Setup

The `/setup` endpoint must be safely callable multiple times:
- Use `CREATE TABLE IF NOT EXISTS` (sqlite3) or `db.create_all()` (SQLAlchemy)
- Check if seed data already exists before inserting: `SELECT COUNT(*)` or equivalent
- For in-memory: check if state dict is populated
- For file-based: check if data file exists and has content

**Critical: Idempotency + Atomicity**

Idempotency (safe to call again) and atomicity (all-or-nothing) are separate concerns. A setup that is idempotent but not atomic can leave the database in a partially-initialized state if a seed insert fails mid-way.

**The vulnerability:** If you insert Alice, then Bob's insert fails (disk full, connection drop), Alice is committed but Bob is not. On the next setup call, `COUNT(*) == 1` (not 0), so seeding is skipped entirely. Bob is permanently missing.

**The fix:** Wrap the entire seed operation in a single transaction. The idempotency check (`COUNT(*) == 0`) must be INSIDE the transaction, not outside:

```python
@app.route("/setup")
def setup():
    db = sqlite3.connect(get_db_path(), isolation_level=None)
    try:
        # DDL is safe (IF NOT EXISTS) — no transaction needed
        db.execute("CREATE TABLE IF NOT EXISTS accounts (...)")
        
        # Wrap seeding in a transaction for atomicity
        db.execute("BEGIN")
        existing = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if existing == 0:
            db.execute("INSERT INTO accounts ...", (1, "Alice", 100.0))
            db.execute("INSERT INTO accounts ...", (2, "Bob", 50.0))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    return jsonify({"status": "ok"}), 200
```

Now if Bob's insert fails, the entire seed rolls back. COUNT(*) stays 0, and the next setup call correctly re-attempts seeding.

**Apply to all persistence models:**
- **sqlite3**: Explicit BEGIN/COMMIT around seed inserts
- **flask_sqlalchemy**: `db.session.commit()` only after ALL seeds (session batches automatically)
- **in_memory**: Build complete state dict first, then assign in one operation
- **file_manifest/jsonl**: Write complete file in one operation (write-to-temp then rename)

## Testing Strategy

Tests use `app.test_client()`:

```python
import pytest, os
from solve import app

@pytest.fixture
def client():
    # Clean state before each test
    if os.path.exists("task.db"):
        os.remove("task.db")
    with app.test_client() as c:
        c.get("/setup")  # Initialize
        yield c
    # Cleanup after
    if os.path.exists("task.db"):
        os.remove("task.db")

def test_basic_operation(client):
    resp = client.post("/endpoint", json={...})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["field"] == expected_value
```

**Key testing patterns**:
- Clean DB/state before each test for isolation
- Test happy path first, then each error condition
- Verify state consistency after failed operations
- Test idempotency by calling setup multiple times

### Test-DB Interaction Pattern

Tests in this family often open **direct database connections** (e.g., `sqlite3.connect("bank.db")`) alongside Flask test client requests. This means:

1. The Flask app and the test must access the **same database file**
2. The DB path must resolve identically for both — use `os.getcwd()` at request time, not import time (see "File Path Resolution Timing" above)
3. Tests may verify state by querying the DB directly after HTTP operations
4. The `_setup()` helper in tests may or may not call `/setup` — your code must handle both patterns:
   - Some tests call `_setup()` which creates a test client but doesn't call `/setup`, then the test itself calls `client.get("/setup")`
   - Other tests call `_setup()` which both creates the client AND calls `/setup`
   - Your `/setup` endpoint must be idempotent so it works correctly in both cases

**Implication for all persistence models:**
- **sqlite3**: Use `get_db_path()` function, not module-level `DB_PATH` constant
- **flask_sqlalchemy**: Use relative URI `sqlite:///task.db` (resolved at connection time)
- **in_memory**: Not affected (no file path)
- **file_manifest/jsonl**: Same principle — compute file paths at access time, not import time

## Decision Checklist

When implementing a new task:

- [ ] Identify the persistence model from the task spec
- [ ] Set up the appropriate connection/state management
- [ ] Use `get_db_path()` function (not module-level constant) for file-based persistence
- [ ] Use `isolation_level=None` for sqlite3 connections
- [ ] Implement `/setup` with idempotent schema creation and atomic conditional seeding
- [ ] Implement each endpoint with the exact route paths and methods specified
- [ ] Add validation in the order: parse → required → type → value → existence → business logic
- [ ] Reject booleans for numeric fields (`isinstance(value, bool)` check before `isinstance(value, (int, float))`)
- [ ] Use exact error messages from the spec
- [ ] Ensure atomicity for state-mutating operations (explicit BEGIN/COMMIT/ROLLBACK)
- [ ] Use `cursor.lastrowid` to get inserted row IDs
- [ ] Return the exact response schema specified
- [ ] Test with Flask test client, covering all error paths
- [ ] Test direct DB access pattern (tests may open `sqlite3.connect("db")` alongside Flask client)
