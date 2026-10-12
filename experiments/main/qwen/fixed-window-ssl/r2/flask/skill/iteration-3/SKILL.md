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

### CRUD Endpoints (for resource-based APIs)

Many family variants require full CRUD operations on resources (notes, tasks, catalog entities, etc.):

**GET /resources** - List all resources with optional filters
```python
@app.route('/notes', methods=['GET'])
def list_notes():
    # Query parameters for filtering
    author = request.args.get('author')
    tag = request.args.get('tag')
    
    db = get_db()
    query = "SELECT * FROM notes WHERE 1=1"
    params = []
    
    if author:
        query += " AND author = ?"
        params.append(author)
    if tag:
        query += " AND tag = ?"
        params.append(tag)
    
    notes = db.execute(query, params).fetchall()
    return jsonify([dict(n) for n in notes]), 200
```

**GET /resources/<id>** - Get single resource
```python
@app.route('/notes/<int:note_id>', methods=['GET'])
def get_note(note_id):
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not note:
        return jsonify({"error": "Note not found"}), 404
    return jsonify(dict(note)), 200
```

**POST /resources** - Create new resource
```python
@app.route('/notes', methods=['POST'])
def create_note():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # Validate required fields
    if 'title' not in data or 'content' not in data:
        return jsonify({"error": "Missing required fields"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN")
        cur = db.execute(
            "INSERT INTO notes (title, content, author) VALUES (?, ?, ?)",
            (data['title'], data['content'], data.get('author'))
        )
        note_id = cur.lastrowid
        db.execute("COMMIT")
        
        note = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return jsonify(dict(note)), 201
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise
```

**PUT /resources/<id>** - Update resource
```python
@app.route('/notes/<int:note_id>', methods=['PUT'])
def update_note(note_id):
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        # Check exists
        note = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not note:
            db.execute("ROLLBACK")
            return jsonify({"error": "Note not found"}), 404
        
        # Update fields
        title = data.get('title', note['title'])
        content = data.get('content', note['content'])
        
        db.execute(
            "UPDATE notes SET title = ?, content = ? WHERE id = ?",
            (title, content, note_id)
        )
        db.execute("COMMIT")
        
        updated = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return jsonify(dict(updated)), 200
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise
```

**DELETE /resources/<id>** - Delete resource
```python
@app.route('/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        note = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not note:
            db.execute("ROLLBACK")
            return jsonify({"error": "Note not found"}), 404
        
        db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        db.execute("COMMIT")
        
        return jsonify({"status": "deleted"}), 200
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise
```

### Mutation Endpoints (non-CRUD)

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

**Critical: Database Path Resolution**

When the task specifies "SQLite3 database in the current working directory", use a **relative path string**, not an absolute path constructed at import time:

```python
# WRONG — captures CWD at import time
DB_PATH = os.path.join(os.getcwd(), 'bank.db')

# CORRECT — resolved at each connect() call
DB_PATH = 'bank.db'
```

**Why this matters:** `sqlite3.connect()` resolves relative paths against the CWD at the moment it's called. Tests often open separate connections using relative paths like `sqlite3.connect("bank.db")`. If your app captures the absolute path at import time and the test harness changes CWD between import and test execution, the app and tests will connect to different database files, causing "no such table" errors.

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
import threading

# Module-level state with lock for thread safety
_lock = threading.Lock()
_resources = {}  # e.g., {1: {'id': 1, 'title': 'Note 1', ...}}
_next_id = 1

@app.route('/setup', methods=['GET'])
def setup():
    global _resources, _next_id
    with _lock:
        _resources = {
            1: {'id': 1, 'owner': 'Alice', 'balance': 100.0},
            2: {'id': 2, 'owner': 'Bob', 'balance': 50.0},
        }
        _next_id = 3
    return jsonify({"status": "ok"}), 200

@app.route('/resources', methods=['GET'])
def list_resources():
    with _lock:
        return jsonify(list(_resources.values())), 200

@app.route('/resources', methods=['POST'])
def create_resource():
    global _next_id
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # Phase 1: Validate
    if 'name' not in data:
        return jsonify({"error": "Missing name"}), 400
    
    # Phase 2: Mutate
    with _lock:
        resource_id = _next_id
        _next_id += 1
        resource = {'id': resource_id, 'name': data['name']}
        _resources[resource_id] = resource
    
    return jsonify(resource), 201

@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json(silent=True)
    # ... Phase 1 validation ...
    
    with _lock:
        if from_id not in _resources or to_id not in _resources:
            return jsonify({"error": "Account not found"}), 404
        if _resources[from_id]['balance'] < amount:
            return jsonify({"error": "Insufficient balance"}), 400
        
        _resources[from_id]['balance'] -= amount
        _resources[to_id]['balance'] += amount
    
    return jsonify({...}), 200
```

**Key patterns for in-memory:**
- Use `threading.Lock()` for thread safety (Flask test client is single-threaded, but good practice)
- State resets on process restart — tests typically call `/setup` before each test
- No transactions needed — mutations are atomic under the GIL for simple operations
- Use `with _lock:` to bracket all read-then-write sequences

### File Manifest / JSONL

For append-only logs or file-based state:

```python
import json
import os
import tempfile

DATA_FILE = 'data.jsonl'
MANIFEST_FILE = 'manifest.json'

def read_all_records():
    """Read all records from JSONL file."""
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def append_record(record):
    """Append a single record to JSONL file."""
    with open(DATA_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

def write_all_records(records):
    """Atomically replace all records (write to temp, then rename)."""
    dir_name = os.path.dirname(DATA_FILE) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            for record in records:
                f.write(json.dumps(record) + '\n')
        os.replace(tmp_path, DATA_FILE)  # Atomic on POSIX
    except:
        os.unlink(tmp_path)
        raise

def read_manifest():
    """Read manifest file for metadata/counters."""
    if not os.path.exists(MANIFEST_FILE):
        return {}
    with open(MANIFEST_FILE, 'r') as f:
        return json.load(f)

def write_manifest(manifest):
    """Write manifest file atomically."""
    dir_name = os.path.dirname(MANIFEST_FILE) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(manifest, f)
        os.replace(tmp_path, MANIFEST_FILE)
    except:
        os.unlink(tmp_path)
        raise

@app.route('/setup', methods=['GET'])
def setup():
    """Initialize data files with seed data."""
    if not os.path.exists(DATA_FILE):
        write_all_records([
            {'id': 1, 'owner': 'Alice', 'balance': 100.0},
            {'id': 2, 'owner': 'Bob', 'balance': 50.0},
        ])
    if not os.path.exists(MANIFEST_FILE):
        write_manifest({'next_id': 3, 'transaction_count': 0})
    return jsonify({"status": "ok"}), 200

@app.route('/resources', methods=['GET'])
def list_resources():
    records = read_all_records()
    return jsonify(records), 200

@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    if data is None or 'name' not in data:
        return jsonify({"error": "Missing name"}), 400
    
    manifest = read_manifest()
    resource_id = manifest.get('next_id', 1)
    
    records = read_all_records()
    records.append({'id': resource_id, 'name': data['name']})
    
    # Atomic write of all records + updated manifest
    write_all_records(records)
    manifest['next_id'] = resource_id + 1
    write_manifest(manifest)
    
    return jsonify({'id': resource_id, 'name': data['name']}), 201
```

**Key patterns for file-based persistence:**
- Use `tempfile.mkstemp()` + `os.replace()` for atomic writes (prevents corruption on crash)
- JSONL for append-only logs; full rewrite for mutable state
- Manifest file for metadata (counters, next IDs) separate from data
- Read-modify-write is not atomic — accept this limitation or use file locks
- Tests typically delete data files before each test case

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

### Counter and Aggregate Patterns

For resources that track counts or aggregates:

```python
# Atomic counter increment
@app.route('/tasks/<int:task_id>/upvote', methods=['POST'])
def upvote_task(task_id):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            db.execute("ROLLBACK")
            return jsonify({"error": "Task not found"}), 404
        
        # Atomic increment
        db.execute("UPDATE tasks SET votes = votes + 1 WHERE id = ?", (task_id,))
        db.execute("COMMIT")
        
        updated = db.execute("SELECT votes FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return jsonify({"votes": updated['votes']}), 200
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise

# Aggregate query (sum, count, avg)
@app.route('/accounts/total', methods=['GET'])
def total_balance():
    db = get_db()
    result = db.execute("SELECT SUM(balance) as total FROM accounts").fetchone()
    return jsonify({"total": result['total'] or 0.0}), 200
```

### Uniqueness Constraint Handling

For resources with unique fields (email, username, URL slug, etc.):

```python
# SQLite: Use UNIQUE constraint + catch IntegrityError
# Table definition:
# CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, ...)

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json(silent=True)
    if not data or 'email' not in data:
        return jsonify({"error": "Missing email"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        # Check uniqueness before insert (Phase 2 check inside transaction)
        existing = db.execute("SELECT id FROM users WHERE email = ?", (data['email'],)).fetchone()
        if existing:
            db.execute("ROLLBACK")
            return jsonify({"error": "Email already registered"}), 409
        
        cur = db.execute("INSERT INTO users (email, name) VALUES (?, ?)",
                        (data['email'], data.get('name')))
        user_id = cur.lastrowid
        db.execute("COMMIT")
        
        return jsonify({"id": user_id, "email": data['email']}), 201
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise

# Alternative: Let the database enforce it and catch the error
import sqlite3
try:
    db.execute("INSERT INTO users (email) VALUES (?)", (email,))
    db.execute("COMMIT")
except sqlite3.IntegrityError:
    db.execute("ROLLBACK")
    return jsonify({"error": "Email already registered"}), 409
```

### Cascading Validation

For operations that depend on multiple resources:

```python
# Example: Checkout requires cart items AND sufficient inventory
@app.route('/checkout', methods=['POST'])
def checkout():
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        
        # Get cart items
        items = db.execute("SELECT * FROM cart_items WHERE user_id = ?", (user_id,)).fetchall()
        if not items:
            db.execute("ROLLBACK")
            return jsonify({"error": "Cart is empty"}), 400
        
        # Check inventory for ALL items before any mutations
        for item in items:
            product = db.execute("SELECT * FROM products WHERE id = ?", (item['product_id'],)).fetchone()
            if not product:
                db.execute("ROLLBACK")
                return jsonify({"error": f"Product {item['product_id']} not found"}), 404
            if product['stock'] < item['quantity']:
                db.execute("ROLLBACK")
                return jsonify({"error": f"Insufficient stock for {product['name']}"}), 400
        
        # All validations passed - now mutate
        for item in items:
            db.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                      (item['quantity'], item['product_id']))
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        db.execute("COMMIT")
        
        return jsonify({"status": "checked out"}), 200
    except Exception:
        try:
            db.execute("ROLLBACK")
        except:
            pass
        raise
```

**Key principle:** Validate ALL resources before ANY mutations. This prevents partial updates when later checks fail.

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

### Test Harness Interaction Patterns

**Critical:** Tests may verify state by opening **separate database connections** outside the Flask app:

```python
# Test pattern that caused iteration 1 failure:
def test_setup_idempotent():
    client = app.test_client()
    resp1 = client.get('/setup')
    resp2 = client.get('/setup')
    
    # Test opens SEPARATE connection to verify state
    conn = sqlite3.connect("bank.db")  # Relative path!
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM accounts")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 2
```

**Why this matters:**
- Tests use relative paths like `sqlite3.connect("bank.db")` that resolve at connection time
- Your app must also use relative paths (not `os.path.join(os.getcwd(), ...)` at import time)
- Both app and tests must see the same database file
- This is why `DB_PATH = 'bank.db'` is correct, not `DB_PATH = os.path.join(os.getcwd(), 'bank.db')`

**For file-based persistence:**
- Tests may read data files directly to verify state
- Use relative paths for data files: `DATA_FILE = 'data.jsonl'`
- Ensure files are flushed/closed after writes so tests can read them

**For in-memory persistence:**
- Tests cannot verify state directly (no external file/connection)
- Tests must verify state through API endpoints
- State resets on process restart — tests call `/setup` before each test

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
11. **SQLite path resolution**: Using `os.path.join(os.getcwd(), 'db.sqlite')` captures CWD at import time. Tests open separate connections with relative paths. Fix: use `DB_PATH = 'db.sqlite'` (relative path resolved at connect time)
12. **Partial updates on cascading validation**: Mutating some resources before discovering a later validation failure. Fix: validate ALL resources before ANY mutations
13. **Non-atomic file writes**: Writing directly to data files without temp+rename causes corruption on crash. Fix: use `tempfile.mkstemp()` + `os.replace()`
14. **Missing thread safety for in-memory state**: Not using locks for read-then-write sequences. Fix: use `threading.Lock()` to bracket all mutations
15. **Forgetting to flush/close files**: Tests read files before data is flushed. Fix: use `with open()` context managers or explicit `f.flush()` + `os.fsync()`

## Decision Framework

When building a Flask stateful service:

### 1. Identify the Service Shape

Read the task specification carefully to determine:
- **Resource model**: What entities are being managed? (accounts, notes, tasks, products, etc.)
- **Endpoint pattern**: CRUD operations, atomic transfers, checkout flows, or custom operations?
- **Persistence model**: sqlite3, flask_sqlalchemy, in_memory, file_manifest, or jsonl?
- **State transitions**: Atomic updates, counters, aggregates, cascading validation?

### 2. Choose Persistence Model

Based on task requirements:
- **sqlite3**: Full control, explicit transactions, good for complex queries, atomic operations
- **flask_sqlalchemy**: ORM convenience, automatic transaction management, relationships
- **in_memory**: Simple, fast, no persistence across restarts, good for demos/tests
- **file_manifest/jsonl**: Append-only logs, audit trails, simple file-based state

### 3. Design Endpoints

Based on the resource model:
- **Setup endpoint**: Idempotent, creates initial state (always needed)
- **CRUD endpoints**: GET list, GET single, POST create, PUT update, DELETE (for resource-based APIs)
- **Mutation endpoints**: POST for atomic operations (transfers, checkouts, votes, etc.)
- **Query endpoints**: GET with query parameters for filtering/searching

### 4. Implement Validation

Follow the two-phase pattern:
- **Phase 1** (no DB): Check JSON parsing, required fields, types, ranges, business rules
- **Phase 2** (inside transaction): Check existence, constraints, then mutate

Type validation checklist:
- Exclude bools from int checks: `isinstance(x, bool) or not isinstance(x, int)`
- Check for None before type checks
- Validate ranges (positive, non-negative, within bounds)
- Check business rules (same account, uniqueness, etc.)

### 5. Ensure Atomicity

Based on persistence model:
- **SQLite**: `isolation_level=None` + `BEGIN IMMEDIATE` for read-then-write
- **SQLAlchemy**: Rely on session management, explicit rollback on errors
- **In-memory**: Use `threading.Lock()` to bracket read-then-write sequences
- **File-based**: Accept non-atomic read-modify-write or use file locks

### 6. Handle Errors Consistently

- Return JSON error responses: `{"error": "descriptive message"}`
- Use appropriate HTTP status codes: 400 (validation), 404 (not found), 409 (conflict), 500 (server error)
- Always rollback transactions on error paths
- Never leak internal error details to clients

### 7. Test Thoroughly

- Happy path: successful operations return correct responses
- Error conditions: all validation errors return correct status codes and messages
- Idempotency: calling setup multiple times doesn't duplicate data
- State consistency: multiple operations maintain invariants (e.g., total balance conserved)
- External verification: tests may open separate connections to verify state

### 8. Common Patterns by Resource Type

**Accounts/Transfers**: Atomic transfers, balance checks, transaction logging
**Notes/Tasks**: Full CRUD, filtering by author/tag/status, counters (votes, comments)
**Catalog/Products**: Uniqueness constraints (SKU, slug), inventory management, search
**Cart/Checkout**: Cascading validation (cart items + inventory), atomic checkout
**URL Mappings**: Uniqueness (short URL), redirect handling, click counters
**Logs/Events**: Append-only, query by time range, aggregation (count, sum)
