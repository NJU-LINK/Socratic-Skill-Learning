---
name: flask
description: >
  Build stateful JSON HTTP services with Flask. Implements multiple behaviorally
  coupled endpoints sharing mutable domain state, with a lifecycle endpoint for
  initialization. Covers all persistence models (raw sqlite3, Flask-SQLAlchemy,
  in-memory dicts, file manifests, JSONL), validation/error patterns, atomic
  state transitions, and test-client-compatible architecture.
---

# Flask Stateful JSON Service

## 1. Family Recognition

A task belongs to this family when it requires:
- A Flask application exported as `app` from `/app/solve.py`
- Multiple behaviorally coupled endpoints (not a single-route demo)
- Shared mutable domain state across requests
- JSON request/response contracts
- A lifecycle/setup endpoint for initialization
- Evaluation via `app.test_client()` (no live server)

## 2. Systematic Approach

### Step 1: Parse the Task Specification
Extract from the task description:
- **Resource model**: What entities exist? What are their fields, types, constraints?
- **Persistence model**: Which storage backend? (sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl)
- **Endpoints**: Paths, methods, request/response schemas
- **State transitions**: What operations mutate state? What invariants must hold?
- **Validation rules**: What error conditions? What status codes? What error messages?

### Step 2: Design the Architecture
```
/app/solve.py structure:
├── Imports & app creation
├── Persistence layer (varies by model)
├── GET /setup (or equivalent lifecycle endpoint)
├── POST/PUT/DELETE /resource endpoints
└── Helper functions (validation, db access)
```

### Step 3: Implement Persistence Layer
Choose the pattern matching the specified persistence model (see §4).

### Step 4: Implement Endpoints
Follow the validation → transaction → response pattern (see §5).

### Step 5: Test with test_client
See §7 for testing patterns.

## 3. Core Architecture Pattern

Every family member follows this skeleton:

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Persistence layer (varies) ---

@app.route("/setup", methods=["GET"])
def setup():
    """Idempotent initialization: create schema, seed data."""
    # ...
    return jsonify({"status": "ok"}), 200

@app.route("/resource", methods=["POST"])
def create_resource():
    """Validate → begin transaction → read → check invariants → mutate → commit → respond."""
    data = request.get_json()
    # validation...
    # transaction...
    return jsonify({...}), 200/201
```

**Key principle**: Each request gets its own connection/transaction scope. Never share connections across requests at module level (except for in-memory dicts, which are inherently shared).

## 4. Persistence Models

### 4.1 Raw sqlite3

**Critical pitfall**: Python's sqlite3 module has `isolation_level=""` by default, which auto-issues `BEGIN` before DML. If you then explicitly execute `BEGIN`, you get `"cannot start a transaction within a transaction"`.

**Fix**: Always use `isolation_level=None` for manual transaction control:

```python
import sqlite3

def get_connection(db_path):
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row  # dict-like access
    return conn

# Usage pattern:
conn = get_connection("app.db")
try:
    conn.execute("BEGIN")
    # ... reads, validations, writes ...
    conn.execute("COMMIT")
except:
    conn.execute("ROLLBACK")
    raise
finally:
    conn.close()
```

**Setup pattern**:
```python
conn.execute("CREATE TABLE IF NOT EXISTS ...")
# Check before seeding to ensure idempotency:
cursor = conn.execute("SELECT COUNT(*) FROM table")
if cursor.fetchone()[0] == 0:
    conn.execute("INSERT INTO table ...")
```

**Database path pattern**:
```python
# WRONG — caches absolute path at import time
DB_PATH = os.path.join(os.getcwd(), "bank.db")

# RIGHT — relative path resolves at call time
DB_PATH = "bank.db"
```
Always use a relative string for the database path. The test harness may inspect the database directly using `sqlite3.connect("bank.db")`, and both must resolve to the same file. Module-level `os.getcwd()` captures the CWD at import time, which may differ from the CWD when tests run.

### 4.2 Flask-SQLAlchemy

```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# Use relative path for test harness compatibility
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db = SQLAlchemy(app)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields ...

# Setup:
with app.app_context():
    db.create_all()  # idempotent - only creates missing tables
    if Resource.query.count() == 0:
        db.session.add(Resource(...))
        db.session.commit()

# In request handlers:
# db.session operations auto-manage transactions
# db.session.commit() to persist, db.session.rollback() on error
```

**Key differences**:
- Flask-SQLAlchemy manages transaction boundaries. Use `db.session.commit()` and `db.session.rollback()`
- Requires `app.app_context()` for operations outside request handlers
- `sqlite:///app.db` uses a relative path — Flask-SQLAlchemy resolves this relative to the instance folder
- For test harness compatibility, the DB file must be accessible from the test's CWD. If tests use `sqlite3.connect("app.db")`, ensure the SQLAlchemy URI resolves to the same file

### 4.3 In-Memory Dicts

```python
# Module-level state
_state = {
    "resources": {},  # id -> resource dict
    "next_id": 1
}

def reset_state():
    """For test isolation."""
    _state["resources"].clear()
    _state["next_id"] = 1

# In handlers: directly read/write _state
# No connection management, no transactions
# Atomicity is trivial (single-threaded test client)
```

**Key concern**: State persists across requests within the same process. Tests may need a reset mechanism.

### 4.4 File Manifest

```python
import json, os

# Use relative paths — never os.path.join(os.getcwd(), ...) at module level
DATA_DIR = "data"
MANIFEST = os.path.join(DATA_DIR, "manifest.json")

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(MANIFEST):
        with open(MANIFEST, "w") as f:
            json.dump({"next_id": 1, "resources": {}}, f)

def load_manifest():
    with open(MANIFEST) as f:
        return json.load(f)

def save_manifest(data):
    with open(MANIFEST, "w") as f:
        json.dump(data, f)
```

**Key concerns**:
- Use relative paths for test harness compatibility (see §7)
- File I/O must be atomic for concurrent safety. For test-client use (single-threaded), simple read-modify-write suffices
- Handle missing files gracefully in setup (check `os.path.exists` before reading)

### 4.5 JSONL

```python
import json

# Use relative path — never os.path.join(os.getcwd(), ...) at module level
DATA_FILE = "data.jsonl"

def append_record(record):
    with open(DATA_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

def read_all_records():
    records = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            for line in f:
                records.append(json.loads(line))
    return records

def rewrite_all(records):
    with open(DATA_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
```

**Key concerns**:
- Use relative paths for test harness compatibility (see §7)
- JSONL is append-friendly but updates require full rewrite. Good for append-only logs; less ideal for frequent mutations
- Handle missing files gracefully (check `os.path.exists` before reading)

## 5. Validation & Error Strategy

### Validation Ordering (inside transaction)
1. **Parse & check required fields** → 400 if missing
2. **Type/range validation** → 400 if invalid
3. **Resource existence** → 404 if not found (check within transaction for atomicity)
4. **Business rule invariants** → 400 with specific error message
5. **Perform mutation**
6. **Commit & return success**

### Error Response Pattern
```python
# Always return JSON errors with appropriate status codes:
return jsonify({"error": "Specific error message"}), 400  # bad input
return jsonify({"error": "Not found"}), 404               # missing resource
return jsonify({"error": "Server error"}), 500            # unexpected
```

### Input Validation Robustness

```python
# Use silent=True to return None for invalid JSON instead of raising
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid JSON body"}), 400

# Check required fields exist
from_id = data.get("from_id")
to_id = data.get("to_id")
amount = data.get("amount")
if from_id is None or to_id is None or amount is None:
    return jsonify({"error": "Missing required fields"}), 400

# Type validation: reject non-numeric amounts
if not isinstance(amount, (int, float)):
    return jsonify({"error": "Amount must be a number"}), 400

# Range validation
if amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400
```

**Key principles**:
- Use `get_json(silent=True)` to avoid 400 errors from Flask's built-in JSON parsing
- Check field presence with `.get()` and `is None` — handles missing keys and explicit null
- Validate types before ranges — a string amount can't be compared with `<= 0`
- Return specific error messages that match the task spec exactly

### Idempotent Setup
- Use `CREATE TABLE IF NOT EXISTS` (sqlite) or `db.create_all()` (SQLAlchemy)
- Check before seeding: `SELECT COUNT(*)` or `Model.query.count()`
- Setup must be safe to call multiple times without duplicating seed data

## 6. State Transition Patterns

### Atomic Transfer (read-check-write)
```
BEGIN → read sender → read receiver → check existence (404) →
check balance (400) → debit sender → credit receiver →
insert record → COMMIT → return updated state
```

### Idempotent Create
```
Check if resource already exists → if yes, return existing or 409 →
if no, create and return 201
```

### Counter/Aggregate
```
BEGIN → read current value → compute new value → write → COMMIT
```

### Cascading Validation
```
BEGIN → validate parent exists → validate children constraints →
mutate parent → mutate children → COMMIT
```

## 7. Testing with Flask Test Client

```python
from solve import app

client = app.test_client()

# GET requests
resp = client.get("/setup")
assert resp.status_code == 200

# POST with JSON body
resp = client.post("/transfer", json={"from_id": 1, "to_id": 2, "amount": 30})
assert resp.status_code == 200
data = resp.get_json()

# Error cases
resp = client.post("/transfer", json={"from_id": 99, "to_id": 2, "amount": 10})
assert resp.status_code == 404
assert "error" in resp.get_json()
```

**Important**: Each test_client request gets its own request context. Module-level state persists across requests (relevant for in-memory persistence). Database files persist on disk.

### Test Harness Compatibility

Test harnesses often clean up state between test functions. Common patterns:

```python
# Test harness may remove DB before each test
def _setup():
    if os.path.exists("bank.db"):
        os.remove("bank.db")
    return app.test_client()

# Each test function calls _setup() to get a fresh client
client = _setup()
resp = client.get("/setup")  # Recreates tables + seeds
```

**Key implications**:
- Your `/setup` endpoint must handle a missing database file gracefully (CREATE TABLE IF NOT EXISTS works even if file doesn't exist)
- Idempotent seeding (COUNT check) ensures setup works whether DB is fresh or already exists
- Tests may inspect the database directly with `sqlite3.connect("bank.db")` — use relative paths so both app and test resolve to the same file
- For file-based persistence (JSON, JSONL), use relative paths for the same reason

## 8. Common Pitfalls

1. **sqlite3 isolation_level**: Always use `isolation_level=None` for explicit transaction control. Default auto-BEGIN will conflict with manual BEGIN.

2. **Connection lifecycle**: Open connections per-request, close in `finally`. Never hold connections at module level for sqlite3 (file locking issues).

3. **Setup idempotency**: Always guard seed data with existence checks. `CREATE TABLE IF NOT EXISTS` handles schema; check row counts before inserting seed data.

4. **Transaction rollback on error response**: When returning error responses from within a transaction, always ROLLBACK before returning. Forgetting this leaves the connection in a broken state.

5. **Flask-SQLAlchemy app context**: Operations outside request handlers need `with app.app_context():`.

6. **JSON parsing**: `request.get_json()` returns `None` if no JSON body or wrong content-type. Always check for `None` before accessing fields.

7. **Type coercion**: JSON numbers may arrive as int or float. Use explicit type checks if the spec requires specific types.

8. **Database path**: Always use a **relative string** like `"bank.db"` — never `os.path.join(os.getcwd(), ...)` at module level. Module-level path resolution caches the CWD at import time, which may differ from the CWD when the test harness later queries the database directly. A relative string ensures both the app and tests resolve to the same file.

9. **Test harness cleanup**: Tests often remove the database file between test functions. Your `/setup` endpoint must handle a missing database file gracefully — `CREATE TABLE IF NOT EXISTS` works even if the file doesn't exist, and the COUNT-based seed guard ensures correct behavior on both fresh and existing databases.

10. **Input validation ordering**: Validate types before ranges. A string amount can't be compared with `<= 0`. Check `isinstance(amount, (int, float))` before numeric comparisons.

11. **Flask-SQLAlchemy instance folder**: `sqlite:///app.db` resolves relative to Flask's instance folder, not the CWD. If the test harness connects directly with `sqlite3.connect("app.db")`, the paths may not match. Use `sqlite:///./app.db` (note the dot) or `sqlite:////absolute/path` to control resolution explicitly.

## 9. Implementation Checklist

- [ ] `app = Flask(__name__)` exported from `/app/solve.py`
- [ ] Persistence layer matches specified model
- [ ] Database/file path uses relative string (e.g., `"bank.db"`), not `os.path.join(os.getcwd(), ...)`
- [ ] Setup endpoint is idempotent (safe to call multiple times, handles missing DB file)
- [ ] All endpoints return JSON responses with correct status codes
- [ ] Error responses use `{"error": "message"}` format matching task spec exactly
- [ ] Input validation: presence → types → ranges → existence → business rules
- [ ] Transactions are atomic (BEGIN/COMMIT/ROLLBACK for sqlite3)
- [ ] Connections are opened per-request and closed in finally blocks
- [ ] State invariants are maintained (e.g., balance >= 0)
- [ ] Tested with `app.test_client()` and verified direct DB access works
- [ ] Tested with DB file removed between test functions (simulates test harness cleanup)
