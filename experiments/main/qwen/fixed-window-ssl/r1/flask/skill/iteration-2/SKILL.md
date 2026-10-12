---
name: flask
description: Build stateful JSON HTTP services with Flask, SQLite3, and atomic state transitions. Covers database lifecycle, idempotency strategies, validation ordering, and transaction patterns for bank transfers, task queues, note managers, cart systems, and similar resource-management APIs.
---

# Flask Stateful Service Skill

This skill covers the construction of JSON HTTP services that manage mutable domain state through Flask and SQLite3. The service is evaluated via Flask's test client without a live network server.

## Core Architecture Pattern

Every case in this family follows the same structural pattern:

1. **Flask app object** named `app` exported from `/app/solve.py`
2. **SQLite3 database** in the current working directory (filename specified in task)
3. **Setup endpoint** that creates tables and seeds initial data (idempotent)
4. **State-manipulating endpoints** that perform atomic operations with proper validation
5. **Per-request database connection** using Flask's `g` object with teardown cleanup

### Database Connection Lifecycle

```python
from flask import Flask, g
import sqlite3

app = Flask(__name__)
DB_PATH = 'your_database.db'

def get_db():
    """Get a database connection for the current request context."""
    if 'db' not in g:
        # isolation_level=None: autocommit mode - we manage transactions explicitly
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row  # Enable dict-like access
        g.db.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    return g.db

@app.teardown_appcontext
def close_db(exception):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Why this pattern matters:**
- `g` is request-scoped, so each request gets its own connection
- `teardown_appcontext` ensures cleanup even if exceptions occur
- `row_factory = sqlite3.Row` enables `row['column_name']` access
- WAL mode improves concurrent read performance
- `isolation_level=None` puts connection in autocommit mode — sqlite3 won't auto-manage transactions

**Critical: `isolation_level=None` explained:**

Python's `sqlite3.connect()` defaults to `isolation_level=""` (DEFERRED mode). In this mode, sqlite3 **automatically issues `BEGIN`** before any DML statement (INSERT, UPDATE, DELETE, REPLACE) if no transaction is already open. When you also call `db.execute("BEGIN")` explicitly, conflicts arise:

1. If your explicit `BEGIN` runs first: sqlite3 sees a transaction is open and doesn't auto-BEGIN. Works fine.
2. If any DML leaks before your `BEGIN` (e.g., a PRAGMA or accidental query): sqlite3 auto-BEGINs, then your explicit `BEGIN` fails with `"cannot start a transaction within a transaction"`.

Setting `isolation_level=None` puts the connection in **autocommit mode** — sqlite3 won't manage transactions for you at all. Your explicit `BEGIN`/`COMMIT`/`ROLLBACK` become the sole transaction controllers.

**Behavior with `isolation_level=None`:**
- Every DML statement auto-commits unless wrapped in explicit `BEGIN`/`COMMIT`
- `/setup` operations (CREATE TABLE, INSERT OR REPLACE) auto-commit individually — correct since they're independent
- `/transfer` wraps read-check-update in explicit `BEGIN`/`COMMIT` — correct for atomicity
- Eliminates the entire class of "nested transaction" bugs

This is essential for this family because every case uses explicit transaction management.

## Idempotency Strategies for /setup

The `/setup` endpoint must be idempotent, but "idempotent" has multiple valid interpretations. Choose based on test behavior:

### Pattern 1: Safe Hybrid (Recommended Default)

```python
@app.route('/setup', methods=['GET'])
def setup():
    db = get_db()
    
    # Create tables if they don't exist
    # With isolation_level=None, each statement auto-commits individually
    db.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL,
            balance REAL NOT NULL CHECK(balance >= 0)
        )
    ''')
    
    # Reset seed rows to initial values without destroying extra data
    db.execute("INSERT OR REPLACE INTO accounts (id, owner, balance) VALUES (1, 'Alice', 100.0)")
    db.execute("INSERT OR REPLACE INTO accounts (id, owner, balance) VALUES (2, 'Bob', 50.0)")
    
    return jsonify({"status": "ok"})
```

**When to use:**
- Tests call `/setup` before each test case and expect pristine seed data
- The API might create additional resources during tests (preserve them)
- You want a single pattern that works in most scenarios

**Behavior:**
- First call: creates tables and inserts seed data
- Subsequent calls: resets seed rows to initial values, preserves extra rows
- Satisfies both "reset-to-initial" and "skip-if-populated" interpretations

### Pattern 2: Skip-if-Populated

```python
existing = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
if existing == 0:
    # With isolation_level=None, each INSERT auto-commits
    db.execute("INSERT INTO accounts (id, owner, balance) VALUES (1, 'Alice', 100.0)")
    db.execute("INSERT INTO accounts (id, owner, balance) VALUES (2, 'Bob', 50.0)")
```

**When to use:**
- Tests call `/setup` once at the start
- Modified balances should persist across `/setup` calls
- Rare in benchmarks (makes tests order-dependent)

### Pattern 3: Full Reset

```python
# With isolation_level=None, each statement auto-commits individually
db.execute("DROP TABLE IF EXISTS accounts")
db.execute("DROP TABLE IF EXISTS transactions")
db.execute("CREATE TABLE accounts ...")
db.execute("CREATE TABLE transactions ...")
db.execute("INSERT INTO accounts ...")
```

**When to use:**
- Tests expect complete state wipe (including extra resources)
- Explicit "reset" semantics in the spec
- Use cautiously: destroys legitimate test-created data

## Validation Ordering

When multiple error conditions are simultaneously true, the order of validation determines which error the test sees. Follow this sequence:

### Standard Validation Order

1. **JSON parsing** (400): `request.get_json(silent=True)` returns None
2. **Required fields** (400): Missing mandatory fields in request body
3. **Type/range validation** (400): Invalid types, negative amounts, out-of-range values
4. **Business rules** (400): Domain-specific constraints (e.g., "cannot transfer to same account")
5. **Resource existence** (404): Referenced resources don't exist
6. **Business constraints** (400): State-dependent checks (e.g., "insufficient balance")

**Why this order:**
- Cheap/structural checks before expensive/stateful ones
- Matches the spec's typical listing order
- Avoids unnecessary database queries for obviously invalid requests

### Example: Transfer Validation

```python
@app.route('/transfer', methods=['POST'])
def transfer():
    # 1. Validate JSON
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # 2. Validate required fields
    from_id = data.get('from_id')
    to_id = data.get('to_id')
    amount = data.get('amount')
    
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    # 3. Type/range validation
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    
    # 4. Business rule
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    
    db = get_db()
    
    # 5. Resource existence + 6. Business constraint (inside transaction)
    try:
        db.execute("BEGIN")
        
        sender = db.execute("SELECT * FROM accounts WHERE id = ?", (from_id,)).fetchone()
        if sender is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Account not found"}), 404
        
        receiver = db.execute("SELECT * FROM accounts WHERE id = ?", (to_id,)).fetchone()
        if receiver is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Account not found"}), 404
        
        if sender['balance'] < amount:
            db.execute("ROLLBACK")
            return jsonify({"error": "Insufficient balance"}), 400
        
        # Perform operation...
        db.execute("COMMIT")
        return jsonify({...}), 200
        
    except Exception as e:
        db.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500
```

## Atomic Transactions

State-manipulating endpoints must use explicit SQL transactions to ensure atomicity:

```python
try:
    db.execute("BEGIN")
    
    # Read current state
    resource = db.execute("SELECT * FROM resources WHERE id = ?", (id,)).fetchone()
    
    # Validate business constraints
    if resource['balance'] < amount:
        db.execute("ROLLBACK")
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Perform updates
    db.execute("UPDATE resources SET balance = ? WHERE id = ?", (new_balance, id))
    
    # Record the operation
    cursor = db.execute("INSERT INTO operations (...) VALUES (...)", (...))
    operation_id = cursor.lastrowid
    
    db.execute("COMMIT")
    
    return jsonify({
        "resource": {...},
        "operation_id": operation_id
    }), 200
    
except Exception as e:
    db.execute("ROLLBACK")
    return jsonify({"error": str(e)}), 500
```

**Critical rules:**
- Always `BEGIN` before reading state you'll modify
- `ROLLBACK` before returning error responses inside the transaction
- `COMMIT` only after all operations succeed
- Wrap in try/except to catch unexpected errors and rollback
- Use `cursor.lastrowid` to get auto-increment IDs

## Response Patterns

### Success Response

Return the updated state and any generated IDs:

```python
return jsonify({
    "sender": {"id": 1, "balance": 75.0},
    "receiver": {"id": 2, "balance": 75.0},
    "transaction_id": 42
}), 200
```

### Error Response

Return a JSON object with an "error" key and appropriate HTTP status:

```python
return jsonify({"error": "Insufficient balance"}), 400
```

**Common status codes:**
- 200: Success
- 400: Client error (invalid input, business rule violation)
- 404: Resource not found
- 500: Server error (unexpected exception)

## Testing Your Solution

Before submission, verify:

1. **Idempotency**: Call `/setup` multiple times, check behavior matches spec
2. **Validation order**: Test with multiple simultaneous errors, check which error "wins"
3. **Atomicity**: Perform a failing operation, verify state is unchanged
4. **Sequential operations**: Perform multiple successful operations, verify cumulative state
5. **Edge cases**: Zero amounts, negative amounts, missing fields, non-existent resources

```python
# Test idempotency
client.get('/setup')
client.post('/transfer', json={'from_id': 1, 'to_id': 2, 'amount': 25.0})
client.get('/setup')  # Should reset balances with safe hybrid pattern

# Test atomicity
client.post('/transfer', json={'from_id': 1, 'to_id': 2, 'amount': 99999})  # Should fail
resp = client.post('/transfer', json={'from_id': 1, 'to_id': 2, 'amount': 1.0})  # Should succeed
# Verify balances are correct after failed + successful operation
```

## Task Analysis Framework

When you encounter a new task in this family, systematically extract requirements before writing code:

### Step 1: Identify the Resource Model

Read the spec and answer:
- **What entities exist?** (accounts, tasks, notes, cart items, URLs, etc.)
- **What are their fields?** Extract from spec: "Account has id, owner, balance"
- **What are the relationships?** (one-to-many, many-to-many, etc.)
- **What constraints exist?** (unique, not null, check constraints, foreign keys)

**Example extraction:**
```
Spec: "accounts(id INTEGER PRIMARY KEY, owner TEXT NOT NULL, balance REAL NOT NULL CHECK(balance >= 0))"
→ Entity: accounts
→ Fields: id (INTEGER PRIMARY KEY), owner (TEXT NOT NULL), balance (REAL NOT NULL with CHECK >= 0)
→ Constraints: balance must be non-negative
```

### Step 2: Identify the Persistence Model

Look for explicit indicators in the spec:
- **sqlite3**: "SQLite3", "bank.db", "CREATE TABLE", "SQL transactions"
- **flask_sqlalchemy**: "Flask-SQLAlchemy", "db.Model", "SQLAlchemy"
- **in_memory**: "in-memory", "no persistence", "process-local"
- **file_manifest**: "JSON file", "manifest.json", "file-based"
- **jsonl**: "JSONL", "append-only", "log file"

If not specified, default to **sqlite3** (most common in this family).

### Step 3: Identify Endpoint Contracts

Extract from spec:
- **Paths**: "/setup", "/transfer", "/tasks", etc.
- **Methods**: GET, POST, PUT, DELETE
- **Request format**: JSON body fields, query parameters
- **Response format**: Success schema, error schema
- **Status codes**: 200, 400, 404, etc.

**Example extraction:**
```
Spec: "POST /transfer accepts JSON body {from_id, to_id, amount, description}"
→ Path: /transfer
→ Method: POST
→ Request: JSON with from_id (required), to_id (required), amount (required), description (optional)
→ Response: {sender: {id, balance}, receiver: {id, balance}, transaction_id}
```

### Step 4: Identify State Transition Semantics

Answer:
- **What operations modify state?** (transfers, CRUD, checkout, etc.)
- **What are the preconditions?** (sufficient balance, resource exists, etc.)
- **What are the postconditions?** (balances updated, transaction recorded, etc.)
- **What must be atomic?** (read-check-update sequences)

**Example extraction:**
```
Spec: "Must use SQL transactions (BEGIN/COMMIT/ROLLBACK) for atomicity"
→ Operations: transfer (debit sender, credit receiver, record transaction)
→ Preconditions: accounts exist, sufficient balance
→ Postconditions: balances updated, transaction recorded
→ Atomicity: entire transfer must succeed or fail together
```

### Step 5: Identify Validation and Failure Behavior

Extract error conditions from spec:
- **Missing fields**: "Missing from_id, to_id, or amount: 400"
- **Invalid values**: "Amount <= 0: 400"
- **Business rules**: "from_id equals to_id: 400"
- **Resource existence**: "Non-existent account: 404"
- **State constraints**: "Insufficient balance: 400"

**Map to validation order:**
1. JSON parsing → 400
2. Required fields → 400
3. Type/range → 400
4. Business rules → 400
5. Resource existence → 404
6. State constraints → 400

### Step 6: Map to Skill Patterns

Once you've extracted requirements, map them to the skill's patterns:
- **Persistence model** → Use the appropriate section (sqlite3, flask_sqlalchemy, etc.)
- **Setup endpoint** → Apply idempotency strategy (safe hybrid default)
- **State-manipulating endpoints** → Apply validation ordering + atomic transactions
- **Error responses** → Use standard format with spec's exact error messages

**Example mapping:**
```
Task: Bank transfer with sqlite3
→ Persistence: sqlite3 section
→ Setup: CREATE TABLE IF NOT EXISTS + INSERT OR REPLACE
→ Transfer: Validate (JSON → fields → amount > 0 → same account) → BEGIN → check existence → check balance → UPDATE → INSERT → COMMIT
→ Errors: Use exact messages from spec
```

## Adaptation to Different Resource Models

This skill applies to any resource-management API:

- **Bank transfers**: accounts, transactions, balance checks
- **Task queues**: tasks, status transitions, completion tracking
- **Note managers**: notes, CRUD operations, ownership
- **Cart systems**: items, quantities, checkout validation
- **URL shorteners**: mappings, uniqueness constraints, redirects

The core patterns (database lifecycle, idempotency, validation ordering, atomic transactions) remain the same; only the resource schema and business rules change.

## Persistence Model Adaptation

The spec defines five persistence models. The architectural patterns (idempotency strategies, validation ordering, state transition semantics, error response format) are **identical across all five**. Only the mechanical layer changes.

### Three Questions for Any Persistence Model

When you encounter a non-sqlite3 variant, ask:

1. **What replaces `BEGIN`/`COMMIT`/`ROLLBACK`?**
   - sqlite3: Explicit SQL transactions
   - flask_sqlalchemy: `db.session.commit()` / `db.session.rollback()`
   - in_memory: Nothing (single-threaded, direct manipulation)
   - file_manifest: Write-then-rename for atomicity
   - jsonl: Full file rewrite

2. **What replaces `CREATE TABLE IF NOT EXISTS`?**
   - sqlite3: SQL DDL
   - flask_sqlalchemy: `db.create_all()`
   - in_memory: Dict/list initialization
   - file_manifest: File creation
   - jsonl: File creation

3. **What replaces `INSERT OR REPLACE` for idempotent seeding?**
   - sqlite3: `INSERT OR REPLACE`
   - flask_sqlalchemy: `db.session.merge()`
   - in_memory: Direct dict assignment
   - file_manifest: File overwrite
   - jsonl: File rewrite

### sqlite3 (v01 pattern - proven)

**Setup**: `CREATE TABLE IF NOT EXISTS` + `INSERT OR REPLACE`
**Transactions**: Explicit `BEGIN`/`COMMIT`/`ROLLBACK`
**Connection lifecycle**: `g` object + `teardown_appcontext`
**Critical**: `isolation_level=None` required to prevent auto-BEGIN conflicts

This is the default and most thoroughly tested pattern. See the Core Architecture Pattern section for complete implementation.

### flask_sqlalchemy

**Key differences from sqlite3**:
- No explicit `BEGIN` — SQLAlchemy session manages transaction boundaries
- `db.session.merge()` replaces `INSERT OR REPLACE` for idempotent seeding
- `db.session.rollback()` on error instead of explicit `ROLLBACK`
- No `isolation_level` concern — SQLAlchemy handles it
- Use `db.Column` definitions instead of SQL DDL

**When to use**: Spec mentions "Flask-SQLAlchemy", "db.Model", or "SQLAlchemy"

### in_memory

**Key differences from sqlite3**:
- No database connection management
- No transactions — state is manipulated directly
- Fastest option; state lost on process exit
- Idempotency via direct dict reassignment
- Use module-level dicts or `g` for state

**When to use**: Spec mentions "in-memory", "no persistence", or "process-local"

### file_manifest

**Key differences from sqlite3**:
- No database — state stored in JSON file
- Atomicity via write-then-rename pattern (not SQL transactions)
- Must load entire state, modify, then save
- JSON keys must be strings (not integers)
- Use `tempfile.mkstemp()` + `os.rename()` for atomic writes

**When to use**: Spec mentions "JSON file", "manifest.json", or "file-based"

### jsonl

**Key differences from sqlite3**:
- Append-only format; updates require full rewrite
- No transactions — atomicity via complete file rewrite
- Good for append-only operations (logs, events)
- Must read all records to find/update specific ones
- Less efficient for large datasets

**When to use**: Spec mentions "JSONL", "append-only", or "log file"

### Choosing the Right Persistence Model

The task spec will indicate which persistence model to use. Look for explicit keywords (see "When to use" above). If not specified, default to **sqlite3** (most common in this family).

## Common Pitfalls

1. **Forgetting `isolation_level=None`**: sqlite3's default auto-BEGIN conflicts with explicit `BEGIN`, causing "cannot start a transaction within a transaction" errors
2. **Forgetting `teardown_appcontext`**: Database connections leak
3. **Not using `BEGIN`**: Operations aren't atomic, partial updates corrupt state
4. **Wrong validation order**: Tests see unexpected error messages
5. **Skip-if-populated when reset is expected**: Tests fail due to stale state
6. **Not rolling back on error**: Transaction state becomes inconsistent
7. **Forgetting `row_factory = sqlite3.Row`**: Can't access columns by name
8. **Hardcoding DB path**: Must use current working directory, not absolute path
9. **Calling `db.commit()` in setup with `isolation_level=None`**: Harmless no-op but misleading — each statement already auto-commits
