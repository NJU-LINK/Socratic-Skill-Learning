---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  through multiple coupled endpoints. Covers persistence backends (SQLite3,
  Flask-SQLAlchemy, in-memory, file-based), transactional operations, input
  validation, error handling, and idempotent setup/lifecycle endpoints.
---

# Flask Stateful JSON Service

## Core Architecture

Every case in this family requires:
- A Flask application object named `app` exported from `/app/solve.py`
- Multiple behaviorally coupled endpoints sharing mutable state
- JSON request/response contracts
- Tests run via `app.test_client()` without a live server

## Flask Application Scaffolding

```python
from flask import Flask, request, jsonify, g

app = Flask(__name__)
```

The app must be importable: `from solve import app`.

## Persistence Patterns

### SQLite3 (Raw)

**Database path resolution** - CRITICAL: match how tests verify the database:

```python
import os

# Option A: Relative path (CORRECT for most cases)
# Use when task says "database in current working directory"
# Tests verify by opening the file from their CWD, so this ensures alignment
DATABASE = "bank.db"

# Option B: Explicit absolute path
# Use ONLY when task specifies an exact location like "/app/data.db"
DATABASE = "/app/bank.db"
```

**AVOID `__file__`-based paths** like `os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank.db")`. This decouples the database location from the process CWD, breaking the contract when tests open the database directly with `sqlite3.connect("bank.db")` from their own CWD. The task says "in the current working directory" - use a relative path to honor that.

**Why this matters**: Tests often verify database state by opening the file directly:
```python
conn = sqlite3.connect("bank.db")  # opens from test's CWD
cur.execute("SELECT ...")
```
If your app creates the DB at a different location (e.g., via `__file__`), the test opens an empty file and fails with "no such table".

**Broader principle**: When multiple independent consumers (your app and a test) share a side-effect artifact (a database file, log file, uploaded file, etc.), the path resolution strategy must be **coordinated across all consumers**, not independently optimized. "Safer for one party" can mean "broken for the shared contract." Always check how tests verify state and match that resolution strategy.

**Connection management** - use Flask's `g` object for per-request connections:

```python
import sqlite3
from flask import g

def get_db():
    if "db" not in g:
        # isolation_level=None disables Python's implicit transaction management
        # giving full manual control with BEGIN/COMMIT/ROLLBACK
        g.db = sqlite3.connect(DATABASE, isolation_level=None)
        g.db.row_factory = sqlite3.Row  # dict-like access to columns
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()
```

**Critical detail**: Python's sqlite3 module has `isolation_level=''` by default, which auto-starts transactions on DML statements. This conflicts with explicit `BEGIN` calls. Set `isolation_level=None` for manual transaction control.

**Transactional operations**:

```python
db = get_db()
try:
    db.execute("BEGIN")
    # ... read and write operations ...
    db.execute("COMMIT")
except Exception as e:
    db.execute("ROLLBACK")
    raise
```

### Flask-SQLAlchemy

Flask-SQLAlchemy uses **scoped sessions** - `db.session` is automatically per-request and managed by SQLAlchemy's session factory. This is fundamentally different from raw sqlite3's manual transaction control.

**Setup and configuration**:

```python
from flask_sqlalchemy import SQLAlchemy

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False  # avoid deprecation warning
db = SQLAlchemy(app)

class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    balance = db.Column(db.Float, nullable=False, check_constraint="balance >= 0")

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_id = db.Column(db.Integer, nullable=False)
    to_id = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String)
```

**Setup endpoint** - use `db.create_all()` for idempotent table creation:

```python
@app.route("/setup", methods=["GET"])
def setup():
    db.create_all()  # creates tables if they don't exist
    
    # Seed data only if empty
    if db.session.query(Account).count() == 0:
        db.session.add_all([
            Account(id=1, owner="Alice", balance=100.0),
            Account(id=2, owner="Bob", balance=50.0)
        ])
        db.session.commit()
    
    return jsonify({"status": "ok"})
```

**Transactional operations** - no manual BEGIN/COMMIT, use session methods:

```python
@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json()
    from_id = data.get("from_id")
    to_id = data.get("to_id")
    amount = data.get("amount")
    
    try:
        # Query using session
        sender = db.session.get(Account, from_id)
        if sender is None:
            return jsonify({"error": "Account not found"}), 404
        
        receiver = db.session.get(Account, to_id)
        if receiver is None:
            return jsonify({"error": "Account not found"}), 404
        
        if sender.balance < amount:
            return jsonify({"error": "Insufficient balance"}), 400
        
        # Mutate objects - SQLAlchemy tracks changes
        sender.balance -= amount
        receiver.balance += amount
        
        # Create related record
        tx = Transaction(from_id=from_id, to_id=to_id, amount=amount)
        db.session.add(tx)
        
        # Commit all changes atomically
        db.session.commit()
        
        return jsonify({
            "sender": {"id": sender.id, "balance": sender.balance},
            "receiver": {"id": receiver.id, "balance": receiver.balance},
            "transaction_id": tx.id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
```

**Critical teardown** - must call `db.session.remove()` to return session to pool:

```python
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()  # returns session to pool, prevents leaks
```

**Key differences from raw sqlite3**:
- No manual `BEGIN`/`COMMIT`/`ROLLBACK` - use `db.session.commit()` and `db.session.rollback()`
- Objects are tracked automatically - mutations are detected and persisted on commit
- `db.session.get(Model, id)` for primary key lookups
- `db.session.add(obj)` for inserts
- `db.session.remove()` in teardown is mandatory for scoped sessions

### In-Memory (Process-Local Dictionaries)

In-memory state persists across requests within the same process. The critical design decision is **reset semantics** vs **seed-if-empty**:

**Option A: Seed-if-empty** (additive idempotency):

```python
accounts = {}
transactions = []
next_tx_id = 0

@app.route("/setup")
def setup():
    global accounts, transactions, next_tx_id
    if not accounts:  # only seed if empty
        accounts = {
            1: {"id": 1, "owner": "Alice", "balance": 100.0},
            2: {"id": 2, "owner": "Bob", "balance": 50.0}
        }
    return jsonify({"status": "ok"})
```

**Option B: Reset to known state** (active reset):

```python
accounts = {}
transactions = []
next_tx_id = 0

@app.route("/setup")
def setup():
    global accounts, transactions, next_tx_id
    # Always reset to known state - idempotent = always produces same result
    accounts = {
        1: {"id": 1, "owner": "Alice", "balance": 100.0},
        2: {"id": 2, "owner": "Bob", "balance": 50.0}
    }
    transactions = []
    next_tx_id = 0
    return jsonify({"status": "ok"})
```

**Choosing between them**: The task spec determines which is correct. Some tasks expect `/setup` to preserve existing state (seed-if-empty), others expect it to reset to a clean state (active reset). When in doubt, check if the task mentions "reset" or "idempotent" - "idempotent" usually means seed-if-empty, "reset" means active reset.

**Transactional operations** - no actual transactions needed, but maintain consistency:

```python
@app.route("/transfer", methods=["POST"])
def transfer():
    global next_tx_id
    data = request.get_json()
    from_id = data.get("from_id")
    to_id = data.get("to_id")
    amount = data.get("amount")
    
    # Validation (same as other backends)
    if from_id not in accounts:
        return jsonify({"error": "Account not found"}), 404
    if to_id not in accounts:
        return jsonify({"error": "Account not found"}), 404
    if accounts[from_id]["balance"] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Perform operation (atomic in single-threaded Flask)
    accounts[from_id]["balance"] -= amount
    accounts[to_id]["balance"] += amount
    
    next_tx_id += 1
    transactions.append({
        "id": next_tx_id,
        "from_id": from_id,
        "to_id": to_id,
        "amount": amount
    })
    
    return jsonify({
        "sender": {"id": from_id, "balance": accounts[from_id]["balance"]},
        "receiver": {"id": to_id, "balance": accounts[to_id]["balance"]},
        "transaction_id": next_tx_id
    }), 200
```

**Note**: In-memory state is not thread-safe. For concurrent requests, you'd need locks, but Flask's test client is single-threaded, so this is usually not a concern for testing.

### File Manifest / JSONL

File-based persistence requires atomic writes to prevent corruption. Use the write-to-temp-then-rename pattern:

```python
import json
import os

DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"accounts": {}, "transactions": [], "next_tx_id": 0}

def save_data(data):
    # Write to temp file then rename for atomicity
    with open(DATA_FILE + ".tmp", "w") as f:
        json.dump(data, f, indent=2)
    os.rename(DATA_FILE + ".tmp", DATA_FILE)
```

**Setup endpoint**:

```python
@app.route("/setup", methods=["GET"])
def setup():
    data = load_data()
    if not data["accounts"]:  # seed if empty
        data["accounts"] = {
            "1": {"id": 1, "owner": "Alice", "balance": 100.0},
            "2": {"id": 2, "owner": "Bob", "balance": 50.0}
        }
        save_data(data)
    return jsonify({"status": "ok"})
```

**Transactional operations** - load, mutate, save:

```python
@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json()
    from_id = str(data["from_id"])
    to_id = str(data["to_id"])
    amount = data["amount"]
    
    state = load_data()
    
    # Validation
    if from_id not in state["accounts"]:
        return jsonify({"error": "Account not found"}), 404
    if to_id not in state["accounts"]:
        return jsonify({"error": "Account not found"}), 404
    
    sender = state["accounts"][from_id]
    receiver = state["accounts"][to_id]
    
    if sender["balance"] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Mutate state
    sender["balance"] -= amount
    receiver["balance"] += amount
    
    state["next_tx_id"] += 1
    state["transactions"].append({
        "id": state["next_tx_id"],
        "from_id": int(from_id),
        "to_id": int(to_id),
        "amount": amount
    })
    
    # Save atomically
    save_data(state)
    
    return jsonify({
        "sender": {"id": int(from_id), "balance": sender["balance"]},
        "receiver": {"id": int(to_id), "balance": receiver["balance"]},
        "transaction_id": state["next_tx_id"]
    }), 200
```

**Note**: JSON keys must be strings, so convert integer IDs to strings when using them as dictionary keys. Convert back to integers in responses.

## Idempotent Setup/Lifecycle Endpoints

Setup endpoints must be safe to call multiple times:

```python
@app.route("/setup", methods=["GET"])
def setup():
    db = get_db()
    
    # Use IF NOT EXISTS for DDL
    db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL,
            balance REAL NOT NULL CHECK(balance >= 0)
        )
    """)
    
    # Check before seeding
    existing = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if existing == 0:
        db.execute("BEGIN")
        db.execute("INSERT INTO accounts (id, owner, balance) VALUES (?, ?, ?)",
                   (1, "Alice", 100.0))
        db.execute("COMMIT")
    
    return jsonify({"status": "ok"})
```

## Input Validation Pipeline

Validate in this order to provide clear error messages:

1. **JSON parsing**: `request.get_json(silent=True)` returns None on invalid JSON
2. **Required fields**: check presence of all required fields
3. **Type validation**: verify types (int, float, str, etc.)
4. **Business rule validation**: domain-specific constraints (e.g., amount > 0, same account check)
5. **Existence checks**: verify referenced resources exist
6. **State validation**: check current state allows the operation (e.g., sufficient balance)

**Python type gotcha**: In Python, `bool` is a subclass of `int`, so `isinstance(True, (int, float))` returns `True`. If the task specifies "amount must be a number" and you need to reject booleans, explicitly check: `isinstance(amount, bool) or not isinstance(amount, (int, float))`. However, if tests don't send booleans, the simpler check `not isinstance(amount, (int, float))` is sufficient.

```python
@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    from_id = data.get("from_id")
    to_id = data.get("to_id")
    amount = data.get("amount")
    
    # 1. Required fields
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    # 2. Type validation
    if not isinstance(amount, (int, float)):
        return jsonify({"error": "Amount must be a number"}), 400
    
    # 3. Business rules
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    
    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    
    # 4-6. Existence and state checks (inside transaction)
    db = get_db()
    try:
        db.execute("BEGIN")
        
        sender = db.execute("SELECT * FROM accounts WHERE id = ?", (from_id,)).fetchone()
        if sender is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Account not found"}), 404
        
        if sender["balance"] < amount:
            db.execute("ROLLBACK")
            return jsonify({"error": "Insufficient balance"}), 400
        
        # ... perform operation ...
        db.execute("COMMIT")
        return jsonify({...}), 200
        
    except Exception as e:
        db.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500
```

## Error Response Pattern

Always return JSON errors with appropriate HTTP status codes:

- **400 Bad Request**: validation failures, missing fields, invalid data
- **404 Not Found**: referenced resource doesn't exist
- **409 Conflict**: state conflicts (e.g., duplicate unique constraint)
- **500 Internal Server Error**: unexpected errors

```python
return jsonify({"error": "Error message"}), status_code
```

## Transactional State Transitions

For operations that must be atomic:

```python
try:
    db.execute("BEGIN")
    
    # Read current state
    entity = db.execute("SELECT ... WHERE id = ?", (id,)).fetchone()
    
    # Validate state
    if entity["field"] < required_value:
        db.execute("ROLLBACK")
        return jsonify({"error": "Insufficient ..."}), 400
    
    # Update state
    db.execute("UPDATE ... SET field = ? WHERE id = ?", (new_value, id))
    
    # Create related records
    db.execute("INSERT INTO ... VALUES (?, ?, ?)", (...))
    
    db.execute("COMMIT")
    return jsonify({"status": "ok"}), 200
    
except Exception as e:
    try:
        db.execute("ROLLBACK")
    except:
        pass
    return jsonify({"error": str(e)}), 500
```

## Response Construction

Return structured JSON with relevant data:

```python
return jsonify({
    "entity": {"id": entity["id"], "field": entity["field"]},
    "related": {"id": related["id"]},
    "metadata": {"count": count, "timestamp": timestamp}
}), 200
```

## Testing Pattern

Tests use Flask's test client and often verify database state directly:

```python
from solve import app

client = app.test_client()

# Setup
resp = client.get("/setup")
assert resp.status_code == 200

# Valid operation
resp = client.post("/endpoint", json={"field": "value"})
assert resp.status_code == 200
data = resp.get_json()
assert data["field"] == expected_value

# Error case
resp = client.post("/endpoint", json={})
assert resp.status_code == 400
assert "error" in resp.get_json()

# Direct database verification (common pattern)
import sqlite3
conn = sqlite3.connect("bank.db")  # opens from test's CWD
cur = conn.cursor()
cur.execute("SELECT balance FROM accounts WHERE id = 1")
assert cur.fetchone()[0] == expected_balance
conn.close()
```

**Critical**: When tests verify database state by opening the file directly, your app must use the same path. If the task says "database in current working directory" and tests do `sqlite3.connect("bank.db")`, your app must also use `DATABASE = "bank.db"` (relative path), not a `__file__`-based absolute path.

## Key Principles

1. **Atomicity**: Use transactions for multi-step operations that must succeed or fail together
2. **Idempotency**: Setup endpoints should be safe to call multiple times
3. **Consistency**: Validate state inside transactions to prevent race conditions
4. **Clear errors**: Return specific error messages with correct HTTP status codes
5. **Resource cleanup**: Always close database connections in teardown handlers
6. **Manual transaction control**: Use `isolation_level=None` with sqlite3 for explicit BEGIN/COMMIT/ROLLBACK
7. **Path alignment**: Database paths must match how tests verify state - use relative paths when task says "current working directory"
8. **Exact specification matching**: Error messages, response formats, and field names must match the task specification exactly. Tests often assert on exact strings like `"Cannot transfer to the same account"` - any deviation will fail.

## Common Pitfalls

### 1. Database Path Mismatch
**Problem**: Using `__file__`-based absolute paths when tests verify by opening the database from their CWD.

**Symptom**: Tests fail with "no such table" even though `/setup` succeeded.

**Root cause**: App creates DB at `/app/bank.db` (via `__file__`), but test opens `bank.db` from its own CWD (e.g., `/tests/bank.db`), creating a new empty file.

**Fix**: Use `DATABASE = "bank.db"` (relative path) when task says "in the current working directory."

**General principle**: When multiple consumers share a side-effect artifact, path resolution must be coordinated across all consumers, not optimized for any single one.

### 2. SQLite3 Implicit Transactions
**Problem**: Python's sqlite3 has `isolation_level=''` by default, which auto-starts transactions on DML.

**Symptom**: `sqlite3.OperationalError: cannot start a transaction within a transaction`

**Fix**: Use `isolation_level=None` for manual transaction control with explicit BEGIN/COMMIT/ROLLBACK.

### 3. Flask-SQLAlchemy Session Leaks
**Problem**: Forgetting to call `db.session.remove()` in teardown.

**Symptom**: Session pool exhaustion, stale data across requests.

**Fix**: Always add teardown handler: `db.session.remove()`

### 4. In-Memory State Persistence
**Problem**: In-memory state persists across test runs within the same process.

**Symptom**: Tests fail when run in sequence because state from previous tests leaks.

**Fix**: Implement proper reset semantics in `/setup` - either seed-if-empty or active reset depending on task requirements.

### 5. Mismatched Error Messages
**Problem**: Error messages don't match the task specification exactly.

**Symptom**: Tests fail with assertion errors on error message strings, even though the correct HTTP status code is returned.

**Root cause**: Tests often assert on exact error message strings like `assert resp.get_json()['error'] == 'Cannot transfer to the same account'`. Any deviation (extra spaces, different wording, missing punctuation) will fail.

**Fix**: Copy error messages directly from the task specification. Don't paraphrase or "improve" them.

### 6. Incorrect HTTP Status Codes
**Problem**: Returning the wrong HTTP status code for error conditions.

**Symptom**: Tests fail with status code assertions like `assert resp.status_code == 404`.

**Common mistakes**:
- Returning 400 instead of 404 for non-existent resources
- Returning 500 instead of 400 for validation errors
- Returning 200 for error conditions

**Fix**: Carefully map each error condition to the correct HTTP status code as specified in the task. Use 400 for validation/client errors, 404 for not found, 409 for conflicts, 500 for server errors.
