---
name: flask
description: >
  Build Flask JSON HTTP services with shared mutable state, multiple
  coupled endpoints, and correct persistence/transaction semantics.
  Covers SQLite3, Flask-SQLAlchemy, in-memory, JSONL, and file-manifest
  backends; idempotent setup; atomic state transitions; validation with
  JSON error responses; and the flask test-client contract.
---

# Flask Stateful JSON Service

## 1 — Implementation Contract (invariant)

Every case in this family requires:

1. A file at **`/app/solve.py`** (no Markdown fences around the code).
2. A module-level Flask application object named **`app`**.
3. Evaluation imports it as `from solve import app` and drives it through
   `app.test_client()` — **no live network server** is started.
4. All request/response bodies are JSON (`Content-Type: application/json`).
5. The service has **multiple behaviorally coupled endpoints** sharing
   mutable domain state (not a single stateless route).
6. **File paths (DB, JSONL, etc.) must be anchored to `__file__`**, not
   to `os.getcwd()`. pytest may run from any CWD; relative paths will
   silently create/find the wrong file. See §2.1.

---

## 2 — Persistence Backends

The task specifies which backend to use. Adapt accordingly.

### 2.1  Raw SQLite3

```python
import sqlite3, os

# CRITICAL: anchor the DB file to solve.py's directory, NOT to os.getcwd().
# pytest may run from /tests or any other CWD; os.getcwd() would create
# the DB there while the test harness connects to "bank.db" from /app.
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "bank.db"                              # adjust per task
DB_PATH = os.path.join(DB_DIR, DB_NAME)

def get_db():
    """Return a connection with manual transaction control."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit off
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn
```

- **Never use `os.getcwd()`** for the DB path. `__file__`-anchored paths
  survive CWD changes during test execution.
- Use `isolation_level=None` so **you** control `BEGIN`/`COMMIT`/`ROLLBACK`.
- Always wrap multi-statement mutations in an explicit transaction:
  ```python
  conn.execute("BEGIN")
  try:
      # … mutations …
      conn.execute("COMMIT")
  except Exception:
      conn.execute("ROLLBACK")
      raise
  ```
- Close connections after each request (or use a context manager).
- The same `DB_PATH` is used by both the Flask endpoint and the test
  harness's direct `sqlite3.connect("bank.db")` only when CWD = the
  solve.py directory. `__file__`-anchoring guarantees the app always
  writes to the correct location regardless of CWD.

### 2.2  Flask-SQLAlchemy

```python
from flask_sqlalchemy import SQLAlchemy
DB_DIR = os.path.dirname(os.path.abspath(__file__))
db = SQLAlchemy()
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(DB_DIR, 'app.db')}"
db.init_app(app)
```

- Use `db.session.commit()` / `db.session.rollback()`.
- Define models as `db.Model` subclasses.
- Wrap atomic operations in a single session flush + commit.

### 2.3  In-Memory (dict / list)

```python
store = {"accounts": {}, "transactions": []}
```

- State resets when the process restarts — fine for test-client evaluation.
- Use `copy.deepcopy` when returning snapshots if mutations follow.

### 2.4  JSONL (append-only log)

```python
import json, pathlib, os
_LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = pathlib.Path(_LOG_DIR) / "events.jsonl"
def append(event):
    with LOG.open("a") as f:
        f.write(json.dumps(event) + "\n")
```

- Read by iterating lines; write by appending.
- Atomicity: write to a tmp file then `os.replace` for full-file rewrites,
  or accept append-only semantics.

### 2.5  File + Manifest

- Data files in a directory; a `manifest.json` tracks metadata.
- Use `json.dump` with a tmp + rename pattern for crash safety.

---

## 3 — Idempotent Setup Endpoint

Most cases include a setup/init route (`GET /setup`, `POST /init`, etc.).

**Idempotency pattern for SQLite3:**

```python
@app.route("/setup")
def setup():
    conn = get_db()
    try:
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                owner TEXT NOT NULL,
                balance REAL NOT NULL CHECK(balance >= 0)
            )
        """)
        # Seed only if absent — never duplicate
        existing = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if existing == 0:
            conn.execute("INSERT INTO accounts VALUES (1, 'Alice', 100.0)")
            conn.execute("INSERT INTO accounts VALUES (2, 'Bob', 50.0)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return jsonify({"status": "ok"}), 200
```

Key principles:
- `CREATE TABLE IF NOT EXISTS` — safe to call repeatedly.
- **Check-then-insert** for seed data — skip if already present.
- Return the same response shape on every call.

For Flask-SQLAlchemy, use `db.create_all()` plus a count check before seeding.

---

## 4 — Atomic State Transitions

Any endpoint that mutates shared state across multiple rows/records must be
**atomic**: either all changes persist or none do.

### Pattern: Read-Validate-Mutate inside one transaction

```python
@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json(silent=True) or {}

    # --- validate presence ---
    for key in ("from_id", "to_id", "amount"):
        if key not in data:
            return jsonify({"error": f"Missing field: {key}"}), 400

    from_id, to_id, amount = data["from_id"], data["to_id"], data["amount"]

    # --- validate domain rules ---
    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    conn = get_db()
    try:
        conn.execute("BEGIN")

        # Lock rows (SELECT … FOR UPDATE semantics via immediate tx)
        sender = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (from_id,)
        ).fetchone()
        receiver = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (to_id,)
        ).fetchone()

        if sender is None or receiver is None:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Account not found"}), 404

        if sender["balance"] < amount:
            conn.execute("ROLLBACK")
            return jsonify({"error": "Insufficient balance"}), 400

        # --- mutate ---
        conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (amount, from_id),
        )
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (amount, to_id),
        )
        cur = conn.execute(
            "INSERT INTO transactions (from_id, to_id, amount, description) "
            "VALUES (?, ?, ?, ?)",
            (from_id, to_id, amount, data.get("description")),
        )
        tx_id = cur.lastrowid

        # Re-read balances inside the same tx
        new_sender = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (from_id,)
        ).fetchone()
        new_receiver = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (to_id,)
        ).fetchone()

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return jsonify({
        "sender": {"id": new_sender["id"], "balance": new_sender["balance"]},
        "receiver": {"id": new_receiver["id"], "balance": new_receiver["balance"]},
        "transaction_id": tx_id,
    }), 200
```

### SQLite concurrency note

SQLite's `BEGIN IMMEDIATE` acquires a write lock up front, preventing
concurrent writers from interleaving. Use it when the task may have
parallel test threads:

```python
conn.execute("BEGIN IMMEDIATE")
```

For the test-client evaluation model (single-threaded), plain `BEGIN` suffices.

---

## 5 — Validation & Error Responses

### 5.1  Validation checklist (apply in this order)

| Priority | Check                         | Typical status |
|----------|-------------------------------|----------------|
| 1        | JSON body parseable            | 400            |
| 2        | Required fields present        | 400            |
| 3        | Type checks (int, float, str)  | 400            |
| 4        | Range / domain rules (> 0, etc.) | 400          |
| 5        | Cross-field rules (from ≠ to)  | 400            |
| 6        | Resource existence             | 404            |
| 7        | Business constraints (balance) | 400 / 409      |

### 5.2  JSON parse safety

```python
data = request.get_json(silent=True)
if data is None:
    return jsonify({"error": "Invalid or missing JSON body"}), 400
```

`silent=True` prevents Flask from raising 400 with its own error format.

### 5.3  Error response shape

Always return `{"error": "<message>"}` — match the exact string from the
task spec when one is given. Do **not** add extra keys unless specified.

### 5.4  State consistency on error

- Roll back the transaction **before** returning the error response.
- Never partially commit — if validation fails mid-transaction, ROLLBACK.
- The `finally: conn.close()` ensures the connection is returned.

---

## 6 — Response Construction

- Use `flask.jsonify()` — it sets `Content-Type: application/json`.
- Match the exact key names and nesting from the task spec.
- For numeric fields, preserve the type the spec expects:
  - `REAL` / `float` → return as Python float (JSON number).
  - `INTEGER` → return as Python int.
- Status codes: `200` success, `201` created (if specified), `400` bad request,
  `404` not found, `409` conflict (if specified).

---

## 7 — Solving Workflow

1. **Read the task spec** carefully — note every endpoint, field, error
   message, and status code.
2. **Identify the persistence model** (sqlite3, flask_sqlalchemy, etc.).
3. **Identify every resource** (tables, models, keys) and its fields.
4. **List all endpoints** with their HTTP method, path, request shape,
   success response, and error responses.
5. **Write `/app/solve.py`** with:
   - Imports
   - App creation and config
   - DB helper (get_db / db session / store)
   - Setup/init endpoint (idempotent)
   - Each business endpoint with validation → transaction → response
6. **Self-verify** by importing and smoke-testing from `/app`:
   ```bash
   cd /app && rm -f bank.db bank.db-wal bank.db-shm && python3 -c "
   from solve import app
   c = app.test_client()
   # Call setup
   r = c.get('/setup')
   print(r.status_code, r.get_json())
   # Call a business endpoint
   r = c.post('/transfer', json={'from_id':1,'to_id':2,'amount':10})
   print(r.status_code, r.get_json())
   # Test an error case
   r = c.post('/transfer', json={'from_id':1,'to_id':2,'amount':-5})
   print(r.status_code, r.get_json())
   " && rm -f bank.db bank.db-wal bank.db-shm
   ```
7. **Clean up** the DB created during smoke testing:
   ```bash
   rm -f /app/bank.db /app/bank.db-wal /app/bank.db-shm
   ```
   (Adjust the filename to match the task's DB name.)
8. **Fix** any failures before declaring done.

---

## 8 — Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Missing `isolation_level=None` | SQLite auto-commits silently; ROLLBACK has no effect | Set `isolation_level=None` on connect |
| Forgetting `conn.close()` in error paths | Leaked connections, locked DB | Use `try/finally` |
| Using `request.get_json()` without `silent=True` | Flask returns its own 400 HTML on bad JSON | Use `silent=True`, check for `None` |
| Seed data duplicated on second `/setup` call | Duplicate key errors or doubled balances | Check count before insert |
| Returning Python `Decimal` or `Row` objects | `jsonify` cannot serialize | Convert to `float`/`int`/`dict` |
| Mutating state before all validations pass | Partial updates on error | Validate everything **before** any mutation |
| Using `os.getcwd()` for DB path | `bank.db` created in pytest's CWD instead of `/app`; test harness can't find tables (3/9 failures) | Use `os.path.dirname(os.path.abspath(__file__))` to anchor DB to solve.py's directory |
| Not handling optional fields | KeyError on `data["description"]` | Use `data.get("description")` |
| Flask `__version__` deprecation warning | Harmless but noisy | Ignore or use `importlib.metadata` |
| Leaving stale `bank.db` from smoke tests | Test sees leftover data from your verification | Delete `bank.db*` after smoke-testing, or use a unique test DB name |

---

## 9 — Adapting to Other Family Members

When the task differs from the bank-transfer anchor:

- **Different resources** (tasks, notes, carts, URLs): change table schemas
  and field names but keep the same validate→transact→respond pattern.
- **Different persistence**: swap §2 backend; keep §3–§5 logic patterns.
  For any file-based backend (SQLite3, JSONL, file-manifest), always
  anchor file paths to `os.path.dirname(os.path.abspath(__file__))`.
- **Different endpoint count**: add or remove route functions; each follows
  the same internal structure.
- **Different state transitions** (counters, aggregates, checkout):
  add the relevant SQL (SUM, COUNT, conditional UPDATE) inside the
  transaction block.
- **Different validation rules**: adjust the checklist in §5.1 but keep
  the priority order (parse → presence → type → range → cross-field →
  existence → business).

The **invariants** across every family member are:
1. `/app/solve.py` with `app` object.
2. Test-client evaluation (no live server).
3. JSON in / JSON out.
4. Multiple coupled endpoints sharing mutable state.
5. Atomic state mutations with rollback on error.
6. Idempotent setup.
7. **File paths anchored to `__file__`**, never to `os.getcwd()`.
