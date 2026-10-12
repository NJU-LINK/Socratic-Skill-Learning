---
name: flask
description: Build stateful Flask JSON services with atomic state transitions, validation, and persistence
---

# Flask Stateful Service Skill

Build Flask applications that implement JSON HTTP services with mutable domain state, atomic operations, and proper validation.

## Core Architecture Pattern

Every task in this family requires:
- A Flask app exported as `app` from `/app/solve.py`
- Multiple coupled endpoints that share mutable state
- Atomic state transitions with proper error handling
- JSON request/response contracts with validation

## Persistence Layer Patterns

### SQLite3 with Explicit Transactions (Most Common)

When using raw sqlite3 with explicit transaction control:

```python
import sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)

# Use relative path - resolves at connection time, not import time
DB_PATH = "bank.db"

def get_db():
    # isolation_level=None = autocommit mode, we control transactions explicitly
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn
```

**Critical gotcha:** Python's sqlite3 module has `isolation_level=""` by default (deferred mode), which auto-issues BEGIN before DML. If you also write explicit BEGIN, you get "cannot start a transaction within a transaction" errors.

**Solution:** Set `isolation_level=None` for autocommit mode, then control everything with explicit `BEGIN`/`COMMIT`/`ROLLBACK`.

### Atomic Operations Pattern

```python
@app.route("/operation", methods=["POST"])
def operation():
    conn = get_db()
    try:
        conn.execute("BEGIN")
        try:
            # Perform all operations
            # ...
            conn.execute("COMMIT")
            return jsonify(result), 200
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
```

### Idempotent Setup Pattern

For `/setup` or initialization endpoints that may be called multiple times:

```python
@app.route("/setup", methods=["GET"])
def setup():
    conn = get_db()
    try:
        # Idempotent table creation
        conn.execute("""
            CREATE TABLE IF NOT EXISTS table_name (
                id INTEGER PRIMARY KEY,
                field TEXT NOT NULL
            )
        """)
        
        # Idempotent seeding with INSERT OR IGNORE
        conn.execute("INSERT OR IGNORE INTO table_name (id, field) VALUES (1, 'value')")
        return jsonify({"status": "ok"}), 200
    finally:
        conn.close()
```

**Why INSERT OR IGNORE:** Works when id is PRIMARY KEY - skips if row exists, inserts if not. More robust than checking existence first.

## Validation Ordering Discipline

Validation must follow a strict layered sequence. Each layer protects the next:

1. **Parse envelope** — `get_json(silent=True)`, reject malformed/missing JSON → 400
2. **Extract required fields** — check presence of all required keys → 400
3. **Type & range validation** — `isinstance(amount, (int, float))`, `amount <= 0` → 400
4. **Cross-field constraints** — `from_id == to_id` → 400
5. **Resource existence** — query DB for resources → 404
6. **Business/state constraints** — insufficient balance, quota exceeded → 400
7. **Perform operation** — inside explicit transaction

**Why order matters:** Each layer ensures the next receives valid inputs. If you skip type validation and go straight to cross-field checks, a request with `amount: "hello"` might pass the cross-field check but then crash on the DB query. If you check balance before existence, you crash on a `None` row. The universal rule: **type/range → cross-field → existence → state**. Always validate that inputs are well-formed before you validate that they're semantically correct.

**Boolean edge case:** In Python, `isinstance(True, int)` returns `True` because `bool` is a subclass of `int`. Always explicitly reject booleans for numeric fields:

```python
# Wrong: allows True/False as valid numbers
if not isinstance(amount, (int, float)) or amount <= 0:
    return error

# Correct: reject booleans first
if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
    return error
```

## Validation and Error Handling Pattern

### Required Field Validation

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid JSON"}), 400

field1 = data.get("field1")
field2 = data.get("field2")

if field1 is None or field2 is None:
    return jsonify({"error": "Missing required fields"}), 400
```

### Type and Range Validation

```python
# Numeric validation with boolean guard
# isinstance(True, int) is True in Python, so reject booleans explicitly
if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
    return jsonify({"error": "Amount must be positive"}), 400
```

### Cross-Field Constraints

```python
# Check after type validation: inputs are well-formed before checking semantics
if from_id == to_id:
    return jsonify({"error": "Cannot operate on same resource"}), 400
```

### Resource Existence Validation

```python
resource = conn.execute("SELECT * FROM table WHERE id = ?", (id,)).fetchone()
if resource is None:
    return jsonify({"error": "Resource not found"}), 404
```

### State Constraint Validation

```python
if resource["balance"] < amount:
    return jsonify({"error": "Insufficient balance"}), 400
```

## Error Response Contract

Always return JSON errors with appropriate HTTP status codes:
- **400 Bad Request:** Missing fields, invalid types/ranges, constraint violations
- **404 Not Found:** Non-existent resources
- **409 Conflict:** State conflicts (if specified)
- **500 Internal Server Error:** Unexpected failures

```python
return jsonify({"error": "Error message"}), status_code
```

## Database Connection Management

Always close connections in a finally block:

```python
conn = get_db()
try:
    # Operations
finally:
    conn.close()
```

Or use context managers if preferred.

## Testing Pattern

Tests use Flask's test client:

```python
from solve import app

def test_endpoint():
    app.config['TESTING'] = True
    with app.test_client() as client:
        # Setup
        client.get('/setup')
        
        # Test operation
        response = client.post('/endpoint', json={...})
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['field'] == expected_value
```

## Common Pitfalls

1. **Transaction conflicts:** Don't mix Python's auto-transaction with explicit BEGIN/COMMIT. Use `isolation_level=None` for explicit control.

2. **Non-idempotent setup:** Use `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` to make setup safe to call multiple times.

3. **Missing error handling:** Always validate inputs, check resource existence, and verify state constraints before operations. Follow the validation ordering discipline.

4. **Connection leaks:** Always close database connections in finally blocks.

5. **Atomicity violations:** Wrap multi-step operations in explicit transactions with proper rollback on error.

6. **Boolean-as-number trap:** `isinstance(True, int)` is `True` in Python. Always check `isinstance(amount, bool)` before `isinstance(amount, (int, float))` for numeric fields.

7. **Validation ordering violations:** Don't check resource existence before type validation — garbage types will crash DB queries. Don't check balance before existence — `None` rows crash attribute access.

8. **Database path resolution at import time:** When a task says "SQLite3 `bank.db` in the current working directory," always use a **bare relative path** `"bank.db"`, never `os.path.join(os.getcwd(), "bank.db")`. The test client runs in the same Python process as the test harness, and `os.getcwd()` at import time may not match cwd when the test actually executes. If you freeze the path at import time, the app writes to one location while the test reads from another → "no such table" errors. Relative paths resolve at connection time, when both app and test share the same cwd.

## Adaptation Guide

When facing a new task in this family:

1. **Identify the resource model:** What entities are being managed? What are their fields and constraints?

2. **Choose persistence model:** sqlite3, flask_sqlalchemy, in_memory, file_manifest, or jsonl? Adapt connection/query patterns accordingly.

3. **Map endpoint contracts:** What routes, methods, request/response schemas are specified?

4. **Identify state transitions:** What operations need atomicity? What invariants must be maintained?

5. **Extract validation rules:** What fields are required? What types/ranges? What constraints?

6. **Apply patterns:** Use the atomic operations, validation, and error handling patterns above.

The core architecture (Flask app, JSON service, atomic operations, validation) is invariant. The resource model, persistence mechanism, and specific endpoints vary by task.

## Process Patterns for Robust Implementation

These meta-lessons emerged from real failures and corrections. They apply across the entire family:

### 1. Test Under Harness Conditions, Not Just in Isolation

The `os.getcwd()` bug only manifested when external tests connected directly to the database. HTTP-only tests passed, but direct DB queries failed.

**Rule:** Always simulate the test harness's behavior. If the task says "tests will query the database directly," write tests that do exactly that — don't just check HTTP responses.

### 2. Resolve Resources at Use-Time, Not Import-Time

Module-level constants like `DB_PATH = os.path.join(os.getcwd(), "bank.db")` are evaluated once at import. If the test harness changes cwd between import and execution, the app and test see different files.

**Rule:** When a task says "file in the current working directory," use a bare relative path. This applies to database paths, config files, log files — anything that might differ between module load and request handling.

### 3. Internal Consistency Between Documentation and Code

The validation ordering fix showed that when docs say one thing and code does another, both are wrong in practice. The SKILL.md said "type/range before cross-field," but the code had them reversed.

**Rule:** After writing code, verify it matches the documented patterns. If the skill says "validate types before cross-field constraints," the code must do exactly that. Inconsistency is a bug.

### 4. Edge Cases Are Systematic, Not Random

Boolean subclassing (`isinstance(True, int)` is `True`), empty JSON bodies, same-account transfers — these aren't random gotchas. Test suites probe these edge cases systematically because they represent common failure modes.

**Rule:** For every validation layer, ask: "What edge cases could bypass this?" Type checks must reject booleans. Existence checks must handle `None`. Range checks must reject zero and negatives. Think like a test writer.

### 5. Validate Before You Operate, Operate Before You Respond

The validation ordering discipline (envelope → presence → type → cross-field → existence → state → operation) ensures each layer receives valid inputs. The atomic transaction pattern ensures operations either fully succeed or fully fail.

**Rule:** Never mix validation and operation. Validate everything first, then perform the operation atomically, then return the response. This prevents partial updates on validation failures.

### 6. Close Resources in Finally Blocks

Database connections, file handles, network sockets — if you open it, close it in a `finally` block. Connection leaks cause subtle failures in long-running tests.

**Rule:** Every `get_db()` or `open()` call must have a corresponding `finally: conn.close()` or `finally: f.close()`. No exceptions.

### 7. Make Setup Idempotent

Tests may call `/setup` multiple times. `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` ensure setup is safe to repeat. Non-idempotent setup causes "table already exists" or duplicate data errors.

**Rule:** Every setup/initialization endpoint must be safe to call multiple times. Use `IF NOT EXISTS` for DDL, `INSERT OR IGNORE` or existence checks for seed data.

### 8. Use Explicit Transactions for Multi-Step Operations

Python's sqlite3 auto-transaction mode conflicts with explicit `BEGIN`/`COMMIT`. Set `isolation_level=None` for autocommit mode, then control transactions manually. This prevents "cannot start a transaction within a transaction" errors.

**Rule:** For any operation that touches multiple tables or requires atomicity, use explicit transactions with `isolation_level=None`. Always `BEGIN`, `COMMIT`, and `ROLLBACK` explicitly.

These process patterns are technology-agnostic. They apply whether you're using sqlite3, flask_sqlalchemy, in-memory dicts, or JSONL files. The specific implementation varies, but the methodology is invariant.
