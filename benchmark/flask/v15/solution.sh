#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)
DATABASE = 'cart.db'


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS cart_items
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         item TEXT NOT NULL,
         quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
         price REAL NOT NULL CHECK(price > 0))''')
    conn.commit()
    return conn


@app.route('/cart/add', methods=['POST'])
def cart_add():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    item = data.get('item')
    quantity = data.get('quantity')
    price = data.get('price')

    if not item or quantity is None or price is None:
        return jsonify({'error': 'Missing required fields'}), 400

    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({'error': 'Quantity must be a positive integer'}), 400

    if not isinstance(price, (int, float)) or price <= 0:
        return jsonify({'error': 'Price must be positive'}), 400

    conn = get_db()
    existing = conn.execute(
        'SELECT id, quantity FROM cart_items WHERE item = ?', (item,)
    ).fetchone()

    if existing:
        new_qty = existing['quantity'] + quantity
        conn.execute(
            'UPDATE cart_items SET quantity = ? WHERE id = ?',
            (new_qty, existing['id'])
        )
        conn.commit()
        row = conn.execute(
            'SELECT * FROM cart_items WHERE id = ?', (existing['id'],)
        ).fetchone()
    else:
        cursor = conn.execute(
            'INSERT INTO cart_items (item, quantity, price) VALUES (?, ?, ?)',
            (item, quantity, price)
        )
        conn.commit()
        row = conn.execute(
            'SELECT * FROM cart_items WHERE id = ?', (cursor.lastrowid,)
        ).fetchone()

    conn.close()
    return jsonify({
        'id': row['id'],
        'item': row['item'],
        'quantity': row['quantity'],
        'price': row['price']
    }), 201


@app.route('/cart', methods=['GET'])
def cart_list():
    conn = get_db()
    rows = conn.execute('SELECT * FROM cart_items').fetchall()
    conn.close()
    items = []
    for row in rows:
        items.append({
            'id': row['id'],
            'item': row['item'],
            'quantity': row['quantity'],
            'price': row['price'],
            'total': round(row['quantity'] * row['price'], 2)
        })
    return jsonify(items)


@app.route('/cart/<int:item_id>', methods=['PUT'])
def cart_update(item_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    quantity = data.get('quantity')
    if quantity is None:
        return jsonify({'error': 'Missing quantity'}), 400
    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({'error': 'Quantity must be a positive integer'}), 400

    conn = get_db()
    row = conn.execute(
        'SELECT * FROM cart_items WHERE id = ?', (item_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Item not found'}), 404

    conn.execute(
        'UPDATE cart_items SET quantity = ? WHERE id = ?', (quantity, item_id)
    )
    conn.commit()
    row = conn.execute(
        'SELECT * FROM cart_items WHERE id = ?', (item_id,)
    ).fetchone()
    conn.close()
    return jsonify({
        'id': row['id'],
        'item': row['item'],
        'quantity': row['quantity'],
        'price': row['price']
    })


@app.route('/cart/<int:item_id>', methods=['DELETE'])
def cart_delete(item_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM cart_items WHERE id = ?', (item_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    conn.execute('DELETE FROM cart_items WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'deleted'})


@app.route('/cart/total', methods=['GET'])
def cart_total():
    conn = get_db()
    result = conn.execute(
        'SELECT SUM(quantity * price) as total, COUNT(*) as item_count FROM cart_items'
    ).fetchone()
    conn.close()
    t = result['total'] if result['total'] is not None else 0.0
    return jsonify({'total': round(t, 2), 'item_count': result['item_count']})


@app.route('/cart/checkout', methods=['POST'])
def cart_checkout():
    conn = get_db()
    rows = conn.execute('SELECT * FROM cart_items').fetchall()
    if not rows:
        conn.close()
        return jsonify({'error': 'Cart is empty'}), 400

    items = []
    total = 0.0
    for row in rows:
        line_total = row['quantity'] * row['price']
        total += line_total
        items.append({
            'item': row['item'],
            'quantity': row['quantity'],
            'price': row['price'],
            'total': round(line_total, 2)
        })

    conn.execute('DELETE FROM cart_items')
    conn.commit()
    conn.close()
    return jsonify({'total': round(total, 2), 'items': items, 'status': 'checked_out'})


@app.route('/cart/clear', methods=['GET'])
def cart_clear():
    conn = get_db()
    conn.execute('DELETE FROM cart_items')
    conn.commit()
    conn.close()
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    app.run(debug=True)
PYEOF
