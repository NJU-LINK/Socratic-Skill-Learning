# Flask Stateful Service Template

This is a complete, annotated template for building stateful Flask services with SQLite3.
Adapt the resource schema, endpoints, and business rules for each specific task.

## Complete Template

```python
import sqlite3
import os
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# Database path in current working directory
DB_PATH = os.path.join(os.getcwd(), 'your_database.db')


def get_db():
    """Get a database connection for the current request context."""
    if 'db' not in g:
        # isolation_level=None: autocommit mode - we manage transactions explicitly
        # Without this, sqlite3 auto-BEGINs before DML, conflicting with our explicit BEGIN
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close the database connection at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.route('/setup', methods=['GET'])
def setup():
    """Create tables and seed initial data. Idempotent via safe hybrid pattern."""
    db = get_db()
    
    # Create tables with IF NOT EXISTS
    db.execute('''
        CREATE TABLE IF NOT EXISTS your_table (
            id INTEGER PRIMARY KEY,
            -- define your columns here
            name TEXT NOT NULL,
            value REAL NOT NULL CHECK(value >= 0)
        )
    ''')
    
    # Optional: create related tables
    db.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            -- track operations on your resources
            resource_id INTEGER NOT NULL,
            operation_type TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Safe hybrid: INSERT OR REPLACE resets seed data
    # With isolation_level=None, each statement auto-commits individually
    db.execute("INSERT OR REPLACE INTO your_table (id, name, value) VALUES (1, 'Item1', 100.0)")
    db.execute("INSERT OR REPLACE INTO your_table (id, name, value) VALUES (2, 'Item2', 50.0)")
    
    return jsonify({"status": "ok"})


@app.route('/your_endpoint', methods=['POST'])
def your_endpoint():
    """Perform an atomic operation with proper validation."""
    
    # 1. Validate JSON
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # 2. Validate required fields
    required_field = data.get('required_field')
    if required_field is None:
        return jsonify({"error": "Missing required field: required_field"}), 400
    
    # 3. Type/range validation
    if not isinstance(required_field, (int, float)) or required_field <= 0:
        return jsonify({"error": "required_field must be positive"}), 400
    
    # 4. Business rules (before database access)
    # e.g., if from_id == to_id: return error
    
    db = get_db()
    
    # 5-6. Resource existence + business constraints inside transaction
    try:
        db.execute("BEGIN")
        
        # Read current state
        resource = db.execute(
            "SELECT * FROM your_table WHERE id = ?", (required_field,)
        ).fetchone()
        
        # 5. Resource existence
        if resource is None:
            db.execute("ROLLBACK")
            return jsonify({"error": "Resource not found"}), 404
        
        # 6. Business constraints
        if resource['value'] < some_threshold:
            db.execute("ROLLBACK")
            return jsonify({"error": "Business constraint violated"}), 400
        
        # Perform updates
        new_value = resource['value'] - some_amount
        db.execute("UPDATE your_table SET value = ? WHERE id = ?", (new_value, resource['id']))
        
        # Record the operation
        cursor = db.execute(
            "INSERT INTO operations (resource_id, operation_type) VALUES (?, ?)",
            (resource['id'], 'your_operation')
        )
        operation_id = cursor.lastrowid
        
        db.execute("COMMIT")
        
        return jsonify({
            "resource": {"id": resource['id'], "value": new_value},
            "operation_id": operation_id
        }), 200
        
    except Exception as e:
        db.execute("ROLLBACK")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
```

## Adaptation Checklist

When adapting this template for a new task:

1. **Resource schema**: Define tables with appropriate columns, types, and constraints
2. **Seed data**: Identify initial resources to create in `/setup`
3. **Endpoints**: Map task requirements to HTTP methods and paths
4. **Validation rules**: Identify required fields, type constraints, business rules
5. **Atomic operations**: Determine which operations need transactions
6. **Response format**: Match the spec's required response structure
7. **Error messages**: Use exact error messages from the spec

## Testing Template

```python
import os
import sys

# Clean database before testing
if os.path.exists('your_database.db'):
    os.remove('your_database.db')

from solve import app

client = app.test_client()

# Test setup
resp = client.get('/setup')
assert resp.status_code == 200, f"Setup failed: {resp.status_code}"

# Test idempotency
resp = client.get('/setup')
assert resp.status_code == 200, f"Second setup failed: {resp.status_code}"

# Test valid operation
resp = client.post('/your_endpoint', json={...})
assert resp.status_code == 200, f"Valid operation failed: {resp.status_code}"
data = resp.get_json()
# Verify response structure matches spec

# Test validation errors
test_cases = [
    ({}, 400, "Missing fields"),
    ({'required_field': -5}, 400, "Negative value"),
    ({'required_field': 999}, 404, "Non-existent resource"),
]

for body, expected_status, desc in test_cases:
    resp = client.post('/your_endpoint', json=body)
    assert resp.status_code == expected_status, f"{desc}: expected {expected_status}, got {resp.status_code}"

# Test atomicity: failing operation shouldn't corrupt state
initial_state = ... # capture state
client.post('/your_endpoint', json={...})  # operation that should fail
final_state = ... # capture state
assert initial_state == final_state, "Failed operation corrupted state"

print("All tests passed!")
```
