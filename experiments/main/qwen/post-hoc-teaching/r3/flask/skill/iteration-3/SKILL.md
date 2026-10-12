---
name: flask
description: >
  Build stateful JSON HTTP services with Flask that manage mutable domain state
  across multiple behaviorally coupled endpoints. Covers all persistence models
  (sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl), validation
  patterns, atomic state transitions, idempotent setup, and error handling with
  proper HTTP status codes. Evaluated via Flask test_client.
---

# Flask Stateful JSON Service

## Family Overview

Every task in this family requires building a Flask application (`app` in
`/app/solve.py`) that implements a JSON HTTP service with **mutable domain
state** shared across multiple coupled endpoints. Tests import `app` and use
`app.test_client()`.

## Systematic Approach

### Step 1: Parse the Task Specification

Extract these elements from the task description:

| Element | What to look for |
|---------|-----------------|
| **Resources** | Entity names, fields, types, constraints (e.g., CHECK constraints) |
| **Endpoints** | Route paths, HTTP methods, request format, response schema |
| **Persistence** | Which model: sqlite3, flask_sqlalchemy, in_memory, file_manifest, jsonl |
| **State transitions** | Atomicity requirements, idempotency, cascading effects |
| **Validation rules** | Required fields, type/range checks, existence checks, conflict detection |
| **Error responses** | Exact error messages, HTTP status codes for each failure mode |

**CRITICAL: Note the ORDER of error conditions in the spec.** When multiple error conditions could fire for the same request, the FIRST check that fails determines the response. Tests rely on the spec's listing order as the validation priority order. Implement checks in the exact sequence the spec lists them.

### Step 2: Choose Persistence Strategy

#### sqlite3 (raw SQLite)

```python
import sqlite3
from flask import Flask, request, jsonify, g

app = Flask(__name__)
# Use bare relative path - SQLite resolves against CWD at connection time
DB_FILENAME = 'database.db'

def get_db():
    if 'db' not in g:
        # CRITICAL: Use bare relative path, not os.path.join(os.getcwd(), ...).
        # SQLite resolves relative paths against process CWD at connection time,
        # which is exactly what we want. Tests open separate connections with
        # relative paths like sqlite3.connect("database.db"), so both must
        # resolve at connection time to ensure they access the same file.
        g.db = sqlite3.connect(DB_FILENAME, isolation_level=None)
        g.db.row_factory = sqlite3.Row  # Access columns by name
        g.db.execute("PRAGMA foreign_keys = ON")  # Enable FK enforcement
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Key patterns:**
- **Use bare relative path** — `sqlite3.connect(DB_FILENAME)` where `DB_FILENAME = 'database.db'`. SQLite resolves relative paths against process CWD at connection time, matching how tests verify state. Never capture `os.path.join(os.getcwd(), ...)` at module level.
- **Always use `isolation_level=None`** — Python's default (`isolation_level=""`) auto-starts transactions before DML, which conflicts with explicit `BEGIN` statements and causes `OperationalError: cannot start a transaction within a transaction`.
- Use `g` for per-request DB connections
- `row_factory = sqlite3.Row` for dict-like row access
- Manual `BEGIN`/`COMMIT`/`ROLLBACK` for atomic operations (see Step 5)
- `CREATE TABLE IF NOT EXISTS` for idempotent DDL
- `INSERT OR IGNORE` for idempotent seed data (avoids SELECT COUNT check, no race window)
- `PRAGMA foreign_keys = ON` to enforce FK constraints
- Clean up DB file in tests: remove before each test run

#### flask_sqlalchemy

```python
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    balance = db.Column(db.Float, nullable=False)

# If you need to create tables at import time (before any request):
with app.app_context():
    db.create_all()

# In routes:
# db.session.add(obj)
# db.session.commit()
# db.session.rollback()
# Model.query.filter_by(...).first()
```

**Key patterns:**
- Define models as classes inheriting from `db.Model`
- Use `db.session` for transactions (auto-begin, explicit commit/rollback)
- `db.create_all()` for setup (idempotent)
- Query with `.query.filter_by()`, `.get()`, `.all()`
- **App context**: `db.create_all()`, `db.session`, and model queries all require an active Flask application context. Inside route handlers, the request context provides this automatically. Outside route handlers (e.g., at import time, in test setup code, or in CLI commands), wrap with `with app.app_context():` or you'll get `RuntimeError: Working outside of application context`.
- **Idempotent seeding**: Use `db.session.merge()` or check `db.session.get(Model, id)` before adding:
  ```python
  if db.session.get(Account, 1) is None:
      db.session.add(Account(id=1, owner='Alice', balance=100.0))
      db.session.commit()
  ```
  Note: `Model.query.get()` is legacy in SQLAlchemy 2.0+. Prefer `db.session.get(Model, id)` or `db.session.execute(db.select(Model).filter_by(id=id)).scalar_one_or_none()`.

#### in_memory (process-local dictionaries)

```python
from flask import Flask, request, jsonify
import copy
import threading

app = Flask(__name__)

# Global state
store = {
    'entities': {},  # id -> entity dict
    'next_id': 1,
}
lock = threading.Lock()

def reset_state():
    global store
    store = {'entities': {}, 'next_id': 1}
```

**Key patterns:**
- Use module-level dicts for state
- `threading.Lock()` for thread safety if needed
- `copy.deepcopy()` when returning data to avoid mutation by callers
- Reset function for test isolation
- State persists across requests within the same process (test_client shares the process)

#### file_manifest

```python
import json
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_DIRNAME = 'data'
MANIFEST_FILENAME = 'manifest.json'

def _data_dir():
    # Resolve at call time, not import time
    return os.path.join(os.getcwd(), DATA_DIRNAME)

def _manifest_path():
    return os.path.join(_data_dir(), MANIFEST_FILENAME)

def load_manifest():
    path = _manifest_path()
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_manifest(data):
    d = _data_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, MANIFEST_FILENAME), 'w') as f:
        json.dump(data, f, indent=2)
```

**Key patterns:**
- JSON file as the single source of truth
- Read-modify-write with file locking for atomicity
- Manifest tracks metadata (list of files, counters, etc.)
- Atomic writes: write to temp file, then rename

#### jsonl

```python
import json
import os
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_FILENAME = 'data.jsonl'

def _data_path():
    # Resolve at call time, not import time
    return os.path.join(os.getcwd(), DATA_FILENAME)

def read_all():
    records = []
    path = _data_path()
    if os.path.exists(path):
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records

def append_record(record):
    with open(_data_path(), 'a') as f:
        f.write(json.dumps(record) + '\n')

def rewrite_all(records):
    with open(_data_path(), 'w') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')
```

**Key patterns:**
- Append-only log for new records
- Full rewrite when updating/deleting (or maintain index)
- Each line is a valid JSON object
- Read all lines to reconstruct state

### Step 3: Implement Endpoints

#### Setup / Lifecycle Endpoint

Always make setup **idempotent**:

```python
@app.route('/setup', methods=['GET'])
def setup():
    # For sqlite3: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE for seeds
    # For flask_sqlalchemy: db.create_all() + conditional seed
    # For in_memory: reset to initial state
    # For file/jsonl: create/reset files
    return jsonify({"status": "ok"})
```

**Idempotency patterns:**
- SQLite: `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` for seed data (no SELECT needed, no race window, handles partial state)
- SQLAlchemy: `db.create_all()` is inherently idempotent; use `db.session.merge()` or check `db.session.get(Model, id)` before adding seeds
- In-memory: check if already initialized, or always reset
- File-based: check if file exists, or overwrite

**Preferred SQLite seed pattern:**
```python
@app.route('/setup', methods=['GET'])
def setup():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY, owner TEXT NOT NULL, balance REAL NOT NULL
    )''')
    # INSERT OR IGNORE: idempotent, no race, handles partial state
    db.execute('INSERT OR IGNORE INTO accounts (id, owner, balance) VALUES (1, ?, 100.0)', ('Alice',))
    db.execute('INSERT OR IGNORE INTO accounts (id, owner, balance) VALUES (2, ?, 50.0)', ('Bob',))
    return jsonify({"status": "ok"})
```

#### CRUD Endpoints

```python
# CREATE
@app.route('/resource', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    # Validate required fields
    # Check uniqueness constraints (see Uniqueness Patterns below)
    # Create and persist
    # Capture auto-generated ID via cursor.lastrowid, not SELECT last_insert_rowid()
    return jsonify(created_resource), 201

# READ (single)
@app.route('/resource/<int:id>', methods=['GET'])
def get_resource(id):
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(resource)

# READ (list with filters — see Query Filtering below)
@app.route('/resources', methods=['GET'])
def list_resources():
    results = query_all_with_filters()
    return jsonify(results)

# UPDATE
@app.route('/resource/<int:id>', methods=['PUT', 'PATCH'])
def update_resource(id):
    data = request.get_json(silent=True)
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    # Apply updates, validate
    return jsonify(updated_resource)

# DELETE
@app.route('/resource/<int:id>', methods=['DELETE'])
def delete_resource(id):
    resource = lookup(id)
    if resource is None:
        return jsonify({"error": "Not found"}), 404
    remove(id)
    return jsonify({"status": "deleted"}), 200
```

#### Query Filtering

For list endpoints with query parameters:

```python
@app.route('/resources', methods=['GET'])
def list_resources():
    db = get_db()
    
    # Build dynamic WHERE clause from query params
    conditions = []
    params = []
    
    # Exact match filter
    status = request.args.get('status')
    if status:
        conditions.append('status = ?')
        params.append(status)
    
    # Range filter
    min_val = request.args.get('min', type=float)
    if min_val is not None:
        conditions.append('value >= ?')
        params.append(min_val)
    
    # Multi-value filter (e.g., ?tag=a&tag=b)
    tags = request.args.getlist('tag')
    if tags:
        placeholders = ','.join('?' * len(tags))
        conditions.append(f'tag IN ({placeholders})')
        params.extend(tags)
    
    # Text search (LIKE)
    search = request.args.get('q')
    if search:
        conditions.append('name LIKE ?')
        params.append(f'%{search}%')
    
    where_clause = ' AND '.join(conditions) if conditions else '1=1'
    query = f'SELECT * FROM resources WHERE {where_clause} ORDER BY id'
    
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(row) for row in rows])
```

**Key patterns:**
- Use `request.args.get('key', type=int)` for automatic type conversion
- Use `request.args.getlist('key')` for multi-value parameters
- Build WHERE clauses dynamically from present parameters
- Always use parameterized queries to prevent SQL injection

#### Redirects

When the spec requires redirects (e.g., after creating a resource):

```python
from flask import redirect, url_for

@app.route('/shorten', methods=['POST'])
def shorten():
    data = request.get_json(silent=True)
    # ... create short URL ...
    # Return 201 with Location header (RESTful) or redirect
    return jsonify({"short_url": f"/{code}"}), 201, {'Location': f'/{code}'}

@app.route('/<code>', methods=['GET'])
def redirect_to_url(code):
    db = get_db()
    row = db.execute('SELECT url FROM urls WHERE code = ?', (code,)).fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    return redirect(row['url'], code=302)  # or 301 for permanent
```

**Key patterns:**
- Use `redirect(url, code=302)` for HTTP redirects
- Use `url_for('endpoint_name', **kwargs)` to generate URLs to other routes
- Return `(response, status, headers)` tuple to set Location header without redirecting
- 301 = permanent redirect, 302 = temporary redirect

#### Middleware Patterns

When the spec requires "a request middleware plus a lifecycle endpoint":

```python
# before_request: runs before every request
@app.before_request
def before_request_handler():
    # Common setup: initialize DB connection, check auth, log request
    g.request_start = time.time()
    # Example: require API key for all endpoints except /setup
    if request.endpoint != 'setup':
        api_key = request.headers.get('X-API-Key')
        if not api_key or not validate_api_key(api_key):
            return jsonify({"error": "Unauthorized"}), 401

# after_request: runs after every request (even on error)
@app.after_request
def after_request_handler(response):
    # Common tasks: add headers, log response, measure timing
    duration = time.time() - g.get('request_start', time.time())
    response.headers['X-Request-Duration'] = str(duration)
    return response

# teardown_appcontext: runs after request context is popped
@app.teardown_appcontext
def teardown(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Key patterns:**
- `@app.before_request` can return a response to short-circuit the request
- `@app.after_request` receives and must return the response object
- Use `g` to pass data between before_request, the view, and after_request
- `request.endpoint` gives the name of the view function being called
- Middleware is useful for cross-cutting concerns: auth, logging, rate limiting

#### Counter and Aggregate Patterns

When state transitions require maintaining counters or aggregates:

```python
# Atomic counter increment
@app.route('/tasks/<int:id>/complete', methods=['POST'])
def complete_task(id):
    db = get_db()
    db.execute('BEGIN')
    try:
        # Update the task
        db.execute('UPDATE tasks SET status = ? WHERE id = ?', ('completed', id))
        # Atomically increment a counter
        db.execute('UPDATE stats SET completed_count = completed_count + 1')
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    return jsonify({"status": "ok"})

# Compute aggregate on demand
@app.route('/stats', methods=['GET'])
def get_stats():
    db = get_db()
    row = db.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            AVG(duration) as avg_duration
        FROM tasks
    ''').fetchone()
    return jsonify(dict(row))
```

**Key patterns:**
- Use `SET counter = counter + 1` for atomic increments (not read-modify-write)
- Compute aggregates with SQL when possible (SUM, AVG, COUNT, GROUP BY)
- For in-memory: use thread-safe operations or locks around counter updates

#### Uniqueness Constraint Handling

When resources must have unique fields (e.g., unique names, codes, URLs):

```python
# SQLite: use UNIQUE constraint + INSERT OR IGNORE or catch IntegrityError
@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    name = data.get('name')
    
    db = get_db()
    # Option 1: Check before insert (TOCTOU race, but OK for test_client)
    existing = db.execute('SELECT id FROM resources WHERE name = ?', (name,)).fetchone()
    if existing:
        return jsonify({"error": "Resource already exists"}), 409
    
    # Option 2: Try insert, catch IntegrityError (more robust)
    try:
        cursor = db.execute('INSERT INTO resources (name) VALUES (?)', (name,))
        resource_id = cursor.lastrowid  # ← Use cursor.lastrowid, not SELECT last_insert_rowid()
        return jsonify({"id": resource_id, "name": name}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Resource already exists"}), 409
```

**Key patterns:**
- Use `UNIQUE` constraint in table definition for database-level enforcement
- Catch `sqlite3.IntegrityError` for robust uniqueness handling
- Return 409 Conflict for duplicate resources
- Use `cursor.lastrowid` immediately after INSERT to get the auto-generated ID
- Never use `SELECT last_insert_rowid()` — it's fragile and can return wrong values in concurrent scenarios

### Step 4: Implement Validation and Error Handling

#### Standard validation pattern:

**CRITICAL: Implement checks in the EXACT ORDER the spec lists error conditions.** When multiple errors could fire, the first check that fails determines the response. Tests rely on spec ordering as priority ordering.

```python
@app.route('/action', methods=['POST'])
def action():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    # Implement checks in spec-listed order:
    # 1. Check required fields exist (if spec lists this first)
    required = ['field_a', 'field_b']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # 2. Type validation (if spec lists this second)
    if not isinstance(data['field_a'], int):
        return jsonify({"error": "field_a must be an integer"}), 400

    # 3. Range/value validation (if spec lists this third)
    if data['amount'] <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    # 4. Existence validation (if spec lists this fourth)
    resource = lookup(data['resource_id'])
    if resource is None:
        return jsonify({"error": "Resource not found"}), 404

    # 5. Business logic validation (if spec lists this fifth)
    if resource['balance'] < data['amount']:
        return jsonify({"error": "Insufficient balance"}), 400

    # 6. Conflict validation (if spec lists this sixth)
    if data['source'] == data['destination']:
        return jsonify({"error": "Source and destination must differ"}), 400

    # Perform the action...
```

**Example: v01 spec lists errors in this order:**
1. Missing fields → 400
2. Same account → 400
3. Amount ≤ 0 → 400
4. Insufficient balance → 400
5. Non-existent account → 404

**Your code must check in this exact order.** If a test sends `{"from_id": 999, "to_id": 999, "amount": -5}`, three conditions fire: same account, negative amount, and non-existent account. The test expects the error for whichever condition appears first in the spec — "Cannot transfer to the same account" (400).

#### Type Coercion and Robust Validation

JSON numbers can arrive as int or float. Be explicit about what you accept:

```python
# Accept both int and float for numeric fields
amount = data.get('amount')
if amount is None:
    return jsonify({"error": "Missing amount"}), 400
if not isinstance(amount, (int, float)):
    return jsonify({"error": "amount must be a number"}), 400
# Convert to float for consistency
amount = float(amount)

# For IDs that should be integers
resource_id = data.get('resource_id')
if resource_id is not None:
    try:
        resource_id = int(resource_id)
    except (ValueError, TypeError):
        return jsonify({"error": "resource_id must be an integer"}), 400

# Use request.args.get with type parameter for query params
page = request.args.get('page', 1, type=int)  # Auto-converts, defaults to 1
limit = request.args.get('limit', 20, type=int)
```

**Key patterns:**
- `isinstance(val, (int, float))` accepts both JSON number types
- `request.args.get('key', default, type=int)` handles conversion automatically
- Always validate before coercing — catch `ValueError` and `TypeError`
- Convert to a consistent type (e.g., always float for money) early in validation

#### Cascading Validation

When operations affect multiple related resources, validate all preconditions atomically:

```python
@app.route('/checkout', methods=['POST'])
def checkout():
    data = request.get_json(silent=True)
    cart_id = data.get('cart_id')
    
    db = get_db()
    db.execute('BEGIN')
    try:
        # Validate cart exists and is not empty
        cart = db.execute('SELECT * FROM carts WHERE id = ?', (cart_id,)).fetchone()
        if cart is None:
            db.execute('ROLLBACK')
            return jsonify({"error": "Cart not found"}), 404
        
        items = db.execute('SELECT * FROM cart_items WHERE cart_id = ?', (cart_id,)).fetchall()
        if not items:
            db.execute('ROLLBACK')
            return jsonify({"error": "Cart is empty"}), 400
        
        # Validate all items have sufficient stock
        for item in items:
            product = db.execute('SELECT * FROM products WHERE id = ?', (item['product_id'],)).fetchone()
            if product['stock'] < item['quantity']:
                db.execute('ROLLBACK')
                return jsonify({"error": f"Insufficient stock for {product['name']}"}), 400
        
        # All validations passed — perform cascading updates
        total = 0
        for item in items:
            db.execute('UPDATE products SET stock = stock - ? WHERE id = ?', 
                      (item['quantity'], item['product_id']))
            total += item['quantity'] * item['price']
        
        db.execute('INSERT INTO orders (cart_id, total, status) VALUES (?, ?, ?)',
                  (cart_id, total, 'completed'))
        db.execute('DELETE FROM cart_items WHERE cart_id = ?', (cart_id,))
        
        db.execute('COMMIT')
        return jsonify({"status": "ok", "total": total}), 200
    except Exception:
        db.execute('ROLLBACK')
        raise
```

**Key patterns:**
- Validate ALL preconditions before ANY mutations
- Use a single transaction for the entire cascading operation
- Rollback on any validation failure — no partial state changes
- Return specific error messages indicating which resource failed validation

| Status | When to use |
|--------|-------------|
| 200 | Successful GET, PUT, or state-changing POST |
| 201 | Successful resource creation |
| 204 | Successful deletion (no body) or sometimes 200 with message |
| 400 | Missing fields, invalid types/ranges, business rule violations |
| 404 | Referenced resource does not exist |
| 409 | Conflict (duplicate, unique constraint violation) |
| 500 | Internal server error (unexpected exceptions) |

### Step 5: Atomic State Transitions

#### sqlite3 atomic operations:

**Requires `isolation_level=None` in `get_db()` (see Step 2).**

```python
def atomic_transfer(db, from_id, to_id, amount):
    db.execute('BEGIN')
    try:
        # All mutations here
        db.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount, from_id))
        db.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount, to_id))
        db.execute('INSERT INTO transactions (from_id, to_id, amount) VALUES (?, ?, ?)',
                   (from_id, to_id, amount))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
```

**Why `isolation_level=None` is mandatory here:** Python's `sqlite3.connect()` defaults to `isolation_level=""` (deferred), which auto-issues `BEGIN` before the first DML statement. If you then call `db.execute('BEGIN')` explicitly, it crashes with `OperationalError: cannot start a transaction within a transaction`. Setting `isolation_level=None` disables this implicit behavior and gives you full manual control.

#### flask_sqlalchemy atomic operations:

```python
def atomic_operation():
    try:
        # All mutations via db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
```

#### in_memory atomic operations:

```python
# Use a lock to ensure atomicity
with lock:
    # All state mutations here
    pass
```

### Step 6: Response Formatting

Always return JSON with `jsonify()`. Match the exact response schema from the task spec:

```python
# Success response - match exact field names from spec
return jsonify({
    "id": resource['id'],
    "name": resource['name'],
    # ... exact fields specified
}), 200

# Error response - match exact error message from spec
return jsonify({"error": "Exact error message from spec"}), 400
```

## Critical Implementation Notes

### Test Client Usage

Tests will do:
```python
from solve import app
client = app.test_client()
resp = client.get('/setup')
resp = client.post('/endpoint', json={...})
```

The `app` object must be importable from `solve.py` at module level.

### Database File Location

For file-based persistence (sqlite3, file_manifest, jsonl):
- **sqlite3**: Use bare relative path `sqlite3.connect(DB_FILENAME)` — SQLite resolves against CWD at connection time
- **file_manifest/jsonl**: Use helper functions like `_data_path()` that resolve at call time
- Tests verify state by opening separate connections with relative paths like `sqlite3.connect("filename.db")`
- Never capture `os.path.join(os.getcwd(), ...)` at module level — this freezes the path at import time
- If CWD changes between import and test execution, import-time path capture causes "no such table" errors

### Idempotent Setup

The `/setup` endpoint must be safely callable multiple times:
- Use `CREATE TABLE IF NOT EXISTS` for SQL
- Use `INSERT OR IGNORE` for seed rows (no SELECT COUNT needed)
- For in-memory: either always reset or check initialization flag

### Request Parsing

```python
# JSON body
data = request.get_json(silent=True)  # Returns None if not valid JSON

# Query parameters
value = request.args.get('key')  # Returns None if missing
value = request.args.get('key', default)  # With default

# URL parameters
@app.route('/resource/<int:id>')  # Auto-converts to int
@app.route('/resource/<path:filepath>')  # Captures slashes
```

### Common Pitfalls

1. **Forgetting `db.commit()`** after INSERT/UPDATE/DELETE in raw sqlite3
2. **Not handling `get_json(silent=True)` returning None** for malformed JSON
3. **Not checking for None** when accessing optional fields with `.get()`
4. **Race conditions** in in-memory stores without locks
5. **Non-idempotent setup** that fails on second call
6. **Forgetting to clean up** DB files between test runs (use `os.remove` in setup if needed)
7. **Returning wrong status codes** (e.g., 200 instead of 201 for creation)
8. **Not matching exact error messages** from the spec
9. **SQLite `isolation_level` trap**: Using `sqlite3.connect(path)` without `isolation_level=None` causes Python to auto-start transactions before DML. Any subsequent explicit `db.execute('BEGIN')` crashes with `OperationalError: cannot start a transaction within a transaction`. Always use `isolation_level=None` when you need manual transaction control.
10. **Flask-SQLAlchemy app context**: `db.create_all()`, `db.session`, and model queries all require an active Flask application context. Inside route handlers this is automatic, but any code outside a request handler (import-time setup, test fixtures, CLI commands) needs `with app.app_context():` or it raises `RuntimeError: Working outside of application context`.
11. **Non-atomic seed with SELECT COUNT + INSERT**: Using `SELECT COUNT(*)` to check before seeding is fragile — it has a race window and doesn't fix partial state. Use `INSERT OR IGNORE` (sqlite3) or `db.session.merge()` (SQLAlchemy) for truly idempotent seeding.
12. **Import-time DB path capture**: Using `DB_PATH = os.path.join(os.getcwd(), 'file.db')` at module level captures CWD at import time. If the test framework changes CWD between import and test execution, the Flask app writes to a different file than where tests verify with `sqlite3.connect('file.db')`. Fix: use bare relative path `sqlite3.connect(DB_FILENAME)` for sqlite3, or resolve paths inside helper functions for file_manifest/jsonl.
13. **Using `SELECT last_insert_rowid()` instead of `cursor.lastrowid`**: After an INSERT, use `cursor.lastrowid` to get the auto-generated ID. `SELECT last_insert_rowid()` is fragile and can return wrong values in concurrent scenarios or if another INSERT happens between your INSERT and the SELECT.
14. **Not validating all preconditions before mutations in cascading operations**: When an operation affects multiple related resources (e.g., checkout validates stock for all cart items), validate ALL preconditions inside the transaction BEFORE performing ANY mutations. Otherwise, partial state changes can occur if a later validation fails.
15. **Forgetting `@app.after_request` must return the response**: The `after_request` handler receives the response object and must return it (possibly modified). If you forget the `return response` statement, Flask will raise an error.
16. **Validation check order doesn't match spec order**: When multiple error conditions could fire for the same request, the FIRST check that fails determines the response. Tests rely on the spec's listing order as the validation priority order. If your code checks conditions in a different order than the spec lists them, tests will fail with wrong error messages. Always implement validation checks in the exact sequence the spec lists error conditions.

## Test Compatibility

Tests in this family often verify state by opening **separate database connections** after making requests through the Flask test client. For example:

```python
# Test pattern: verify state via separate connection
def test_something():
    client = app.test_client()
    client.get('/setup')
    client.post('/endpoint', json={...})
    
    # Test opens its own connection to verify state
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM table')
    # Assert on results...
```

**Critical requirements for test compatibility:**

1. **DB path consistency**: The Flask app and test must access the same file. Use bare relative paths for sqlite3 (`sqlite3.connect(DB_FILENAME)`), or resolve paths at call time for file_manifest/jsonl.

2. **Connection cleanup**: Ensure `teardown_appcontext` closes the Flask app's connection after each request, so the test's separate connection can see committed changes.

3. **Committed state**: With `isolation_level=None`, all changes are autocommitted immediately. The test's separate connection will see the latest state.

4. **File location**: Use the exact filename specified in the task (e.g., `bank.db`, `database.db`). Tests will use that same filename with a relative path.

## Diagnostic Patterns

**"API works but verification fails" = state location mismatch**

When tests that check HTTP responses pass but tests that verify internal state via separate channels fail, the root cause is almost always a **path or location divergence** between the service's state and the verifier's access point — not a code logic error.

**Signature pattern:**
- Tests checking HTTP status codes and JSON response bodies: ✓ PASS
- Tests opening separate `sqlite3.connect()` or file reads to verify state: ✗ FAIL with "no such table" or "file not found"

**Diagnostic shortcut:** The moment you see "no such table" from a *separate* connection while the API returns correct responses, you know immediately: the table exists, but in a different file than where the test is looking. Check path resolution timing (import-time vs connection-time) before investigating logic errors.

## Checklist Before Submitting

- [ ] `app` is defined at module level in `/app/solve.py`
- [ ] All routes from the spec are implemented with correct HTTP methods
- [ ] Setup endpoint is idempotent
- [ ] All validation rules from the spec are implemented
- [ ] Validation checks are in the exact order the spec lists error conditions
- [ ] Error responses use exact messages and status codes from spec
- [ ] Success responses match the exact schema from spec
- [ ] State transitions are atomic where required
- [ ] Persistence works correctly (DB file path, table creation, etc.)
- [ ] No leftover state from previous test runs (clean DB in setup)
- [ ] sqlite3 connections use `isolation_level=None` for manual transaction control
- [ ] Flask-SQLAlchemy code uses `app.app_context()` when outside request handlers
- [ ] DB paths are resolved at connection time, not import time
- [ ] Tests can verify state via separate DB connections (path consistency)
- [ ] Use `cursor.lastrowid` after INSERT, not `SELECT last_insert_rowid()`
- [ ] Cascading operations validate all preconditions before any mutations
- [ ] Middleware handlers (`before_request`, `after_request`) follow Flask conventions
- [ ] Type coercion handles both int and float for numeric JSON fields
