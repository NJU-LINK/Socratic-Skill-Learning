#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)
DATABASE = 'bank.db'


def get_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/setup')
def setup():
    conn = get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS accounts "
                     "(id INTEGER PRIMARY KEY, owner TEXT NOT NULL, "
                     "balance REAL NOT NULL CHECK(balance >= 0))")
        conn.execute("CREATE TABLE IF NOT EXISTS transactions "
                     "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, "
                     "amount REAL NOT NULL, description TEXT)")
        cur = conn.execute("SELECT COUNT(*) AS cnt FROM accounts")
        if cur.fetchone()['cnt'] == 0:
            conn.execute(
                "INSERT INTO accounts (id, owner, balance) VALUES (1, 'Alice', 100.0)")
            conn.execute(
                "INSERT INTO accounts (id, owner, balance) VALUES (2, 'Bob', 50.0)")
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()


@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Missing request body"}), 400

    from_id = data.get('from_id')
    to_id = data.get('to_id')
    amount = data.get('amount')

    if from_id is None or to_id is None or amount is None:
        return jsonify({"error": "Missing from_id, to_id, or amount"}), 400

    if from_id == to_id:
        return jsonify({"error": "Cannot transfer to the same account"}), 400

    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    conn = get_conn()
    try:
        conn.execute("BEGIN")

        cur = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (from_id,))
        sender = cur.fetchone()
        if sender is None:
            conn.rollback()
            return jsonify({"error": "Account not found"}), 404

        cur = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (to_id,))
        receiver = cur.fetchone()
        if receiver is None:
            conn.rollback()
            return jsonify({"error": "Account not found"}), 404

        if sender['balance'] < amount:
            conn.rollback()
            return jsonify({"error": "Insufficient balance"}), 400

        description = data.get('description', '')

        conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (amount, from_id))
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (amount, to_id))
        cur = conn.execute(
            "INSERT INTO transactions (from_id, to_id, amount, description) "
            "VALUES (?, ?, ?, ?)",
            (from_id, to_id, amount, description))
        transaction_id = cur.lastrowid

        conn.commit()

        cur = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (from_id,))
        sender_balance = cur.fetchone()['balance']
        cur = conn.execute(
            "SELECT id, balance FROM accounts WHERE id = ?", (to_id,))
        receiver_balance = cur.fetchone()['balance']

        return jsonify({
            "sender": {"id": from_id, "balance": sender_balance},
            "receiver": {"id": to_id, "balance": receiver_balance},
            "transaction_id": transaction_id
        })
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(debug=True)
PYEOF
