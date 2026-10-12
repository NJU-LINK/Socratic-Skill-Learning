---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  across multiple coupled endpoints. Covers persistence backends (sqlite3,
  flask_sqlalchemy, in_memory, file_manifest, jsonl), atomic state transitions,
  input validation, idempotent setup, and structured JSON error responses.
  The app is always exported as `app` from `/app/solve.py` and tested via
  Flask's test client.
---

# Flask Stateful JSON Service

## Core Architecture

Every task in this family requires `/app/solve.py` exporting a Flask application
object named `app`. Tests import it and use `app.test_client()`. The service
manages mutable domain state through multiple behaviorally coupled endpoints.

### Mandatory Structure

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# ... persistence setup, routes, helpers ...

if __name__ == '__main__':
    app.run(debug=True)
```

## Methodology: Reading the Task Spec

Extract these dimensions from every task description:

1. **Resource model**: What entities exist? What are their fields, types, and constraints?
2. **Persistence model**: Which storage backend? (sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl)
3. **Endpoint contracts**: Exact route paths, HTTP methods, request bodies, query params, response schemas, status codes.
4. **State transitions**: What mutations occur? What atomicity guarantees are needed?
5. **Validation rules**: What inputs are invalid? What error messages and status codes for each?
6. **Setup/lifecycle**: Is there a setup endpoint? Must it be idempotent? What seed data?

## Persistence Patterns

### sqlite3 (raw SQLite)

```python
import sqlite3
import os
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DB_PATH = os.path.join(os.getcwd(), 'service.db')  # or task-specified path

def get_db():
    """Per-request database connection stored in Flask g."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row  # dict-like access
        g.db.execute('PRAGMA journal_mode=WAL')  # better concurrency
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Key patterns:**
- Use `CREATE TABLE IF NOT EXISTS` for idempotent setup
- Manual transaction control: `db.execute('BEGIN')` / `COMMIT` / `ROLLBACK`
- Always ROLLBACK on error paths before returning error responses
- Use parameterized queries (`?`) to prevent SQL injection
- `row_factory = sqlite3.Row` for dict-like column access

**Atomic state mutation pattern — two error-handling zones:**

There are two distinct zones of validation, and they require different error-handling strategies:

- **Pre-transaction zone** (before `BEGIN`): Pure input validation — missing fields, wrong types, out-of-range values. These return JSON errors directly. No transaction is open, so no rollback is needed.
- **In-transaction zone** (after `BEGIN`): Lookups and state-dependent checks — resource existence, business-rule invariants. These must `ROLLBACK` first, then `return jsonify(...), status`. They must NOT `raise`, because `raise` would propagate to Flask's default handler, producing a generic 500 HTML error page instead of the required JSON error response.
- **except block**: Only catches truly unexpected errors (e.g., database corruption). Rolls back and returns a 500 JSON error.

```python
db = get_db()
try:
    db.execute('BEGIN')

    # In-transaction lookups and state checks:
    # Each failure path must ROLLBACK then RETURN a JSON error.
    resource = db.execute('SELECT * FROM ... WHERE id = ?', (id,)).fetchone()
    if resource is None:
        db.execute('ROLLBACK')
        return jsonify({"error": "Resource not found"}), 404

    if resource['balance'] < amount:
        db.execute('ROLLBACK')
        return jsonify({"error": "Insufficient balance"}), 400

    # ... multiple related writes ...
    db.execute('COMMIT')
    return jsonify({...}), 200

except Exception as e:
    # Only truly unexpected errors reach here (e.g., DB corruption).
    # Roll back and return a JSON 500 — never `raise`.
    db.execute('ROLLBACK')
    return jsonify({"error": f"Internal error: {str(e)}"}), 500
```

### flask_sqlalchemy (ORM)

```python
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///service.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)
```

**Key patterns:**
- `db.create_all()` for setup (idempotent by nature)
- `db.session.add()`, `db.session.commit()`, `db.session.rollback()`
- Query with `Model.query.filter_by(...)` or `db.session.execute(db.select(Model).where(...))`
- Seed data: check if records exist before inserting

### in_memory (process-local dicts/lists)

```python
# Module-level state
state = {
    'accounts': {},  # id -> account dict
    'next_id': 1,
}

def reset_state():
    state['accounts'] = {}
    state['next_id'] = 1
```

**Key patterns:**
- No persistence across process restarts (fine for test client)
- Setup endpoint initializes/resets state
- Use deep copies when returning data to prevent aliasing bugs
- Thread safety not needed for test client (single-threaded)

### file_manifest (JSON file + metadata)

```python
import json, os

DATA_FILE = os.path.join(os.getcwd(), 'data.json')
MANIFEST_FILE = os.path.join(os.getcwd(), 'manifest.json')

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)
```

**Key patterns:**
- Read-modify-write cycle for mutations
- Manifest tracks schema version, last modified, etc.
- Atomic writes: write to temp file then rename

### jsonl (append-only JSON lines)

```python
import json, os

LOG_FILE = os.path.join(os.getcwd(), 'events.jsonl')

def append_record(record):
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

def read_all_records():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE) as f:
        return [json.loads(line) for line in f if line.strip()]
```

**Key patterns:**
- Append-only writes (no updates/deletes of existing records)
- Derive current state by replaying all records
- Good for audit trails and event sourcing

## Endpoint Design Patterns

### Setup / Lifecycle Endpoint

Typically `GET /setup`. Must be **idempotent** — calling multiple times produces same result.

```python
@app.route('/setup', methods=['GET'])
def setup():
    # For sqlite3: CREATE TABLE IF NOT EXISTS + conditional seed
    # For SQLAlchemy: db.create_all() + conditional seed
    # For in_memory: reset and reinitialize state
    return jsonify({"status": "ok"}), 200
```

**Idempotency checklist:**
- Tables: `CREATE TABLE IF NOT EXISTS`
- Seed data: check existence before inserting (`SELECT COUNT(*) ...`)
- State reset: only initialize if not already initialized (or always reset — depends on spec)

### CRUD Endpoints

```python
# Create
@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    # validate, create, return 201

# Read (single)
@app.route('/resources/<int:id>', methods=['GET'])
def get_resource(id):
    # lookup, return 200 or 404

# Read (collection, possibly filtered)
@app.route('/resources', methods=['GET'])
def list_resources():
    # filter by query params, return list

# Update
@app.route('/resources/<int:id>', methods=['PUT', 'PATCH'])
def update_resource(id):
    # lookup, validate, update, return updated

# Delete
@app.route('/resources/<int:id>', methods=['DELETE'])
def delete_resource(id):
    # lookup, delete, return 200 or 204
```

### State Transition Endpoints (e.g., transfers, checkout)

These require **atomicity** — either all changes happen or none do.

**Critical ordering with two error-handling zones:**

1. **Pre-transaction zone** — Pure input validation (no transaction open, return JSON errors directly):
   - Parse JSON body → 400 if invalid
   - Check required fields present → 400 if missing
   - Check types and value ranges → 400 if invalid
2. `BEGIN` transaction
3. **In-transaction zone** — Lookups and state-dependent checks (ROLLBACK then return JSON error):
   - Look up referenced resources → ROLLBACK + 404 if missing
   - Check state-dependent invariants (e.g., sufficient balance) → ROLLBACK + 400 if violated
4. Execute all mutations
5. `COMMIT`
6. Return success with updated state
7. `except` block catches only unexpected errors → ROLLBACK + 500 JSON error

```python
@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400

    from_id = data.get('from_id')
    to_id = data.get('to_id')
    amount = data.get('amount')

    # === PRE-TRANSACTION ZONE: pure input validation ===
    # No transaction open; return JSON errors directly.
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    db = get_db()
    try:
        db.execute('BEGIN')

        # === IN-TRANSACTION ZONE: lookups and state checks ===
        # Each failure: ROLLBACK first, then return JSON error.
        sender = db.execute('SELECT * FROM accounts WHERE id = ?', (from_id,)).fetchone()
        if sender is None:
            db.execute('ROLLBACK')
            return jsonify({"error": "Account not found"}), 404

        receiver = db.execute('SELECT * FROM accounts WHERE id = ?', (to_id,)).fetchone()
        if receiver is None:
            db.execute('ROLLBACK')
            return jsonify({"error": "Account not found"}), 404

        if sender['balance'] < amount:
            db.execute('ROLLBACK')
            return jsonify({"error": "Insufficient balance"}), 400

        # === MUTATIONS ===
        db.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, from_id))
        db.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, to_id))
        cur = db.execute(
            'INSERT INTO transactions (from_id, to_id, amount, description) VALUES (?, ?, ?, ?)',
            (from_id, to_id, amount, data.get('description'))
        )
        tx_id = cur.lastrowid

        db.execute('COMMIT')

        return jsonify({
            "sender": {"id": from_id, "balance": sender['balance'] - amount},
            "receiver": {"id": to_id, "balance": receiver['balance'] + amount},
            "transaction_id": tx_id
        }), 200

    except Exception as e:
        # Only truly unexpected errors (DB corruption, etc.)
        db.execute('ROLLBACK')
        return jsonify({"error": f"Internal error: {str(e)}"}), 500
```

**The key rule:** Inside a transaction, every error path is `ROLLBACK` then `return jsonify(...), status_code` — never `raise`. The `raise` pattern would produce Flask's default 500 HTML page, not the JSON error the spec requires. The `except` block is reserved for truly unexpected failures.

## Validation and Error Handling

### Request Parsing

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid or missing JSON body"}), 400
```

Always use `silent=True` to get `None` instead of a 400 exception for malformed JSON.

### Field Validation Pattern

```python
# Check required fields
required = ['field_a', 'field_b']
missing = [f for f in required if f not in data]
if missing:
    return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

# Type validation
if not isinstance(data['amount'], (int, float)):
    return jsonify({"error": "amount must be a number"}), 400

# Value validation
if data['amount'] <= 0:
    return jsonify({"error": "Amount must be positive"}), 400
```

### Error Response Convention

- **400**: Client error — missing fields, invalid values, business rule violations
- **404**: Resource not found
- **409**: Conflict (duplicate, unique constraint violation)
- **500**: Server error (should be rare with proper validation)

Always return JSON error bodies: `{"error": "descriptive message"}`

Match the **exact error messages** specified in the task — tests often check for exact strings.

## Common Pitfalls

1. **Forgetting to commit**: SQLite writes without commit are lost on connection close
2. **Not rolling back on error**: Leaves transaction in bad state
3. **Non-idempotent setup**: Calling setup twice creates duplicate seed data
4. **Missing rollback before in-transaction error return**: Every error path inside a transaction (after BEGIN) must call `db.execute('ROLLBACK')` BEFORE returning a JSON error response. Forgetting the rollback leaves the connection in a broken transaction state, causing all subsequent queries to fail with "cannot start a transaction within a transaction"
5. **Type mismatches**: JSON numbers may be int or float; check with `isinstance(x, (int, float))`
6. **Missing `silent=True`**: `get_json()` without it raises on malformed input
7. **Hardcoded DB paths**: Use `os.getcwd()` or task-specified paths
8. **Not checking resource existence**: Always verify referenced IDs exist before operating
9. **Aliasing mutable state**: Return copies of dicts/lists when using in-memory storage
10. **Ignoring optional fields**: Use `.get('field', default)` for optional request fields

## Testing Compatibility Notes

- Tests use `app.test_client()` — no live server needed
- Each test may call `/setup` to initialize state
- Database files persist between test calls within same process
- For sqlite3: consider using a fresh DB path per test or cleaning up
- Flask's test client preserves cookies and session across requests
- Use `app.test_client()` like:
  ```python
  client = app.test_client()
  resp = client.get('/setup')
  resp = client.post('/transfer', json={...})
  assert resp.status_code == 200
  data = resp.get_json()
  ```

## Implementation Checklist

When implementing any case in this family:

- [ ] Extract all resources, fields, constraints from spec
- [ ] Choose correct persistence pattern
- [ ] Implement setup endpoint (idempotent)
- [ ] Implement all CRUD/transition endpoints
- [ ] Add input validation (required fields, types, ranges)
- [ ] Add state validation (existence checks, business rules)
- [ ] Ensure atomicity for multi-step mutations
- [ ] Match exact error messages and status codes from spec
- [ ] Match exact response schemas from spec
- [ ] Test edge cases: missing fields, invalid types, boundary values, non-existent resources
- [ ] Verify setup idempotency (call twice, same result)
