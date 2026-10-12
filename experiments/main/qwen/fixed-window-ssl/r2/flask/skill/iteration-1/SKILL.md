---
name: flask
description: >
  Build Flask-based JSON HTTP services with mutable domain state, multiple
  coupled endpoints, validation, atomic state transitions, and proper error
  handling. Covers persistence via sqlite3, flask_sqlalchemy, in-memory dicts,
  file manifests, and JSONL. Emphasizes transaction semantics, idempotent setup,
  and test-client evaluation.
---

# Flask Stateful JSON Service

## Family Scope

This skill covers Flask applications that:
- Expose multiple behaviorally coupled endpoints managing shared mutable state
- Accept and return JSON (not HTML/templates)
- Require validation, error handling, and state consistency
- Are evaluated via `app.test_client()` (no live server needed)

**Out of scope:** single-route stateless wrappers, authentication-only snippets, template rendering, pure numerical APIs.

## Core Architecture Pattern

```python
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# Per-request resource management via Flask's `g` object
def get_resource():
    if 'resource' not in g:
        g.resource = initialize_resource()
    return g.resource

@app.teardown_appcontext
def close_resource(exception):
    resource = g.pop('resource', None)
    if resource is not None:
        resource.close()
```

## Endpoint Design

### Setup/Lifecycle Endpoint

- **Idempotent**: Safe to call multiple times without side effects
- Use `CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`, or existence checks
- Return 200 with status confirmation

### Mutation Endpoints

- Validate all inputs before any state changes
- Return appropriate HTTP status codes:
  - 400: validation errors (missing fields, invalid values, constraint violations)
  - 404: resource not found
  - 409: conflict (duplicate, already exists)
  - 500: unexpected errors
- Return JSON error responses: `{"error": "descriptive message"}`

### Validation Ordering: Cheap First, Transaction Late

**Critical principle:** Validate everything you can without the database first, then open the transaction for what requires the database.

**Phase 1 — No transaction, no database access:**
1. Parse JSON (`get_json(silent=True)`)
2. Check required field presence
3. Check types (integers are integers, not strings or bools)
4. Check ranges and constraints (amount > 0, etc.)
5. Check identity rules (from_id != to_id, etc.)

**Phase 2 — Inside transaction (BEGIN IMMEDIATE ... COMMIT):**
6. Check existence (resources exist? → 404)
7. Check business constraints (sufficient balance? → 400)
8. Mutate state (UPDATE, INSERT)

**Why this ordering matters:**
- Phase 1 checks are O(1) Python operations. If they fail, you return immediately — no transaction to start, no ROLLBACK needed, no database lock held.
- Phase 2 checks require reading database state. They must be inside the transaction to be consistent.
- Starting `BEGIN IMMEDIATE` late minimizes lock hold time and simplifies error paths (fewer ROLLBACK branches).

**Type validation pattern (Python-specific):**
```python
# bool is a subclass of int in Python — exclude it explicitly
if isinstance(from_id, bool) or not isinstance(from_id, int):
    return jsonify({"error": "from_id must be an integer"}), 400

if not isinstance(amount, (int, float)) or isinstance(amount, bool):
    return jsonify({"error": "Amount must be a number"}), 400
```

Without bool exclusion, `isinstance(True, int)` returns `True`, allowing boolean values where integers are expected.

## Persistence Models

### SQLite3 (Raw)

**Critical: Transaction Control**

Python's `sqlite3` module defaults to `isolation_level=""` (DEFERRED), which starts implicit transactions on the first write but leaves SELECTs outside transactions. This creates TOCTOU races in read-then-write patterns.

**Solution: Use `isolation_level=None` (autocommit) with explicit transaction management:**

```python
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.route('/setup', methods=['GET'])
def setup():
    db = get_db()
    try:
        db.execute("BEGIN")  # Explicit transaction for multi-statement setup
        db.execute("CREATE TABLE IF NOT EXISTS ...")
        db.execute("INSERT OR IGNORE INTO ...")
        db.execute("COMMIT")
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise
    return jsonify({"status": "ok"}), 200

@app.route('/transfer', methods=['POST'])
def transfer():
    # ... validation ...
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")  # Acquires RESERVED lock before reads
        
        # Read-then-write is now atomic
        sender = db.execute("SELECT ... WHERE id=?", (id,)).fetchone()
        if not sender:
            db.execute("ROLLBACK")
            return jsonify({"error": "Not found"}), 404
        
        if sender['balance'] < amount:
            db.execute("ROLLBACK")
            return jsonify({"error": "Insufficient"}), 400
        
        db.execute("UPDATE ... SET balance = balance - ? WHERE id=?", (amount, id))
        cur = db.execute("INSERT INTO ...", (...))
        transaction_id = cur.lastrowid  # Capture before COMMIT
        
        db.execute("COMMIT")
        return jsonify({...}), 200
        
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

**Key principles:**
1. `isolation_level=None` — full manual control, no implicit transactions
2. `BEGIN IMMEDIATE` for read-then-write operations — closes TOCTOU window
3. `BEGIN` (DEFERRED) for pure setup/initialization
4. Always `ROLLBACK` on every error path — prevents dirty state on recycled connections
5. Capture `lastrowid` immediately after INSERT, before COMMIT

### Flask-SQLAlchemy

```python
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    balance = db.Column(db.Float, nullable=False)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()  # Not .close() — remove() returns the session to the pool

@app.route('/transfer', methods=['POST'])
def transfer():
    try:
        # SQLAlchemy manages transactions automatically
        sender = Account.query.get(from_id)
        if not sender:
            return jsonify({"error": "Not found"}), 404
        
        sender.balance -= amount
        receiver.balance += amount
        db.session.commit()
        return jsonify({...}), 200
    except IntegrityError:
        db.session.rollback()  # Mandatory after IntegrityError
        return jsonify({"error": "Constraint violation"}), 409
    except Exception:
        db.session.rollback()
        raise
```

**Key differences from raw sqlite3:**
- Teardown uses `db.session.remove()` (returns session to pool), not `.close()`
- `commit()` can raise `IntegrityError` on constraint violations — always rollback after
- Session management handles most transaction lifecycle automatically

### In-Memory (Process-Local Dicts)

```python
# Module-level state
accounts = {}

@app.route('/setup', methods=['GET'])
def setup():
    global accounts
    accounts = {1: {'owner': 'Alice', 'balance': 100.0}}
    return jsonify({"status": "ok"}), 200

@app.route('/transfer', methods=['POST'])
def transfer():
    # No transaction needed — single-threaded test client
    # But still validate before mutating
    if accounts[from_id]['balance'] < amount:
        return jsonify({"error": "Insufficient"}), 400
    
    accounts[from_id]['balance'] -= amount
    accounts[to_id]['balance'] += amount
    return jsonify({...}), 200
```

**Note:** In-memory state is lost on process restart. Tests typically call `/setup` before each test case.

### File Manifest / JSONL

```python
import json
import os

DATA_FILE = 'data.jsonl'

def append_record(record):
    with open(DATA_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

def read_all_records():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r') as f:
        return [json.loads(line) for line in f]
```

**Note:** File-based persistence requires careful handling of concurrent writes (use file locks if needed) and atomic writes (write to temp file, then rename).

## Validation Patterns

### Required Field Validation

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid JSON"}), 400

required = ['field1', 'field2']
missing = [f for f in required if f not in data]
if missing:
    return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
```

### Type and Range Validation

```python
amount = data.get('amount')

# Type checks — exclude bools (bool is subclass of int in Python)
if isinstance(amount, bool) or not isinstance(amount, (int, float)):
    return jsonify({"error": "Amount must be a number"}), 400

# Range checks
if amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400

# Integer ID checks
if isinstance(from_id, bool) or not isinstance(from_id, int):
    return jsonify({"error": "from_id must be an integer"}), 400
```

### Business Rule Validation

```python
if from_id == to_id:
    return jsonify({"error": "Cannot transfer to same account"}), 400

if sender['balance'] < amount:
    return jsonify({"error": "Insufficient balance"}), 400
```

## State Transition Patterns

### Atomic Updates (SQLite)

Use SQL arithmetic to avoid read-then-write races:

```python
# Instead of:
balance = db.execute("SELECT balance FROM accounts WHERE id=?", (id,)).fetchone()[0]
new_balance = balance - amount
db.execute("UPDATE accounts SET balance=? WHERE id=?", (new_balance, id))

# Use:
db.execute("UPDATE accounts SET balance = balance - ? WHERE id=?", (amount, id))
```

### Idempotent Operations

```python
# Setup
db.execute("CREATE TABLE IF NOT EXISTS ...")
db.execute("INSERT OR IGNORE INTO ...")

# Updates with conditions
db.execute("UPDATE ... SET status='completed' WHERE id=? AND status='pending'", (id,))
if db.execute("SELECT changes()").fetchone()[0] == 0:
    return jsonify({"error": "Already completed or not found"}), 409
```

## Testing Patterns

### Test Client Usage

```python
import pytest
from solve import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        # Reset state before each test
        client.get('/setup')
        yield client

def test_transfer(client):
    resp = client.post('/transfer', json={
        'from_id': 1,
        'to_id': 2,
        'amount': 25.0
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['sender']['balance'] == 75.0
```

### State Consistency Checks

```python
def test_atomicity(client):
    # Perform multiple operations
    client.post('/transfer', json={'from_id': 1, 'to_id': 2, 'amount': 30.0})
    client.post('/transfer', json={'from_id': 2, 'to_id': 1, 'amount': 20.0})
    
    # Verify final state is consistent
    resp = client.get('/accounts')
    data = resp.get_json()
    # Total money should be conserved
    total = sum(acc['balance'] for acc in data['accounts'])
    assert total == 150.0  # Initial total
```

## Common Pitfalls

1. **TOCTOU races in SQLite**: Using default `isolation_level` with read-then-write patterns. Fix: `isolation_level=None` + `BEGIN IMMEDIATE`
2. **Missing ROLLBACK**: Forgetting to rollback on error paths leaves connections in dirty state
3. **Non-idempotent setup**: Using `INSERT` instead of `INSERT OR IGNORE` causes duplicates
4. **Floating-point arithmetic**: Using Python floats for money; prefer SQL arithmetic or Decimal
5. **Missing validation**: Mutating state before validating inputs
6. **Inconsistent error responses**: Mixing string errors with dict errors; always use `{"error": "..."}`
7. **Validation ordering**: Starting transactions before cheap Python-only checks. Fix: Phase 1 (no DB) then Phase 2 (inside transaction)
8. **Bool-is-int trap**: `isinstance(True, int)` returns `True` in Python. Always exclude bools when validating integer fields
9. **SQLAlchemy teardown**: Using `.close()` instead of `.remove()` on sessions. Fix: `db.session.remove()`
10. **SQLAlchemy IntegrityError**: Forgetting to rollback after constraint violations. Fix: explicit rollback in except block

## Decision Framework

When building a Flask stateful service:

1. **Choose persistence model** based on task requirements:
   - sqlite3: Full control, explicit transactions, good for complex queries
   - flask_sqlalchemy: ORM convenience, automatic transaction management
   - in_memory: Simple, fast, but no persistence across restarts
   - file_manifest/jsonl: Append-only logs, good for audit trails

2. **Design endpoints**:
   - Setup endpoint: Idempotent, creates initial state
   - Query endpoints: GET, return current state
   - Mutation endpoints: POST/PUT/PATCH, validate then mutate atomically

3. **Implement validation**:
   - Check JSON parsing
   - Validate required fields
   - Validate types and ranges
   - Check business rules
   - Return appropriate HTTP status codes

4. **Ensure atomicity**:
   - SQLite: `BEGIN IMMEDIATE` for read-then-write
   - SQLAlchemy: Rely on session management, explicit rollback on errors
   - In-memory: Single-threaded, no explicit transactions needed

5. **Test thoroughly**:
   - Happy path
   - All error conditions
   - Idempotency
   - State consistency across multiple operations
