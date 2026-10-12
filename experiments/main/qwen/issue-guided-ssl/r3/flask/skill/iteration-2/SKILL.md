---
name: flask
description: >
  Reusable procedure for building JSON HTTP services with Flask that manage
  mutable domain state across behaviorally coupled endpoints. Covers the
  invariant family shape: lifecycle/setup endpoint, domain endpoints with
  state transitions, validation/error contracts, and persistence lifecycle.
  Parameterized over resource model, persistence model (sqlite3,
  flask_sqlalchemy, in_memory, file_manifest, jsonl), endpoint contracts,
  state transition semantics, and validation/failure behavior.
---

# Flask Stateful JSON Service — Family Skill

## 1. Invariant Family Shape

Every member of this family implements a Flask application (`app`) that:

1. **Exposes a lifecycle/setup endpoint** — creates schema or initializes state, must be idempotent
2. **Exposes one or more domain endpoints** — perform state transitions on shared mutable state
3. **Enforces a validation/error contract** — specific JSON error bodies with specific HTTP status codes; failed requests must leave persistent state consistent
4. **Binds via Flask test client** — evaluation imports `from solve import app` and uses `app.test_client()`

### 1.1 Skeleton Procedure

```python
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Persistence initialization (varies by persistence_model) ---
# See §2 for persistence-specific setup

# --- Lifecycle endpoint ---
@app.route('/setup', methods=['GET'])
def setup():
    """Idempotent initialization. See §3."""
    ...
    return jsonify({"status": "ok"}), 200

# --- Domain endpoints ---
# Route paths, methods, request/response schemas vary per case.
# All domain endpoints follow the pattern in §4.

# --- Error contract ---
# All errors return JSON with at least {"error": "<message>"}
# Status codes: 400 (client error), 404 (not found), 500 (server error)
# See §5 for validation ordering.
```

## 2. Persistence Model Procedures

### 2.1 sqlite3 (Raw SQLite)

**Connection lifecycle**: One connection per request, stored in Flask `g`, closed on teardown.

**CRITICAL**: Compute DB path at **request time** inside `get_db()`, NOT at module import time. The evaluator may import the module from a different CWD than where tests execute, causing the app to write to a different file than the evaluator verifies.

```python
import sqlite3
from flask import g

def get_db():
    if 'db' not in g:
        # Compute path at REQUEST TIME, not import time
        db_path = os.path.join(os.getcwd(), '<dbname>.db')
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Transaction atomicity** (critical for multi-step state transitions):

```python
db = get_db()
db.execute("BEGIN")
try:
    # 1. Read current state (SELECT)
    # 2. Validate business rules
    # 3. Mutate state (UPDATE/INSERT/DELETE)
    # 4. Record audit trail if needed
    db.execute("COMMIT")
except Exception:
    db.execute("ROLLBACK")
    raise
```

**Key subtlety**: Python's `sqlite3` module with default `isolation_level=""` auto-starts transactions on DML but NOT on SELECT. A read-then-write sequence is NOT atomic unless you issue an explicit `BEGIN`. Always use explicit `BEGIN`/`COMMIT`/`ROLLBACK` for any endpoint that reads state and then conditionally mutates it.

**Idempotent setup**:
```python
db.execute("CREATE TABLE IF NOT EXISTS ...")
# For seed data: check-then-insert or INSERT OR IGNORE
existing = db.execute("SELECT COUNT(*) FROM <table>").fetchone()[0]
if existing == 0:
    db.execute("INSERT INTO ...")
    db.commit()
```

### 2.2 flask_sqlalchemy (SQLAlchemy ORM)

**Setup**:

**CRITICAL**: Configure the database URI at request time or in a before_first_request hook, not at module level. Use a dynamic path based on current working directory.

```python
from flask_sqlalchemy import SQLAlchemy

# Configure in app factory or before_first_request, not at module level
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(os.getcwd(), "<dbname>.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields with constraints
```

Alternatively, use a before_request hook to set the URI dynamically:
```python
@app.before_request
def set_db_path():
    if 'SQLALCHEMY_DATABASE_URI' not in app.config or app.config['SQLALCHEMY_DATABASE_URI'] is None:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(os.getcwd(), "<dbname>.db")}'
```

**Transaction atomicity**: SQLAlchemy auto-manages transactions within a request. Use explicit session control for complex operations:

```python
try:
    # reads and writes within same session
    db.session.commit()
except Exception:
    db.session.rollback()
    raise
```

**Idempotent setup**: Use `db.create_all()` (safe to call repeatedly) and check-then-insert for seeds.

### 2.3 in_memory (Process-Local Dictionaries)

**Setup**: Module-level dicts/lists. Reset by clearing them.

**Note**: For in-memory storage, the "path" is not a file path but the storage location itself. Since it's process-local, there's no CWD issue. However, ensure the store is initialized lazily (on first access) rather than at module import time to avoid issues with test isolation.

```python
# Module-level state (initialized lazily)
_store = None

def get_store():
    global _store
    if _store is None:
        _store = {"resources": {}, "counter": 0}
    return _store

def reset_state():
    global _store
    _store = {"resources": {}, "counter": 0}
```

**Transaction atomicity**: Not needed for single-process, single-threaded test client. For thread safety, use `threading.Lock`. State mutations are inherently atomic in CPython due to GIL for simple operations, but use locks for read-modify-write sequences.

**Idempotent setup**: Check if state is already initialized before seeding.

### 2.4 file_manifest (File + Manifest)

**Setup**: A data file stores serialized state; a manifest file tracks metadata (version, checksum, etc.).

**CRITICAL**: Compute file paths at request time, not at module import time.

```python
import json

def get_data_file():
    # Compute at request time, not import time
    return os.path.join(os.getcwd(), '<data>.json')

def get_manifest_file():
    return os.path.join(os.getcwd(), '<manifest>.json')

def read_state():
    data_file = get_data_file()
    if os.path.exists(data_file):
        with open(data_file) as f:
            return json.load(f)
    return None

def write_state(state):
    data_file = get_data_file()
    manifest_file = get_manifest_file()
    # Atomic write: write to temp file, then rename
    tmp_path = data_file + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(state, f)
    os.replace(tmp_path, data_file)
    # Update manifest
    manifest = {"version": state.get("version", 0), "updated": True}
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f)
```

**Transaction atomicity**: Use write-to-temp-then-rename pattern to prevent corruption.

**Idempotent setup**: Check if data file exists before creating/seeding.

### 2.5 jsonl (JSON Lines)

**Setup**: Append-only log file. Each line is a JSON record.

**CRITICAL**: Compute file paths at request time, not at module import time.

```python
def get_data_file():
    # Compute at request time, not import time
    return os.path.join(os.getcwd(), '<data>.jsonl')

def read_all_records():
    data_file = get_data_file()
    records = []
    if os.path.exists(data_file):
        with open(data_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records

def append_record(record):
    data_file = get_data_file()
    with open(data_file, 'a') as f:
        f.write(json.dumps(record) + '\n')
```

**Transaction atomicity**: Append operations are atomic for small writes on most filesystems. For compound operations, reconstruct state from all records, validate, then append.

**Idempotent setup**: Check if file exists and has content before seeding.

## 3. Lifecycle/Setup Endpoint

The `/setup` endpoint (or equivalent lifecycle endpoint) must:

1. **Create schema or initialize state** — using idempotent operations (`CREATE TABLE IF NOT EXISTS`, check-then-insert, etc.)
2. **Seed initial data** — only if state is empty/uninitialized
3. **Return 200** with a JSON status body every time, even on repeated calls
4. **Never fail on repeated calls** — the entire point is idempotency

**Idempotency patterns by persistence model**:
- **sqlite3**: `CREATE TABLE IF NOT EXISTS` + `SELECT COUNT(*)` guard before seed inserts
- **flask_sqlalchemy**: `db.create_all()` + existence check before seed inserts
- **in_memory**: Check if store is empty before seeding
- **file_manifest**: Check if data file exists before creating
- **jsonl**: Check if file exists and has content before seeding

## 4. Domain Endpoint Pattern

Every domain endpoint follows this structure:

```python
@app.route('/<path>', methods=['<METHOD>'])
def domain_operation():
    # 1. Parse and validate input (see §5)
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    # 2. Extract and validate required fields
    # 3. Validate business rules (domain invariants)
    # 4. Begin transaction (if applicable)
    # 5. Read current state
    # 6. Check preconditions (existence, sufficiency, uniqueness)
    # 7. Mutate state
    # 8. Record audit trail if required
    # 9. Commit transaction
    # 10. Return success response with updated state

    return jsonify({...}), 200
```

**State transition semantics** vary per case but commonly include:
- Atomic transfers (debit one, credit another)
- CRUD operations with uniqueness constraints
- Counter increments/decrements
- Aggregate computations
- Cascading validation across related entities
- Checkout/consumption (mark as used)

## 5. Validation Ordering Checklist

Validate in this order to match expected error semantics:

1. **Request format** — Is the body valid JSON? → 400
2. **Required fields present** — Are all mandatory fields in the body? → 400
3. **Field type/range validation** — Are types correct? Are values in valid ranges? → 400
4. **Domain-specific structural checks** — e.g., from_id != to_id, no self-references → 400
5. **Resource existence** — Do referenced resources exist? → 404
6. **Business rule preconditions** — e.g., sufficient balance, not already checked out → 400
7. **Uniqueness/conflict checks** — e.g., duplicate names, conflicting routes → 409

**Critical**: Getting the order wrong produces the wrong status code. For example, checking resource existence before field validation would return 404 when the spec expects 400 for missing fields.

**Error response format** (invariant across family):
```python
return jsonify({"error": "<specific error message>"}), <status_code>
```

## 6. Implementation Binding Notes

### Flask Test Client

Evaluation always uses:
```python
from solve import app
client = app.test_client()
resp = client.get('/setup')
resp = client.post('/transfer', json={...})
```

**Key requirements**:
- The Flask application object must be named `app` at module level in `solve.py`
- `solve.py` must be at `/app/solve.py`
- Do NOT wrap code in Markdown fences
- The file must be importable without side effects that prevent testing

### Database/File Paths

**CRITICAL**: **ALWAYS** compute persistence paths at **request time** (inside `get_db()`, endpoint handlers, or accessor functions), **NEVER** at module import time.

- The evaluator may import `solve.py` from a different CWD than where tests execute
- Module-level `DB_PATH = os.path.join(os.getcwd(), 'bank.db')` captures CWD at import time, which may differ from CWD at test execution time
- This causes the app to write to a different file than the evaluator verifies, resulting in "no such table" errors

**Correct pattern**:
```python
def get_db():
    if 'db' not in g:
        db_path = os.path.join(os.getcwd(), 'bank.db')  # Request time!
        g.db = sqlite3.connect(db_path)
        ...
```

**Wrong pattern**:
```python
DB_PATH = os.path.join(os.getcwd(), 'bank.db')  # Import time - WRONG!
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        ...
```

- Tests may change CWD or clean up files between tests
- Never hardcode absolute paths
- For test fixtures: clean up DB/files in `autouse` fixtures

### Testing Patterns

```python
@pytest.fixture(autouse=True)
def clean_state():
    """Remove persistence artifacts before each test."""
    # Remove DB files, data files, etc.
    yield

@pytest.fixture
def client():
    from solve import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
```

## 7. Worked Reference: Bank Transfer (v01)

**Resource model**: Accounts with balances, transactions as audit trail.
**Persistence**: sqlite3 with manual transaction control.
**Endpoints**: GET /setup (idempotent), POST /transfer (atomic debit/credit).

**Key implementation decisions**:
- Explicit `BEGIN`/`COMMIT`/`ROLLBACK` for transfer atomicity
- `row_factory = sqlite3.Row` for dict-like access
- **DB path computed at request time inside `get_db()`**, not at module import time (critical for evaluator compatibility)
- Validation order: missing fields → same account → amount positive → account exists → sufficient balance
- Idempotent setup via `CREATE TABLE IF NOT EXISTS` + count check before seeding

**Error contract**:
| Condition | Status | Error Message |
|-----------|--------|---------------|
| Missing fields | 400 | "Missing required fields: ..." |
| Same account | 400 | "Cannot transfer to the same account" |
| Amount ≤ 0 | 400 | "Amount must be positive" |
| Account not found | 404 | "Account not found" |
| Insufficient balance | 400 | "Insufficient balance" |

## 8. Adaptation Checklist for New Family Members

When encountering a new task in this family:

1. **Identify the resource model** — What entities? What fields? What invariants?
2. **Identify the persistence model** — Match to §2.x procedure
3. **Map the endpoint contract** — What routes? What methods? What request/response schemas?
4. **Map the state transition semantics** — What operations? What atomicity requirements?
5. **Map the validation/failure behavior** — What errors? What status codes? What consistency guarantees?
6. **Apply the invariant skeleton** (§1.1) with persistence-specific setup (§2.x)
7. **Follow validation ordering** (§5) using the case-specific error messages
8. **Test atomicity** — Verify that failed operations leave state unchanged
