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

### 6. Database Path Resolution

When the task spec says "database in the current working directory" (or similar), **always use a relative path**:

```python
# CORRECT: Relative path resolves at connect-time
DB_PATH = "bank.db"
# Each sqlite3.connect(DB_PATH) resolves relative to CWD at that moment

# WRONG: Absolute path locked at import-time
DB_PATH = os.path.join(os.getcwd(), "bank.db")
# If CWD changes between import and test assertions, they see different files
```

**Why this matters**: Test harnesses frequently:
1. Import the app module (which sets `DB_PATH` at module level)
2. Change CWD or run from a different directory
3. Open their own `sqlite3.connect("bank.db")` to verify state

If the app uses an absolute path computed at import time, the test's relative-path connection opens a different (empty) file → "no such table" errors. With relative paths, both resolve identically because they use the same CWD at connect-time.

This applies to all file-based persistence: JSON files, manifests, JSONL logs — always use relative paths when the spec says "current working directory."

### 7. Request-Scoped Resource Lifecycle

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

## Endpoint Patterns

The spec's `endpoint_contract` axis allows arbitrary route paths, HTTP methods, query filters, JSON bodies, redirects, status codes, and response schemas. The `state_transition_semantics` axis includes CRUD updates, uniqueness, counters, aggregates, checkout, and cascading validation. Here are patterns for each:

### CRUD Endpoints

When the API manages resources with full lifecycle:

```python
# GET /resources — list with optional filters
@app.route('/resources', methods=['GET'])
def list_resources():
    # Extract query parameters for filtering
    status = request.args.get('status')
    owner_id = request.args.get('owner_id', type=int)
    
    db = get_db()
    query = "SELECT * FROM resources WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    if owner_id:
        query += " AND owner_id = ?"
        params.append(owner_id)
    
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(row) for row in rows]), 200

# GET /resources/<id> — single resource
@app.route('/resources/<int:resource_id>', methods=['GET'])
def get_resource(resource_id):
    db = get_db()
    row = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Resource not found"}), 404
    return jsonify(dict(row)), 200

# POST /resources — create
@app.route('/resources', methods=['POST'])
def create_resource():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # Validate required fields
    name = data.get('name')
    if not name:
        return jsonify({"error": "Missing name"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN")
        cursor = db.execute(
            "INSERT INTO resources (name, status) VALUES (?, 'active')",
            (name,)
        )
        resource_id = cursor.lastrowid
        db.execute("COMMIT")
        
        row = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        if "unique" in str(e).lower():
            return jsonify({"error": "Already exists"}), 409
        return jsonify({"error": "Constraint violation"}), 400

# PUT /resources/<id> — full update
@app.route('/resources/<int:resource_id>', methods=['PUT'])
def update_resource(resource_id):
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    db = get_db()
    try:
        db.execute("BEGIN")
        existing = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if existing is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        # Update all fields from request
        name = data.get('name', existing['name'])
        status = data.get('status', existing['status'])
        
        db.execute(
            "UPDATE resources SET name = ?, status = ? WHERE id = ?",
            (name, status, resource_id)
        )
        db.execute("COMMIT")
        
        row = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        return jsonify(dict(row)), 200
    except sqlite3.IntegrityError as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": "Constraint violation"}), 400

# DELETE /resources/<id>
@app.route('/resources/<int:resource_id>', methods=['DELETE'])
def delete_resource(resource_id):
    db = get_db()
    try:
        db.execute("BEGIN")
        existing = db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if existing is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
        db.execute("COMMIT")
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

### Redirect Patterns

When the spec requires redirects (e.g., URL shortener, task completion):

```python
from flask import redirect, url_for

# Redirect to another endpoint
@app.route('/short/<code>', methods=['GET'])
def redirect_short(code):
    db = get_db()
    row = db.execute("SELECT url FROM urls WHERE code = ?", (code,)).fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    return redirect(row['url'], code=302)  # or 301 for permanent

# Redirect after POST (PRG pattern)
@app.route('/tasks', methods=['POST'])
def create_task():
    # ... create task ...
    return redirect(url_for('get_task', task_id=task_id), code=303)
```

### Cascading Validation

When deleting or updating a parent must cascade to children:

```python
@app.route('/parents/<int:parent_id>', methods=['DELETE'])
def delete_parent(parent_id):
    db = get_db()
    try:
        db.execute("BEGIN")
        parent = db.execute("SELECT * FROM parents WHERE id = ?", (parent_id,)).fetchone()
        if parent is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Parent not found"}), 404
        
        # Cascade: delete children first
        db.execute("DELETE FROM children WHERE parent_id = ?", (parent_id,))
        db.execute("DELETE FROM parents WHERE id = ?", (parent_id,))
        db.execute("COMMIT")
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
```

### Counters and Aggregates

When the API tracks counts or computes aggregates:

```python
# Increment a counter atomically
@app.route('/tasks/<int:task_id>/complete', methods=['POST'])
def complete_task(task_id):
    db = get_db()
    try:
        db.execute("BEGIN")
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Task not found"}), 404
        
        if task['completed']:
            db.execute("ROLLBACK")
            return jsonify({"error": "Already completed"}), 400
        
        # Atomic update
        db.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
        db.execute("UPDATE stats SET completed_count = completed_count + 1")
        db.execute("COMMIT")
        
        return jsonify({"status": "completed"}), 200
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

# GET aggregate stats
@app.route('/stats', methods=['GET'])
def get_stats():
    db = get_db()
    row = db.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(completed) as completed,
            AVG(duration) as avg_duration
        FROM tasks
    """).fetchone()
    return jsonify(dict(row)), 200
```

## Operational Environment

When solving tasks in this family, you work across two separate filesystems:

**Author-workspace** (host tools: `read`, `write`, `edit`, `ls`)
- Contains: `skill/flask/SKILL.md`, `spec.yaml`, `train/v01/task.yaml`, `feedback/`
- Use workspace-relative paths: `skill/flask/SKILL.md`
- This is where you edit the Skill package

**Isolated `/app/` container** (`task_shell`)
- Contains: `solve.py`, database files, runtime artifacts
- Use absolute paths: `/app/solve.py`, `/app/bank.db`
- This is where you write and test the solution

The two filesystems are **not shared**. Files in `/app/` are not visible from the author-workspace, and vice versa. Always use the appropriate tool for the environment:
- To edit the Skill → host tools with workspace-relative paths
- To write/test solve.py → `task_shell` with `/app/` paths

## Persistence-Specific Patterns

### sqlite3 (raw)
- Use `isolation_level=None` for explicit transaction control
- Use `row_factory = sqlite3.Row` for column-name access
- Parameterize all queries with `?` placeholders (never string interpolation)
- **Use a relative path for the database file** (e.g., `DB_PATH = "bank.db"`), never `os.path.join(os.getcwd(), ...)` which locks the path at import time. Tests often open their own `sqlite3.connect("bank.db")` to verify state — both must resolve to the same file regardless of CWD changes between import and execution.
- Avoid `PRAGMA journal_mode=WAL` unless specifically needed — it creates additional files and can confuse test assertions that open separate connections

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
8. **Separate-connection visibility**: State written via Flask test client is visible from a separate `sqlite3.connect(path)` opened in the same process (tests often verify this way)
9. **Path resolution**: Database/file paths resolve correctly even if CWD changes between module import and test execution

## Common Pitfalls

1. **Forgetting `isolation_level=None`** with raw sqlite3 → implicit/explicit transaction conflict
2. **Returning before ROLLBACK** in error paths → partial state committed
3. **Not checking existence before mutation** → confusing IntegrityError instead of clean 404
4. **Not catching IntegrityError and mapping it to the expected 400/409 response** → raw database error leaked as 500
5. **Using `request.json` instead of `request.get_json(silent=True)`** → 400 on malformed JSON instead of controlled error
6. **Forgetting `row_factory`** → accessing rows by index instead of column name
7. **Non-idempotent setup** → duplicate seed data on repeated calls
8. **Mutating state before validation** → partial corruption on error
9. **Using `os.path.join(os.getcwd(), 'db.sqlite')` for database path** → absolute path locked at import time; test's separate `sqlite3.connect('db.sqlite')` resolves to a different file if CWD changed → "no such table" errors
10. **Enabling WAL journal mode unnecessarily** → creates `-wal` and `-shm` sidecar files; test connections opening the main DB file may not see uncommitted WAL data
