# Critical Decision Points

Quick reference for the decisions that most commonly cause failures in this family.

## Decision 1: Idempotency Strategy

**Question**: What should `/setup` do when called multiple times?

| Scenario | Strategy | Code Pattern |
|----------|----------|--------------|
| Tests call `/setup` once at start | Skip-if-populated | `if COUNT(*) == 0: INSERT` |
| Tests call `/setup` before each test | Reset-to-initial | `DROP TABLE` + recreate |
| **Default (works for both)** | **Safe hybrid** | `CREATE IF NOT EXISTS` + `INSERT OR REPLACE` |

**Safe hybrid is the default** because:
- Resets seed data to initial values (satisfies reset tests)
- Preserves extra resources created through API (doesn't destroy test data)
- Works whether tests call `/setup` once or multiple times

**Exception**: If spec explicitly says "preserve modified state" or tests verify that balances persist across `/setup` calls, use skip-if-populated.

## Decision 2: Validation Order

**Question**: When multiple errors are true, which error should be returned?

**Standard order** (cheap → expensive, structural → stateful):

1. JSON parsing → 400
2. Required fields → 400
3. Type/range → 400
4. Business rules → 400
5. Resource existence → 404
6. Business constraints → 400

**Why this order**:
- Avoids unnecessary database queries for obviously invalid requests
- Matches typical spec listing order
- Tests expect errors in this sequence

**Example**: If `from_id=999, to_id=999, amount=-5`:
- Amount validation (step 3) fires first → "Amount must be positive"
- Even though account doesn't exist (step 5) and same account (step 4)

## Decision 3: Transaction Boundaries

**Question**: When should you use `BEGIN`/`COMMIT`/`ROLLBACK`?

**Use transactions when**:
- Reading state, then modifying it based on that read
- Multiple related updates must succeed or fail together
- Recording operations that reference the modified state

**Transaction pattern**:
```python
try:
    db.execute("BEGIN")
    
    # Read state
    resource = db.execute("SELECT ...").fetchone()
    
    # Validate
    if resource is None:
        db.execute("ROLLBACK")
        return error_response
    
    # Modify
    db.execute("UPDATE ...")
    
    # Record
    cursor = db.execute("INSERT ...")
    
    db.execute("COMMIT")
    return success_response
    
except Exception:
    db.execute("ROLLBACK")
    return error_response
```

**Critical**: Always `ROLLBACK` before returning error inside transaction.

## Decision 4: Database Connection Lifecycle

**Question**: How to manage database connections across requests?

**Pattern**:
```python
def get_db():
    if 'db' not in g:
        # isolation_level=None: autocommit mode - we manage transactions explicitly
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
```

**Why**:
- `g` is request-scoped: each request gets its own connection
- `teardown_appcontext` ensures cleanup even on exceptions
- Prevents connection leaks and "database is locked" errors
- `isolation_level=None` prevents sqlite3 from auto-BEGINning transactions, which would conflict with our explicit `BEGIN`/`COMMIT`/`ROLLBACK`

**Never**: Store connection in global variable or module-level scope.

**`isolation_level=None` detail**: Python's sqlite3 defaults to `isolation_level=""` (DEFERRED), where it auto-issues `BEGIN` before DML. With explicit transaction management, this causes "cannot start a transaction within a transaction" errors. Setting `isolation_level=None` makes every statement auto-commit unless wrapped in explicit `BEGIN`/`COMMIT`.

## Decision 5: Error Response Format

**Question**: What should error responses look like?

**Standard format**:
```python
return jsonify({"error": "Error message"}), status_code
```

**Status codes**:
- 400: Invalid input, business rule violation, constraint failure
- 404: Resource not found
- 500: Unexpected server error

**Error messages**: Use exact text from spec when provided. When spec doesn't specify, use clear, descriptive messages.

## Decision 6: Success Response Format

**Question**: What should success responses include?

**Standard pattern**: Return updated state + generated IDs

```python
return jsonify({
    "resource": {"id": 1, "balance": 75.0},
    "operation_id": 42
}), 200
```

**Why**:
- Tests verify state changes by checking response
- Generated IDs (auto-increment) must be returned for tracking
- Updated state allows tests to verify without additional queries

## Common Failure Modes

1. **Not using `INSERT OR REPLACE`**: Seed data doesn't reset between tests
2. **Wrong validation order**: Tests see unexpected error messages
3. **Forgetting `ROLLBACK`**: Transaction state becomes inconsistent
4. **Not using `BEGIN`**: Operations aren't atomic, partial updates corrupt state
5. **Storing DB connection globally**: Connection leaks, "database is locked" errors
6. **Forgetting `row_factory = sqlite3.Row`**: Can't access columns by name
7. **Hardcoding absolute DB path**: Fails when working directory changes

## Testing Checklist

Before submission, verify:

- [ ] `/setup` is idempotent (call multiple times, check behavior)
- [ ] Validation order matches spec (test with multiple simultaneous errors)
- [ ] Failed operations don't corrupt state (test atomicity)
- [ ] Sequential operations produce correct cumulative state
- [ ] Edge cases handled (zero, negative, missing fields, non-existent resources)
- [ ] Response format matches spec exactly
- [ ] Database connection cleanup works (no leaks)
