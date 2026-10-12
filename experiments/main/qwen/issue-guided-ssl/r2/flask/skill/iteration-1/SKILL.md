---
name: flask
description: >
  Build stateful JSON HTTP services with Flask. Covers SQLite3 persistence with
  correct transaction semantics (isolation_level=None, BEGIN IMMEDIATE), idempotent
  setup endpoints, atomic read-check-write operations, validation ordering, and
  structured error contracts. Generalizes to any resource model (accounts, tasks,
  notes, catalogs, carts, URL mappings, logs) with mutable shared state.
---

# Flask Stateful JSON HTTP Service

## Family Invariants

Every case in this family implements a JSON HTTP service where:
- Requests share mutable domain state (not stateless)
- Multiple behaviorally coupled endpoints, or a middleware + lifecycle endpoint
- State is persisted (SQLite3, Flask-SQLAlchemy, in-memory dicts, file manifest, or JSONL)
- The Flask app object is named `app` and evaluated via `app.test_client()`
- All responses are JSON with appropriate HTTP status codes

## Architecture Template

### File Structure
```
/app/solve.py   # Flask app with `app` object, all routes, persistence logic
```

### Application Skeleton
```python
import sqlite3  # or sqlalchemy, or dict-based storage
import os
from flask import Flask, request, jsonify, g

app = Flask(__name__)

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
```

## SQLite3 Persistence (persistence_model: sqlite3)

### Critical: Transaction Semantics

Python's `sqlite3` module has a default `isolation_level=""` (DEFERRED) that **auto-issues BEGIN before DML** (INSERT/UPDATE/DELETE) but **NOT before SELECT**. This means a SELECT-then-UPDATE sequence is NOT atomic by default — the read happens outside any transaction.

**The fix**: Always use `isolation_level=None` (manual/autocommit mode) and manage transactions explicitly:

```python
g.db = sqlite3.connect(db_path, isolation_level=None)
```

### Atomic Operation Template (BEGIN IMMEDIATE)

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
        updated = db.execute("SELECT ... WHERE ...", (...)).fetchone()
        
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

### Idempotent Setup Endpoint

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

### Database Path

Compute the path at request time inside `get_db()`, not at module import time, because tests may change the working directory:

```python
def get_db():
    if 'db' not in g:
        db_path = os.path.join(os.getcwd(), 'bank.db')  # computed per-request
        g.db = sqlite3.connect(db_path, isolation_level=None)
        ...
```

## Validation Ordering Pattern

Always validate in this order to produce the correct error for the first failing constraint:

1. **Parse request** — extract JSON body, handle missing/malformed body
2. **Missing required fields** — check all required keys exist and are not None
3. **Logical constraints** — type checks, range checks, cross-field rules (no DB needed)
4. **Existence checks** — verify referenced resources exist (requires DB, inside transaction)
5. **State-dependent checks** — balance sufficient, status allows operation, etc. (inside transaction)

This ordering ensures the most specific, actionable error is returned first.

## Error Contract Pattern

Every error returns JSON with an `"error"` key and the appropriate HTTP status:

| Condition | Status | Response |
|-----------|--------|----------|
| Missing fields | 400 | `{"error": "Missing required fields: ..."}` |
| Invalid values | 400 | `{"error": "Amount must be positive"}` |
| Logical violation | 400 | `{"error": "Cannot transfer to the same account"}` |
| Resource not found | 404 | `{"error": "Account not found"}` |
| Insufficient state | 400 | `{"error": "Insufficient balance"}` |
| Server error | 500 | `{"error": "..."}` |

**Key invariant**: On any error path inside a transaction, always ROLLBACK before returning, so persistent state remains consistent.

## Adaptation to Different Persistence Models

### In-Memory (dict-based)
```python
# Module-level state
state = {"resources": {}, "counter": 0}

# No transaction management needed (single-threaded test client)
# But still validate in the same order
```

### Flask-SQLAlchemy
```python
from flask_sqlalchemy import SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db = SQLAlchemy(app)

# Use db.session for transactions
# db.session.begin() for explicit transaction control
# db.session.rollback() on error
```

### File Manifest / JSONL
```python
# Read-modify-write with file locking
# Use fcntl.flock or a lock file for atomicity
```

## Adaptation to Different Resource Models

The pattern is the same regardless of what's being managed:

1. **Define schema** — tables/collections with fields, constraints, and relationships
2. **Setup endpoint** — create schema + seed data idempotently
3. **Mutation endpoints** — validate → lock → check → mutate → commit → respond
4. **Query endpoints** — read state with optional filters

The resource model (accounts, tasks, notes, carts, URLs, logs) only changes:
- Table schemas and field names
- Validation rules and error messages
- Response shapes
- Business logic in the mutation step

## Checklist for New Cases

- [ ] `app` Flask object exported from `/app/solve.py`
- [ ] `isolation_level=None` on all SQLite3 connections
- [ ] `BEGIN IMMEDIATE` for all read-check-write operations
- [ ] ROLLBACK on every error path inside a transaction
- [ ] Setup endpoint is idempotent (IF NOT EXISTS + INSERT OR IGNORE)
- [ ] Validation ordering: missing → logical → existence → state-dependent
- [ ] All errors return JSON `{"error": "..."}` with correct HTTP status
- [ ] Database path computed at request time (inside `get_db()`)
- [ ] Response includes all fields specified by the case
- [ ] State remains consistent after any error (no partial mutations)
