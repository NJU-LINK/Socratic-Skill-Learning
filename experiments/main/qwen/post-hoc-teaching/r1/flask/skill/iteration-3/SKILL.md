---
name: flask
description: Build stateful Flask JSON HTTP services with multiple coupled endpoints, proper persistence, atomic state transitions, and comprehensive validation
---

# Flask Stateful Service Skill

## Core Pattern

Every case in this family implements a **stateful JSON HTTP service** where requests share mutable domain state. The service has multiple behaviorally coupled endpoints (or middleware + lifecycle endpoints) that must maintain consistency.

## Mandatory Structure

### App Export
```python
from flask import Flask, request, jsonify
app = Flask(__name__)
```

The Flask application object **must** be named `app` and exported from `/app/solve.py`. Tests import it via `from solve import app` and use `app.test_client()`.

### Working Directory
All file-based persistence (SQLite databases, JSON files, manifests) must use **relative paths** that resolve at connection time:
```python
DB_PATH = 'database.db'  # Relative path - resolves to CWD at connection time
```

**CRITICAL: Never use `os.path.join(os.getcwd(), ...)` at module level**

This creates an absolute path at import time. If the test process changes CWD between module import and test execution, the app writes to the wrong location while tests read from the current CWD, causing "no such table" errors.

With relative paths:
- `sqlite3.connect('bank.db')` resolves to CWD at **connection time**
- Matches test behavior: `sqlite3.connect('bank.db')` in test code
- Works correctly even if CWD changes between import and execution

## Persistence Models

### SQLite3 (Raw)
```python
import sqlite3

DB_PATH = 'database.db'  # Relative path - resolves at connection time

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # CRITICAL: disable auto-transactions
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

# In route handlers:
db = get_db_connection()
try:
    db.execute('BEGIN')
    # ... operations ...
    db.commit()
except:
    db.rollback()
    raise
finally:
    db.close()
```

**CRITICAL: `isolation_level=None`**

Python's `sqlite3.connect()` with default `isolation_level` enables **automatic transaction management**: before any DML statement (INSERT, UPDATE, DELETE), Python auto-issues `BEGIN`. When you also issue explicit `BEGIN`, you get two competing transaction managers, causing `OperationalError: cannot start a transaction within a transaction`.

With `isolation_level=None`:
- Python **never** auto-issues `BEGIN`
- You have full manual control of `BEGIN` / `COMMIT` / `ROLLBACK`
- Without explicit `BEGIN`, each statement runs in autocommit mode
- With explicit `BEGIN`, all statements until `COMMIT`/`ROLLBACK` are atomic

This pattern is robust for all family variants, including those with middleware, logging, or connection reuse.

**Key points:**
- Use `CREATE TABLE IF NOT EXISTS` for idempotent setup
- Check `SELECT COUNT(*)` before seeding to ensure idempotency
- Use explicit transactions (`BEGIN`/`COMMIT`/`ROLLBACK`) for atomicity
- Always close connections in `finally` blocks

### Flask-SQLAlchemy
```python
from flask_sqlalchemy import SQLAlchemy

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db = SQLAlchemy(app)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields ...

# In setup:
with app.app_context():
    db.create_all()
    if Resource.query.count() == 0:
        # seed data
        db.session.commit()
```

### In-Memory (Process-Local Dictionaries)
```python
# Module-level state
resources = {}
next_id = 1

@app.route('/setup', methods=['GET'])
def setup():
    global resources, next_id
    if not resources:  # Idempotent: only seed if empty
        resources[1] = {'id': 1, 'name': 'Item 1'}
        next_id = 2
    return jsonify({"status": "ok"})
```

**Key points:**
- State persists across requests within the same process
- Check if state is empty before seeding
- No need for transactions (single-threaded test client)

### File Manifest
```python
import json

MANIFEST_FILE = 'manifest.json'
DATA_FILE = 'data.json'

def load_state():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE) as f:
            manifest = json.load(f)
        with open(manifest['data_file']) as f:
            return json.load(f)
    return {}

def save_state(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)
    with open(MANIFEST_FILE, 'w') as f:
        json.dump({'data_file': DATA_FILE}, f)
```

### JSONL (JSON Lines)
```python
DATA_FILE = 'data.jsonl'

def append_record(record):
    with open(DATA_FILE, 'a') as f:
        f.write(json.dumps(record) + '\n')

def read_all_records():
    records = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            for line in f:
                records.append(json.loads(line))
    return records
```

## Setup/Lifecycle Endpoint Pattern

The setup endpoint must be **idempotent**:

```python
@app.route('/setup', methods=['GET'])
def setup():
    # 1. Create tables/files if not exists
    # 2. Check if already seeded
    # 3. Only seed if empty
    # 4. Return success status
    return jsonify({"status": "ok"}), 200
```

**Idempotency strategies:**
- SQL: `CREATE TABLE IF NOT EXISTS` + check `COUNT(*)` before inserting seed data
- In-memory: Check if dictionary is empty before populating
- File-based: Check if file exists or is empty before writing

## Request Handling Pattern

### Parse JSON Body
```python
data = request.get_json(force=True, silent=True)
if data is None:
    return jsonify({"error": "Invalid JSON"}), 400
```

**Why `force=True`?** Flask's `get_json()` requires `Content-Type: application/json` by default. Some test clients may send JSON without this header (e.g., `client.post('/path', data=json.dumps({...}))` without `content_type`). Using `force=True` tells Flask to attempt JSON parsing regardless of Content-Type, while `silent=True` returns None instead of raising on parse failure. This combination handles all test client patterns robustly.

### Validate Required Fields
```python
field1 = data.get('field1')
field2 = data.get('field2')

if field1 is None or field2 is None:
    return jsonify({"error": "Missing required fields"}), 400
```

### Business Logic Validation
```python
# Domain-specific validations
if field1 == field2:
    return jsonify({"error": "Cannot operate on same resource"}), 400

if field1 <= 0:
    return jsonify({"error": "Value must be positive"}), 400

# Check resource existence
resource = db.execute('SELECT * FROM resources WHERE id = ?', (id,)).fetchone()
if resource is None:
    return jsonify({"error": "Resource not found"}), 404

# Check state constraints
if resource['balance'] < amount:
    return jsonify({"error": "Insufficient balance"}), 400
```

### Type Validation with Boolean Exclusion

**CRITICAL**: In Python, `bool` is a subclass of `int`, so `isinstance(True, int)` returns `True`. When validating numeric fields, you must exclude booleans first:

```python
# WRONG: True/False pass this check (True == 1, False == 0)
if not isinstance(amount, (int, float)) or amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400

# CORRECT: Exclude booleans before checking numeric type
if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400
```

This pattern applies to any numeric field validation where boolean values should be rejected.

## State Transition Pattern

### Validation Ordering Principle

**All pure-input validation (missing fields, type checks, same-account, negative amount) must happen BEFORE opening any DB connection or transaction.** DB-dependent validation (account existence, sufficient balance) happens after. This ensures:
1. You never hold a transaction open while doing non-DB work
2. You never need to rollback for reasons that could have been caught earlier
3. Error responses are deterministic regardless of DB state

### Atomic Operations (SQL)
```python
# Phase 1: Pure input validation (no DB)
if from_id is None or to_id is None or amount is None:
    return jsonify({"error": "Missing required fields"}), 400
if from_id == to_id:
    return jsonify({"error": "Cannot operate on same resource"}), 400
if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400

# Phase 2: DB transaction (all DB work here)
db = get_db_connection()
try:
    db.execute('BEGIN')
    
    # 1. Read current state
    resource1 = db.execute('SELECT * FROM resources WHERE id = ?', (id1,)).fetchone()
    resource2 = db.execute('SELECT * FROM resources WHERE id = ?', (id2,)).fetchone()
    
    # 2. DB-dependent validation
    if resource1 is None or resource2 is None:
        db.rollback()
        return jsonify({"error": "Resource not found"}), 404
    
    if resource1['balance'] < amount:
        db.rollback()
        return jsonify({"error": "Insufficient"}), 400
    
    # 3. Perform updates
    db.execute('UPDATE resources SET balance = balance - ? WHERE id = ?', (amount, id1))
    db.execute('UPDATE resources SET balance = balance + ? WHERE id = ?', (amount, id2))
    
    # 4. Record the operation
    cursor = db.execute('INSERT INTO operations ...')
    operation_id = cursor.lastrowid
    
    db.commit()
    
    # 5. Fetch updated state for response
    updated1 = db.execute('SELECT * FROM resources WHERE id = ?', (id1,)).fetchone()
    updated2 = db.execute('SELECT * FROM resources WHERE id = ?', (id2,)).fetchone()
    
    return jsonify({
        "resource1": {"id": updated1['id'], "balance": updated1['balance']},
        "resource2": {"id": updated2['id'], "balance": updated2['balance']},
        "operation_id": operation_id
    }), 200
    
except Exception as e:
    db.rollback()
    return jsonify({"error": str(e)}), 500
finally:
    db.close()
```

### Atomic Operations (In-Memory)
```python
# Single-threaded, so no explicit transactions needed
# But maintain consistency by updating all state together

if resources[id1]['balance'] < amount:
    return jsonify({"error": "Insufficient"}), 400

resources[id1]['balance'] -= amount
resources[id2]['balance'] += amount
operation_id = next_op_id
next_op_id += 1

return jsonify({
    "resource1": resources[id1],
    "resource2": resources[id2],
    "operation_id": operation_id
}), 200
```

## Error Response Pattern

Always return JSON errors with appropriate HTTP status codes:

```python
# 400 Bad Request - validation errors
return jsonify({"error": "Missing required fields"}), 400
return jsonify({"error": "Invalid value"}), 400

# 404 Not Found - resource doesn't exist
return jsonify({"error": "Resource not found"}), 404

# 409 Conflict - state conflict (optional, often use 400)
return jsonify({"error": "Resource already exists"}), 409

# 500 Internal Server Error - unexpected errors
return jsonify({"error": "Internal error"}), 500
```

## Response Format Pattern

Return created/updated resources with consistent structure:

```python
# Single resource
return jsonify({
    "id": resource['id'],
    "name": resource['name'],
    "field": resource['field']
}), 201  # 201 for creation, 200 for updates

# Multiple resources
return jsonify({
    "resource1": {"id": ..., "field": ...},
    "resource2": {"id": ..., "field": ...},
    "operation_id": ...
}), 200

# List of resources
return jsonify({
    "resources": [
        {"id": 1, "name": "Item 1"},
        {"id": 2, "name": "Item 2"}
    ]
}), 200

# Status response
return jsonify({"status": "ok"}), 200
```

## Common Endpoint Patterns

### CRUD Endpoints
```python
# Create
@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json()
    # validate, insert, return 201

# Read (single)
@app.route('/resources/<int:id>', methods=['GET'])
def get_resource(id):
    # query, return 200 or 404

# Read (list with filters)
@app.route('/resources', methods=['GET'])
def list_resources():
    filter_field = request.args.get('field')
    # query with WHERE clause, return list

# Update
@app.route('/resources/<int:id>', methods=['PUT', 'PATCH'])
def update_resource(id):
    data = request.get_json()
    # validate, update, return 200 or 404

# Delete
@app.route('/resources/<int:id>', methods=['DELETE'])
def delete_resource(id):
    # delete, return 204 or 404
```

### Operation Endpoints
```python
# Atomic multi-resource operation
@app.route('/operations/transfer', methods=['POST'])
def transfer():
    # validate, perform atomic update, return updated resources
```

### Query Parameter Parsing

For list/filter endpoints, parse query parameters with type validation:

```python
@app.route('/resources', methods=['GET'])
def list_resources():
    # String parameters with defaults
    status = request.args.get('status', 'active')
    
    # Integer parameters with validation
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Boolean parameters (query strings are always strings)
    include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'
    
    # Multiple values for same key
    tags = request.args.getlist('tag')  # /resources?tag=a&tag=b
    
    # Build dynamic query
    query = 'SELECT * FROM resources WHERE 1=1'
    params = []
    
    if status:
        query += ' AND status = ?'
        params.append(status)
    
    if not include_deleted:
        query += ' AND deleted_at IS NULL'
    
    query += ' ORDER BY id LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])
    
    db = get_db_connection()
    try:
        rows = db.execute(query, params).fetchall()
        return jsonify({"resources": [dict(row) for row in rows]}), 200
    finally:
        db.close()
```

### Uniqueness and Conflict Handling

When creating resources with unique constraints (e.g., unique names, emails, URLs):

```python
@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    name = data.get('name')
    if name is None:
        return jsonify({"error": "Missing required field: name"}), 400
    
    db = get_db_connection()
    try:
        # Check uniqueness before insert
        existing = db.execute('SELECT id FROM resources WHERE name = ?', (name,)).fetchone()
        if existing is not None:
            return jsonify({"error": "Resource already exists"}), 409  # or 400 per task spec
        
        # Insert
        cursor = db.execute('INSERT INTO resources (name) VALUES (?)', (name,))
        resource_id = cursor.lastrowid
        
        # Fetch and return created resource
        resource = db.execute('SELECT * FROM resources WHERE id = ?', (resource_id,)).fetchone()
        return jsonify({"id": resource['id'], "name": resource['name']}), 201
    finally:
        db.close()
```

**Note**: Some tasks specify 400 for conflicts instead of 409. Always check the task specification for the required status code.

### Reset Endpoint Pattern

Some tasks require a reset endpoint that clears state and re-seeds:

```python
@app.route('/reset', methods=['POST'])
def reset():
    db = get_db_connection()
    try:
        # Drop and recreate tables
        db.execute('DROP TABLE IF EXISTS resources')
        db.execute('CREATE TABLE resources (...)')
        
        # Re-seed initial data
        db.execute('INSERT INTO resources ...')
        
        return jsonify({"status": "reset complete"}), 200
    finally:
        db.close()
```

**Idempotency**: Reset should be safe to call multiple times, always returning to the same initial state.

## Testing Pattern

Tests use Flask's test client:
```python
from solve import app

client = app.test_client()

# GET request
response = client.get('/setup')
assert response.status_code == 200
data = response.get_json()

# POST request with JSON
response = client.post('/resources', json={'name': 'Item', 'value': 100})
assert response.status_code == 201
data = response.get_json()

# POST with query parameters
response = client.post('/resources?field=value', json={...})
```

### Test Database Verification Pattern

**CRITICAL**: Tests often directly query the database to verify state after API calls:
```python
# Test calls API endpoint
resp = client.post('/transfer', json={'from_id': 1, 'to_id': 2, 'amount': 25.0})
assert resp.status_code == 200

# Test then directly queries database to verify state
conn = sqlite3.connect('bank.db')  # Uses relative path
cur = conn.cursor()
cur.execute('SELECT balance FROM accounts WHERE id = 1')
assert cur.fetchone()[0] == 75.0
conn.close()
```

This means:
1. **Use relative paths for DB files** - The test's `sqlite3.connect('bank.db')` resolves to CWD at call time. Your app must use the same relative path so they access the same file.
2. **Never use `os.path.join(os.getcwd(), ...)` at module level** - This creates an absolute path at import time. If CWD changes between import and test execution, the app and test access different files.
3. **Always commit changes** - Tests check the database after the request completes, so all changes must be committed (not left in an open transaction).

## Checklist for Implementation

1. ✓ Import Flask, request, jsonify, and persistence libraries
2. ✓ Create `app = Flask(__name__)`
3. ✓ Define persistence layer (DB connection, file paths, or in-memory state)
4. ✓ Implement `/setup` endpoint with idempotent initialization
5. ✓ Implement domain endpoints with proper HTTP methods
6. ✓ Parse JSON request bodies with error handling
7. ✓ Validate required fields and business logic constraints
8. ✓ Perform atomic state transitions (transactions for SQL)
9. ✓ Return appropriate HTTP status codes (200, 201, 400, 404, etc.)
10. ✓ Return JSON responses with consistent structure
11. ✓ Handle errors gracefully with rollback/cleanup
12. ✓ Close database connections in finally blocks

## Key Principles

1. **Idempotency**: Setup operations must be safe to call multiple times
2. **Atomicity**: State transitions must be all-or-nothing (use transactions)
3. **Consistency**: Validate constraints before modifying state
4. **Error Handling**: Return proper HTTP codes and JSON error messages
5. **Resource Management**: Always close database connections
6. **Response Format**: Return complete resource representations after operations
