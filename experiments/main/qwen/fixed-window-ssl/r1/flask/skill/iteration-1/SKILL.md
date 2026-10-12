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

When you encounter a non-sqlite3 variant, ask three questions:
1. **What replaces `BEGIN`/`COMMIT`/`ROLLBACK`?** (SQLAlchemy session, file locking, or nothing for in-memory)
2. **What replaces `CREATE TABLE IF NOT EXISTS`?** (`db.create_all()`, `os.makedirs`, dict initialization, or file creation)
3. **What replaces `INSERT OR REPLACE` for idempotent seeding?** (SQLAlchemy `merge()`, dict `setdefault()`, file existence check, or JSONL line deduplication)

### sqlite3 (v01 pattern)

**Setup**: `CREATE TABLE IF NOT EXISTS` + `INSERT OR REPLACE`
**Transactions**: Explicit `BEGIN`/`COMMIT`/`ROLLBACK`
**Connection lifecycle**: `g` object + `teardown_appcontext`
**Critical**: `isolation_level=None` required to prevent auto-BEGIN conflicts

### flask_sqlalchemy

**Setup**: `db.create_all()` + `db.session.merge()` for idempotent seeding
**Transactions**: `db.session.commit()` / `db.session.rollback()`
**Connection lifecycle**: Flask-SQLAlchemy manages connections per request automatically

```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///your_database.db'
db = SQLAlchemy(app)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String, nullable=False)
    balance = db.Column(db.Float, nullable=False)

@app.route('/setup')
def setup():
    db.create_all()
    # Idempotent seeding with merge()
    alice = Account(id=1, owner='Alice', balance=100.0)
    bob = Account(id=2, owner='Bob', balance=50.0)
    db.session.merge(alice)
    db.session.merge(bob)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route('/transfer', methods=['POST'])
def transfer():
    try:
        # SQLAlchemy session manages transactions
        sender = Account.query.get(from_id)
        if sender is None:
            return jsonify({"error": "Account not found"}), 404
        
        if sender.balance < amount:
            return jsonify({"error": "Insufficient balance"}), 400
        
        sender.balance -= amount
        receiver.balance += amount
        
        db.session.commit()
        return jsonify({...}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
```

**Key differences from sqlite3**:
- No explicit `BEGIN` — SQLAlchemy session manages transaction boundaries
- `db.session.merge()` replaces `INSERT OR REPLACE` for idempotent seeding
- `db.session.rollback()` on error instead of explicit `ROLLBACK`
- No `isolation_level` concern — SQLAlchemy handles it

### in_memory

**Setup**: Dict/list initialization in module scope or `g`
**Transactions**: No transactions needed (single-threaded test client)
**Connection lifecycle**: Module-level dict or `g` dict

```python
from flask import Flask, jsonify, request

app = Flask(__name__)

# Module-level state
accounts = {}
transactions = []
transaction_counter = 0

@app.route('/setup')
def setup():
    global accounts, transactions, transaction_counter
    # Idempotent: reset to initial state
    accounts = {
        1: {'id': 1, 'owner': 'Alice', 'balance': 100.0},
        2: {'id': 2, 'owner': 'Bob', 'balance': 50.0}
    }
    transactions = []
    transaction_counter = 0
    return jsonify({"status": "ok"})

@app.route('/transfer', methods=['POST'])
def transfer():
    global transaction_counter
    
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    from_id = data.get('from_id')
    to_id = data.get('to_id')
    amount = data.get('amount')
    
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    
    # No transaction needed — direct state manipulation
    if from_id not in accounts:
        return jsonify({"error": "Account not found"}), 404
    
    if to_id not in accounts:
        return jsonify({"error": "Account not found"}), 404
    
    sender = accounts[from_id]
    receiver = accounts[to_id]
    
    if sender['balance'] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    sender['balance'] -= amount
    receiver['balance'] += amount
    
    transaction_counter += 1
    transactions.append({
        'id': transaction_counter,
        'from_id': from_id,
        'to_id': to_id,
        'amount': amount
    })
    
    return jsonify({
        "sender": {"id": sender['id'], "balance": sender['balance']},
        "receiver": {"id": receiver['id'], "balance": receiver['balance']},
        "transaction_id": transaction_counter
    }), 200
```

**Key differences from sqlite3**:
- No database connection management
- No transactions — state is manipulated directly
- Fastest option; state lost on process exit
- Idempotency via direct dict reassignment

### file_manifest

**Setup**: Create file + write JSON manifest
**Transactions**: File locking or write-then-rename for atomicity
**Connection lifecycle**: Open/close per request or `g`

```python
import json
import os
import tempfile
from flask import Flask, jsonify, request

app = Flask(__name__)
MANIFEST_PATH = 'manifest.json'

def load_manifest():
    """Load state from manifest file."""
    if not os.path.exists(MANIFEST_PATH):
        return {'accounts': {}, 'transactions': [], 'next_id': 1}
    with open(MANIFEST_PATH, 'r') as f:
        return json.load(f)

def save_manifest(data):
    """Atomically save state to manifest file using write-then-rename."""
    # Write to temporary file first
    fd, temp_path = tempfile.mkstemp(dir='.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        # Atomic rename
        os.rename(temp_path, MANIFEST_PATH)
    except:
        os.unlink(temp_path)
        raise

@app.route('/setup')
def setup():
    # Idempotent: reset to initial state
    data = {
        'accounts': {
            '1': {'id': 1, 'owner': 'Alice', 'balance': 100.0},
            '2': {'id': 2, 'owner': 'Bob', 'balance': 50.0}
        },
        'transactions': [],
        'next_id': 1
    }
    save_manifest(data)
    return jsonify({"status": "ok"})

@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    from_id = str(data.get('from_id'))
    to_id = str(data.get('to_id'))
    amount = data.get('amount')
    
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    
    # Load current state
    manifest = load_manifest()
    
    if from_id not in manifest['accounts']:
        return jsonify({"error": "Account not found"}), 404
    
    if to_id not in manifest['accounts']:
        return jsonify({"error": "Account not found"}), 404
    
    sender = manifest['accounts'][from_id]
    receiver = manifest['accounts'][to_id]
    
    if sender['balance'] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Perform transfer
    sender['balance'] -= amount
    receiver['balance'] += amount
    
    transaction_id = manifest['next_id']
    manifest['next_id'] += 1
    manifest['transactions'].append({
        'id': transaction_id,
        'from_id': int(from_id),
        'to_id': int(to_id),
        'amount': amount
    })
    
    # Atomically save
    save_manifest(manifest)
    
    return jsonify({
        "sender": {"id": sender['id'], "balance": sender['balance']},
        "receiver": {"id": receiver['id'], "balance": receiver['balance']},
        "transaction_id": transaction_id
    }), 200
```

**Key differences from sqlite3**:
- No database — state stored in JSON file
- Atomicity via write-then-rename pattern (not SQL transactions)
- Must load entire state, modify, then save
- JSON keys must be strings (not integers)

### jsonl

**Setup**: Create file + write initial lines
**Transactions**: Append-only writes; read-all-then-rewrite for updates
**Connection lifecycle**: Open/append per request

```python
import json
import os
from flask import Flask, jsonify, request

app = Flask(__name__)
DATA_FILE = 'data.jsonl'

def read_all_records():
    """Read all records from JSONL file."""
    if not os.path.exists(DATA_FILE):
        return []
    records = []
    with open(DATA_FILE, 'r') as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def write_all_records(records):
    """Rewrite entire JSONL file."""
    with open(DATA_FILE, 'w') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')

@app.route('/setup')
def setup():
    # Idempotent: reset to initial state
    initial_accounts = [
        {'type': 'account', 'id': 1, 'owner': 'Alice', 'balance': 100.0},
        {'type': 'account', 'id': 2, 'owner': 'Bob', 'balance': 50.0}
    ]
    write_all_records(initial_accounts)
    return jsonify({"status": "ok"})

@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    from_id = data.get('from_id')
    to_id = data.get('to_id')
    amount = data.get('amount')
    
    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    
    # Read all records
    records = read_all_records()
    
    # Find accounts
    accounts = [r for r in records if r['type'] == 'account']
    sender = next((a for a in accounts if a['id'] == from_id), None)
    receiver = next((a for a in accounts if a['id'] == to_id), None)
    
    if sender is None:
        return jsonify({"error": "Account not found"}), 404
    
    if receiver is None:
        return jsonify({"error": "Account not found"}), 404
    
    if sender['balance'] < amount:
        return jsonify({"error": "Insufficient balance"}), 400
    
    # Update accounts in records
    sender['balance'] -= amount
    receiver['balance'] += amount
    
    # Append transaction record
    transactions = [r for r in records if r['type'] == 'transaction']
    transaction_id = len(transactions) + 1
    records.append({
        'type': 'transaction',
        'id': transaction_id,
        'from_id': from_id,
        'to_id': to_id,
        'amount': amount
    })
    
    # Rewrite entire file
    write_all_records(records)
    
    return jsonify({
        "sender": {"id": sender['id'], "balance": sender['balance']},
        "receiver": {"id": receiver['id'], "balance": receiver['balance']},
        "transaction_id": transaction_id
    }), 200
```

**Key differences from sqlite3**:
- Append-only format; updates require full rewrite
- No transactions — atomicity via complete file rewrite
- Good for append-only operations (logs, events)
- Must read all records to find/update specific ones
- Less efficient for large datasets

### Choosing the Right Persistence Model

The task spec will indicate which persistence model to use. If not specified:
- **sqlite3**: Default choice for structured data with relationships
- **flask_sqlalchemy**: When ORM features or complex queries are needed
- **in_memory**: For simple demos or when persistence isn't required
- **file_manifest**: When state must survive restarts but database is overkill
- **jsonl**: For append-only logs or event streams

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
