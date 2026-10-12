#!/bin/bash

# Concatenate fragments in order and recover the SQLite database
# The fragments are split equally from a padded database file.
# Fragment order: 1, 2, 3, 4 (as numbered)

FRAGMENT_DIR="/app/fragments"
DB_PATH="/tmp/recovered.db"
OUTPUT_PATH="/app/recover.json"

cat "${FRAGMENT_DIR}/fragment_1" \
    "${FRAGMENT_DIR}/fragment_2" \
    "${FRAGMENT_DIR}/fragment_3" \
    "${FRAGMENT_DIR}/fragment_4" > "${DB_PATH}"

python3 -c "
import json
import sqlite3

conn = sqlite3.connect('${DB_PATH}')
cur = conn.cursor()

# --- Employees ---
# The legacy application stored integers as raw big-endian bytes (BLOBs).
# We must detect BLOB values and decode them as big-endian integers.
cur.execute('SELECT id, name, dept_id FROM employees ORDER BY rowid')
employees = []
for id_val, name, dept_id in cur.fetchall():
    if isinstance(id_val, bytes):
        id_val = int.from_bytes(id_val, 'big')
    if isinstance(dept_id, bytes):
        dept_id = int.from_bytes(dept_id, 'big')
    employees.append({'id': id_val, 'name': name, 'dept_id': dept_id})

# --- Departments ---
cur.execute('SELECT id, name, budget FROM departments ORDER BY rowid')
departments = []
for id_val, name, budget in cur.fetchall():
    departments.append({'id': id_val, 'name': name, 'budget': budget})

# --- Salaries ---
# Some bonus values are long text strings stored on overflow pages.
# sqlite3 handles overflow pages automatically.
cur.execute('SELECT emp_id, amount, bonus FROM salaries ORDER BY rowid')
salaries = []
for emp_id, amount, bonus in cur.fetchall():
    salaries.append({'emp_id': emp_id, 'amount': amount, 'bonus': bonus})

conn.close()

result = {
    'employees': employees,
    'departments': departments,
    'salaries': salaries,
}

with open('${OUTPUT_PATH}', 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
"
