---
name: flask
description: >
  Build stateful Flask JSON HTTP services with mutable domain state, multiple
  coupled endpoints, atomic state transitions, input validation, and proper
  error handling. Covers persistence via sqlite3, Flask-SQLAlchemy, in-memory
  dicts, file manifests, or JSONL. Evaluated through Flask's test client.
---

# Flask Stateful Service Skill

## Family Definition

Every case in this family is a **stateful JSON HTTP service** built with Flask where:
- Requests share and mutate domain state (not stateless wrappers)
- Multiple endpoints are behaviorally coupled through that state
- The app object is named `app` and evaluated via `app.test_client()`
- All responses are JSON (no template rendering)

## Core Architecture Pattern

```python
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# Request-scoped resource management via g + teardown
def get_resource():
    if 'resource' not in g:
        g.resource = initialize_resource()
    return g.resource

@app.teardown_appcontext
def close_resource(exception):
    resource = g.pop('resource', None)
    if resource is not None:
        resource.close()

# Lifecycle/setup endpoint
@app.route('/setup', methods=['GET'])
def setup():
    # Idempotent initialization
    ...

# Domain endpoints
@app.route('/resource', methods=['POST'])
def create_resource():
    # Validate → mutate atomically → respond
    ...
```

## Critical Invariants

### 1. Single Transaction Control Layer

**Principle**: When a persistence layer has both a framework-level transaction abstraction AND raw SQL/operation-level transaction control, pick one and disable the other. Mixing them creates invisible state divergence that only manifests in error recovery paths.

#### For raw sqlite3:
```python
# CORRECT: Disable implicit transactions, use explicit control
db = sqlite3.connect(path, isolation_level=None)
# Now you write BEGIN/COMMIT/ROLLBACK explicitly — no hidden layer

# WRONG: Default isolation_level="" with explicit BEGIN
# Python's implicit transaction management and your explicit calls
# can diverge in error paths
db = sqlite3.connect(path)  # isolation_level="" by default
db.execute("BEGIN")  # Works in happy path, fragile in error paths
```

#### For Flask-SQLAlchemy:
```python
# CORRECT: Use session exclusively
db.session.add(obj)
db.session.commit()
# Or for rollback:
db.session.rollback()

# WRONG: Mixing session with raw SQL transaction commands
db.session.execute(text("BEGIN"))  # Conflicts with session state
```

#### For in-memory/file persistence:
```python
# Atomicity via copy-on-write or write-to-temp-then-rename
import shutil, tempfile
tmp = tempfile.NamedTemporaryFile(dir=DATA_DIR, delete=False)
# Write complete new state to tmp
# Then atomic rename
os.replace(tmp.name, DATA_FILE)
```

### 2. Idempotent Setup

Setup endpoints must be safely callable multiple times:
```python
# SQL: Use IF NOT EXISTS for tables
db.execute("CREATE TABLE IF NOT EXISTS ...")

# Check before seeding
count = db.execute("SELECT COUNT(*) FROM table").fetchone()[0]
if count == 0:
    db.execute("BEGIN")
    # Insert seed data
    db.execute("COMMIT")

# In-memory: Check if already initialized
if not state['initialized']:
    state['initialized'] = True
    # Seed data
```

### 3. Validate Before Mutate

All validation must happen **before** any state-changing operation:
```python
@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # 1. Extract and validate ALL inputs first
    field_a = data.get('field_a')
    if field_a is None:
        return jsonify({"error": "Missing field_a"}), 400
    
    # 2. Business rule validation
    if field_a <= 0:
        return jsonify({"error": "Must be positive"}), 400
    
    # 3. Only NOW begin the transaction and mutate
    db = get_db()
    try:
        db.execute("BEGIN")
        # ... mutations ...
        db.execute("COMMIT")
        return jsonify({...}), 200
    except Exception:
        db.execute("ROLLBACK")
        raise
```

### 4. Atomic Multi-Step Mutations

When an operation requires multiple state changes, they must all succeed or all fail.
Discriminate exception types to map constraint violations to the contract's expected
error responses — never leak raw database errors as 500:

```python
try:
    db.execute("BEGIN")
    
    # Step 1: Read current state (within transaction for consistency)
    sender = db.execute("SELECT balance FROM accounts WHERE id = ?", (from_id,)).fetchone()
    if sender is None:
        db.execute("ROLLBACK")
        return jsonify({"error": "Not found"}), 404
    
    # Step 2: Validate against current state
    if sender['balance'] < amount:
        db.execute("ROLLBACK")
        return jsonify({"error": "Insufficient"}), 400
    
    # Step 3: All mutations
    db.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_id))
    db.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))
    db.execute("INSERT INTO transactions ...")
    
    db.execute("COMMIT")
    return jsonify({...}), 200

except sqlite3.IntegrityError as e:
    # CHECK or UNIQUE constraint violated — map to expected contract response.
    # This is the safety net: even if pre-validation missed something (race condition,
    # floating-point edge case), the DB constraint catches it and we return the
    # correct status code, not a raw 500.
    try:
        db.execute("ROLLBACK")
    except Exception:
        pass
    error_msg = str(e).lower()
    if "balance" in error_msg or "check" in error_msg:
        return jsonify({"error": "Insufficient balance"}), 400
    elif "unique" in error_msg:
        return jsonify({"error": "Already exists"}), 409
    else:
        return jsonify({"error": "Constraint violation"}), 400

except sqlite3.OperationalError as e:
    try:
        db.execute("ROLLBACK")
    except Exception:
        pass
    if "locked" in str(e).lower():
        return jsonify({"error": "Database busy, try again"}), 503
    return jsonify({"error": "Database error"}), 500

except Exception as e:
    try:
        db.execute("ROLLBACK")
    except Exception:
        pass
    return jsonify({"error": "Internal server error"}), 500
```

**Key principle**: CHECK/UNIQUE/NOT NULL constraints are runtime safety nets, not
just schema documentation. Catch the specific exception type they raise and map it
to the contract's expected error response. This applies across all persistence models:
- `sqlite3` → `sqlite3.IntegrityError`
- `Flask-SQLAlchemy` → `sqlalchemy.exc.IntegrityError`
- `in_memory` → your own validation (no DB to catch what you miss)

### 5. Error Response Contract

| Condition | Status | Response |
|-----------|--------|----------|
| Missing/invalid fields | 400 | `{"error": "..."}` |
| Business rule violation | 400 | `{"error": "..."}` (exact message per spec) |
| Resource not found | 404 | `{"error": "..."}` |
| Conflict/duplicate | 409 | `{"error": "..."}` |
| Server error | 500 | `{"error": "..."}` |

Always return JSON error bodies. Never return HTML error pages.

### 6. Request-Scoped Resource Lifecycle

```python
# Use Flask's g for per-request resources
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row  # Dict-like row access
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

## Persistence-Specific Patterns

### sqlite3 (raw)
- Use `isolation_level=None` for explicit transaction control
- Use `row_factory = sqlite3.Row` for column-name access
- Parameterize all queries with `?` placeholders (never string interpolation)
- Use `PRAGMA journal_mode=WAL` for better concurrent read performance

### Flask-SQLAlchemy
- Define models with `db.Model`
- Use `db.session` for all mutations
- `db.session.commit()` / `db.session.rollback()` for transaction control
- Use `db.create_all()` for setup (idempotent by default)

### In-Memory (dicts)
- Store state in module-level or app.config dict
- Deep-copy on read if mutation safety needed
- No persistence across process restarts (by design)

### File Manifest
- Store data as JSON file + manifest for metadata
- Use atomic file replacement (write temp → os.replace)
- Lock file or atomic rename for concurrent safety

### JSONL
- Append-only log of operations
- Rebuild state by replaying log on startup
- Truncate/compact periodically

## Verification Checklist

Before considering a solution complete, verify:

1. **Happy path**: All endpoints return correct status codes and response bodies
2. **Idempotency**: Calling setup multiple times produces same state as calling once
3. **Validation errors**: Every invalid input returns correct status + error message
4. **Not found**: Referencing nonexistent resources returns 404
5. **Atomicity**: A failed mutation leaves state completely unchanged
   - Test: record state → trigger failure → verify state identical
6. **Transaction isolation**: Concurrent requests don't corrupt state
7. **Response schema**: All fields present with correct types and names

## Common Pitfalls

1. **Forgetting `isolation_level=None`** with raw sqlite3 → implicit/explicit transaction conflict
2. **Returning before ROLLBACK** in error paths → partial state committed
3. **Not checking existence before mutation** → confusing IntegrityError instead of clean 404
4. **Not catching IntegrityError and mapping it to the expected 400/409 response** → raw database error leaked as 500
5. **Using `request.json` instead of `request.get_json(silent=True)`** → 400 on malformed JSON instead of controlled error
6. **Forgetting `row_factory`** → accessing rows by index instead of column name
7. **Non-idempotent setup** → duplicate seed data on repeated calls
8. **Mutating state before validation** → partial corruption on error
