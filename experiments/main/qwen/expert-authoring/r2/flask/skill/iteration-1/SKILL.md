---
name: flask
description: >
  Build a Flask JSON HTTP service with shared mutable state, multiple coupled
  endpoints, proper validation, atomic state transitions, and idempotent setup.
  The app is exported as `app` from /app/solve.py and tested via Flask's test
  client without a live server.
---

# Flask Stateful JSON Service

## 1. Family Overview

Every case in this family requires building a Flask application that:
- Exposes **multiple behaviorally coupled** JSON endpoints (never a single route).
- Shares **mutable domain state** across requests (database, in-memory dict, file).
- Is exported as a Flask object named **`app`** from **`/app/solve.py`**.
- Is tested via **`app.test_client()`** — no live network server.

The resource model, persistence backend, endpoint contracts, state transitions, and
validation rules vary per case. The task instruction fully specifies them.

## 2. Solution Skeleton

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- persistence setup (varies by case) ---

@app.route("/setup", methods=["GET"])
def setup():
    # Idempotent: safe to call multiple times
    ...

@app.route("/<action>", methods=["POST"])  # one or more action endpoints
def action():
    # Validate → mutate state atomically → return JSON
    ...
```

Adapt imports and routes to match the task's endpoint contract exactly.

## 3. Persistence Backends

Read the task to determine which backend is required. Use the matching pattern below.

### 3a. sqlite3 (raw)

```python
import sqlite3, os

DB_PATH = os.path.join(os.getcwd(), "<db_name>.db")  # from task spec

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # dict-like access
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```

- Always close connections in a `finally` block.
- Use `conn.execute("BEGIN IMMEDIATE")` before reads that participate in a write,
  to acquire a write lock up front and prevent `SQLITE_BUSY`.
- Call `conn.commit()` on success, `conn.rollback()` on any error.

### 3b. Flask-SQLAlchemy

```python
from flask_sqlalchemy import SQLAlchemy

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///<path>"
db = SQLAlchemy(app)

class Model(db.Model):
    ...

# In setup: db.create_all(); db.session.commit()
# In mutations: db.session.add/commit/rollback
```

### 3c. In-memory

```python
state = {}  # module-level dict

@app.route("/setup", methods=["GET"])
def setup():
    global state
    if not state:          # idempotent guard
        state = {...}      # seed data
    return jsonify({"status": "ok"})
```

### 3d. File-manifest / JSONL

Use `json` module; read on each request or cache and flush. Use file locking
(`fcntl.flock`) if tests issue concurrent requests.

## 4. Idempotent Setup

The `/setup` endpoint **must be safely callable multiple times** without duplicating
seed data or failing.

**Decision rules (choose based on persistence backend):**

| Backend         | Idempotency pattern                                       |
|-----------------|-----------------------------------------------------------|
| sqlite3         | `CREATE TABLE IF NOT EXISTS` + count-check before INSERT  |
| Flask-SQLAlchemy| `db.create_all()` (already idempotent) + existence check  |
| In-memory       | Guard on `if not state:` before seeding                   |
| File/JSONL      | Check if file exists and is non-empty before writing      |

**sqlite3 idempotent seed pattern:**

```python
conn.execute("CREATE TABLE IF NOT EXISTS accounts (...)")
conn.execute("CREATE TABLE IF NOT EXISTS transactions (...)")
existing = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
if existing == 0:
    conn.execute("INSERT INTO accounts ...")  # seed rows
conn.commit()
```

## 5. Atomic State Transitions

When an endpoint mutates multiple rows or entities, wrap the entire operation in a
transaction so partial failures never corrupt state.

```python
conn = get_db()
try:
    conn.execute("BEGIN IMMEDIATE")   # acquire write lock up front

    # 1. Read current state (with lock)
    sender = conn.execute("SELECT ... WHERE id = ?", (from_id,)).fetchone()
    receiver = conn.execute("SELECT ... WHERE id = ?", (to_id,)).fetchone()

    # 2. Validate business rules (rollback + return error on failure)
    if sender is None or receiver is None:
        conn.rollback()
        return jsonify({"error": "..."}), 404

    # 3. Compute new state
    new_sender_bal = sender["balance"] - amount
    new_receiver_bal = receiver["balance"] + amount

    # 4. Write mutations
    conn.execute("UPDATE ... SET balance = ? WHERE id = ?", (new_sender_bal, from_id))
    conn.execute("UPDATE ... SET balance = ? WHERE id = ?", (new_receiver_bal, to_id))
    cursor = conn.execute("INSERT INTO transactions ...")

    conn.commit()
    return jsonify({...}), 200

except Exception as e:
    conn.rollback()
    return jsonify({"error": str(e)}), 500
finally:
    conn.close()
```

**Key principles:**
- `BEGIN IMMEDIATE` prevents deadlocks by acquiring the write lock before reads.
- Validate **after** acquiring the lock but **before** writing.
- Always rollback on validation failure to release the lock cleanly.
- Always close the connection in `finally`.

## 6. Validation and Error Handling

Build validation in layers. Each layer short-circuits with the specified HTTP status
and JSON error body. **Leave persistent state untouched on any validation failure.**

### 6a. Validation order (apply in this sequence)

1. **Request parsing** — reject malformed / missing JSON body → `400`
2. **Required fields** — reject if any mandatory key is absent → `400`
3. **Type checks** — reject wrong types. Watch out for Python's `bool` being a
   subclass of `int`: add `isinstance(val, bool)` guards before `isinstance(val, int)`
   if the spec requires strict integer types.
4. **Business rules** — same-account transfer, negative amount, duplicate name, etc.
   → status code per spec (typically `400` or `409`)
5. **Existence checks** — unknown resource IDs → `404`
6. **Capacity checks** — insufficient balance, full queue, etc. → `400`

### 6b. Type-safe integer check

```python
def is_strict_int(val):
    """Return True only for int, not bool."""
    return isinstance(val, int) and not isinstance(val, bool)
```

Use this when the task specifies integer fields and tests may send booleans.

### 6c. Error response format

Match the task spec exactly. Most cases use:

```python
return jsonify({"error": "<exact message from spec>"}), <status_code>
```

**Critical**: Copy error message strings verbatim from the task instruction. Tests
often assert exact string matches.

## 7. Response Construction

- Use `jsonify()` for all responses (sets `Content-Type: application/json`).
- Return the exact JSON schema from the task spec. Field names and nesting must match.
- For success responses, include the post-mutation state of affected entities.
- `transaction_id` or similar auto-generated IDs come from `cursor.lastrowid` (sqlite3)
  or the ORM's flushed object.

## 8. General Checklist

Before considering the solution complete, verify:

- [ ] `app` is a Flask instance at module level in `/app/solve.py`
- [ ] All route paths and HTTP methods match the spec exactly
- [ ] `/setup` is idempotent (call it twice → same result, no duplicate data)
- [ ] All JSON field names match the spec (case-sensitive)
- [ ] Error messages are exact string copies from the spec
- [ ] HTTP status codes match the spec for every error condition
- [ ] Mutating endpoints use transactions for atomicity
- [ ] Connections / sessions are always closed (finally block)
- [ ] Validation order: parse → required → type → business → existence → capacity
- [ ] Booleans are rejected where strict integers are required
- [ ] No `if __name__ == "__main__": app.run()` guard is needed (test client imports `app`)

## 9. Self-Verification Procedure

After writing `/app/solve.py`, run this smoke test:

```python
from solve import app
client = app.test_client()

# 1. Setup is idempotent
r1 = client.get("/setup")
r2 = client.get("/setup")
assert r1.status_code == 200 and r2.status_code == 200

# 2. Happy path
r = client.post("/<action>", json={...valid payload...})
assert r.status_code == 200
data = r.get_json()
# assert expected keys and values

# 3. Each error condition from the spec
for payload, expected_status, expected_error in [
    ({...missing field...}, 400, "..."),
    ({...same account...},  400, "Cannot transfer to the same account"),
    ({...bad amount...},    400, "Amount must be positive"),
    ({...unknown id...},    404, "Account not found"),
]:
    r = client.post("/<action>", json=payload)
    assert r.status_code == expected_status, f"Got {r.status_code} for {payload}"
    if expected_error:
        assert r.get_json().get("error") == expected_error

# 4. State consistency: after a successful mutation, verify DB reflects changes
```

Adapt the smoke test payloads to match the case's specific endpoint contract.

## 10. Common Pitfalls

| Pitfall | Consequence | Fix |
|---------|-------------|-----|
| Forgetting `CREATE TABLE IF NOT EXISTS` | Setup crashes on second call | Always use `IF NOT EXISTS` |
| Not using `BEGIN IMMEDIATE` | `SQLITE_BUSY` under concurrent test calls | Use `BEGIN IMMEDIATE` for write-intent transactions |
| `isinstance(True, int)` → `True` | Booleans pass integer validation | Add `not isinstance(val, bool)` guard |
| Not closing DB connection | Leaked connections, locked DB | Always `conn.close()` in `finally` |
| Committing before validation | Partial writes on error | Validate first, commit last |
| Hardcoding DB path incorrectly | DB created in wrong directory | Use `os.path.join(os.getcwd(), "<name>.db")` |
| Approximating error messages | String-match test failures | Copy messages verbatim from spec |
| Missing `silent=True` on `get_json()` | Flask raises 400 before your code runs | Use `request.get_json(silent=True)` and check for `None` |
