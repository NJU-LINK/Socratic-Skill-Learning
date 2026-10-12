#!/usr/bin/env python3
"""
Recover rows from a corrupted SQLite database file.

Handles corruption patterns:
- Bit flips in unused page areas (noise bytes)
- Corrupted serial types in record headers (most common)
- Corrupted cell-content-area pointers in page headers
- Mixed integer/float storage in REAL columns
- Text stored with blob serial types (bit 0 flip)
- Truncated or zeroed regions

Strategy:
  1. Try sqlite3 first (fast path)
  2. Parse raw SQLite page format
  3. Use schema + payload-length + data heuristics to fix serial types
  4. Score candidate parses to pick the best interpretation

Usage: python3 recover_sqlite.py <db_path> <output_json_path> [schema_json]
"""

import struct
import sys
import json
import re
import os
import subprocess


# ── Varint and serial-type primitives ─────────────────────────────────────

def parse_varint(data, offset):
    """Parse a SQLite varint (1-9 bytes). Returns (value, new_offset)."""
    if offset >= len(data):
        return 0, offset + 1
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, offset + i + 1
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80:
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset + 9


def decode_serial_type(st):
    """Return (kind, byte_size) for a SQLite serial type code."""
    if st == 0:
        return ('null', 0)
    elif 1 <= st <= 6:
        return ('int', [0, 1, 2, 3, 4, 6, 8][st])
    elif st == 7:
        return ('float', 8)
    elif st == 8:
        return ('const0', 0)
    elif st == 9:
        return ('const1', 0)
    elif st >= 12:
        if st % 2 == 0:
            return ('text', (st - 12) // 2)
        else:
            return ('blob', (st - 13) // 2)
    return ('reserved', 0)


# ── Value extraction ──────────────────────────────────────────────────────

def _read_text(payload, pos, sz):
    """Read text bytes, preferring utf-8."""
    raw = payload[pos:pos + sz]
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def extract_values(payload, data_start, serial_types, schema_types):
    """Extract column values using (trusted) serial types."""
    values, d = [], data_start
    for j, st in enumerate(serial_types):
        kind, sz = decode_serial_type(st)
        expected = (schema_types[j]
                    if schema_types and j < len(schema_types) else None)
        if kind == 'null':
            values.append(None)
        elif kind == 'int':
            if d + sz <= len(payload):
                values.append(int.from_bytes(
                    payload[d:d + sz], 'big', signed=True))
                d += sz
            else:
                values.append(None)
        elif kind == 'float':
            if d + 8 <= len(payload):
                values.append(struct.unpack('>d', payload[d:d + 8])[0])
                d += 8
            else:
                values.append(None)
        elif kind in ('const0', 'const1'):
            values.append(int(kind[-1]))
        elif kind in ('text', 'blob'):
            if d + sz <= len(payload):
                raw = payload[d:d + sz]
                if kind == 'text' or expected == 'TEXT':
                    values.append(_read_text(payload, d, sz))
                else:
                    values.append(raw)
                d += sz
            else:
                values.append(None)
        else:
            values.append(None)
    return values


def extract_by_sizes(payload, data_start, col_sizes, schema_types):
    """Extract values given explicit byte sizes per column."""
    values, d = [], data_start
    for sz, stype in zip(col_sizes, schema_types):
        if sz == 0:
            values.append(None)
        elif stype == 'TEXT':
            values.append(_read_text(payload, d, sz))
            d += sz
        elif stype == 'REAL':
            if sz == 8:
                values.append(struct.unpack('>d', payload[d:d + 8])[0])
            elif sz == 4:
                values.append(struct.unpack('>f', payload[d:d + 4])[0])
            elif 1 <= sz <= 6:
                values.append(int.from_bytes(
                    payload[d:d + sz], 'big', signed=True))
            else:
                values.append(None)
            d += sz
        elif stype == 'INTEGER':
            if d + sz <= len(payload):
                values.append(int.from_bytes(
                    payload[d:d + sz], 'big', signed=True))
            else:
                values.append(None)
            d += sz
        elif stype == 'BLOB':
            if d + sz <= len(payload):
                values.append(payload[d:d + sz])
            else:
                values.append(None)
            d += sz
        else:
            if d + sz <= len(payload):
                values.append(payload[d:d + sz])
            else:
                values.append(None)
            d += sz
    return values


# ── Scoring helpers ───────────────────────────────────────────────────────

def _is_printable(b):
    return 0x20 <= b <= 0x7e or b in (0x09, 0x0a, 0x0d)


def _text_score_bonus(text_bytes):
    """Bonus for text that looks like a real identifier / word."""
    try:
        s = text_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return 0
    bonus = 0
    if s.isalnum() or s.replace('_', '').isalnum():
        bonus += 15
    if len(s) >= 3:
        bonus += 5
    return bonus


def _numeric_size_score(sz, stype):
    """Score for a numeric column of given byte size."""
    if stype == 'REAL':
        return {8: 6, 4: 4, 6: 2, 3: 2, 2: 2, 1: 1}.get(sz, 0)
    elif stype == 'INTEGER':
        return {1: 4, 2: 4, 3: 3, 4: 3, 6: 2, 8: 2}.get(sz, 0)
    return 0


# ── Record parsing with schema-guided recovery ────────────────────────────

def parse_record_smart(payload, schema_types=None):
    """
    Parse a record payload. If serial types are corrupted,
    uses schema + data heuristics to find the best parse.
    """
    if len(payload) < 2:
        return None
    header_size, h_pos = parse_varint(payload, 0)
    if header_size < 2 or header_size > min(len(payload), 50):
        return None

    # Parse declared serial types
    serial_types, pos = [], h_pos
    while pos < header_size:
        st, pos = parse_varint(payload, pos)
        serial_types.append(st)

    num_cols = len(serial_types)
    data_start = header_size
    actual_data = len(payload) - data_start
    if actual_data < 0:
        return None

    # Fast path: declared types match payload size
    declared_size = sum(decode_serial_type(st)[1] for st in serial_types)
    if declared_size == actual_data:
        return extract_values(payload, data_start, serial_types, schema_types)

    # Corrupted serial types — need schema to recover
    if not schema_types or len(schema_types) != num_cols:
        return None

    return _recover_record(payload, data_start, actual_data, schema_types)


def _recover_record(payload, data_start, actual_data, schema_types):
    """Find best column-size assignment using search + scoring."""
    ncols = len(schema_types)

    # Build candidate byte sizes per column
    cands = []
    for j in range(ncols):
        st = schema_types[j]
        if st in ('TEXT', 'BLOB'):
            c = list(range(0, min(actual_data + 1, 2000)))
        elif st in ('REAL', 'INTEGER'):
            c = [0, 1, 2, 3, 4, 6, 8]
        else:
            c = list(range(0, actual_data + 1))
        cands.append(c)

    # DFS to enumerate all valid size combos
    best_score = -1e9
    best_sizes = None

    def dfs(idx, current, running_sum):
        nonlocal best_score, best_sizes
        if idx == ncols:
            if running_sum == actual_data:
                # Score this parse
                score = 0.0
                off = data_start
                for k in range(ncols):
                    sz = current[k]
                    stype = schema_types[k]
                    if stype == 'TEXT' and sz > 0:
                        score += sz * 10  # longer text preferred
                        score += _text_score_bonus(
                            payload[off:off + sz])
                    elif stype in ('REAL', 'INTEGER'):
                        score += _numeric_size_score(sz, stype)
                    elif stype == 'BLOB' and sz > 0:
                        score += sz * 5
                    if sz == 0 and stype != 'BLOB':
                        score -= 8  # null penalty
                    off += sz
                if score > best_score:
                    best_score = score
                    best_sizes = list(current)
            return

        remaining_min = 0
        remaining_max = 0
        for k in range(idx + 1, ncols):
            remaining_max += max(cands[k])

        for sz in cands[idx]:
            new_sum = running_sum + sz
            if new_sum > actual_data:
                break
            if new_sum + remaining_max < actual_data:
                continue
            # Validate text
            if schema_types[idx] == 'TEXT' and sz > 0:
                off = data_start + running_sum
                ok = True
                for kk in range(sz):
                    if off + kk >= len(payload):
                        ok = False
                        break
                    if not _is_printable(payload[off + kk]):
                        ok = False
                        break
                if not ok:
                    continue
            current.append(sz)
            dfs(idx + 1, current, new_sum)
            current.pop()

    dfs(0, [], 0)

    if best_sizes is not None:
        return extract_by_sizes(payload, data_start, best_sizes, schema_types)
    return None


# ── Page-level parsing ────────────────────────────────────────────────────

def find_schema(data, page_size):
    """Extract table schemas from CREATE TABLE text in page 1."""
    page1 = data[:page_size]
    schemas = []
    for m in re.finditer(
            rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)',
            page1, re.IGNORECASE):
        tname = m.group(1).decode('utf-8')
        cols = []
        for cd in m.group(2).decode('utf-8').split(','):
            parts = cd.strip().split()
            if len(parts) >= 2:
                cols.append((parts[0], parts[1].upper()))
            elif len(parts) == 1:
                cols.append((parts[0], 'BLOB'))
        schemas.append((tname, cols))
    return schemas


def parse_leaf_page(data, page_start, page_size, schema_types=None):
    """Parse a leaf table b-tree page (type 0x0d / 13)."""
    page = data[page_start:page_start + page_size]
    if len(page) < 8 or page[0] != 0x0d:
        return []

    cell_count = struct.unpack('>H', page[3:5])[0]
    ptrs = []
    for i in range(cell_count):
        off = 8 + i * 2
        if off + 2 > len(page):
            break
        ptrs.append(struct.unpack('>H', page[off:off + 2])[0])

    rows = []
    for ptr in sorted(p for p in ptrs if p < page_size):
        abs_off = page_start + ptr
        offset = abs_off
        payload_len, offset = parse_varint(data, offset)
        rowid, offset = parse_varint(data, offset)
        if payload_len <= 0 or payload_len > page_size:
            continue
        payload = data[offset:offset + payload_len]
        if len(payload) < 3:
            continue
        values = parse_record_smart(payload, schema_types)
        if values is not None and len(values) > 0:
            rows.append((rowid, values))
    return rows


# ── Fast-path: normal sqlite3 ─────────────────────────────────────────────

def try_sqlite3(db_path):
    """Try normal sqlite3 read. Returns list-of-dicts or None."""
    try:
        r = subprocess.run(
            ['sqlite3', '-json', db_path,
             "SELECT name FROM sqlite_master WHERE type='table'"],
            capture_output=True, text=True, timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        tables = json.loads(r.stdout)
        if not tables:
            return None
        tname = tables[0]['name']
        r2 = subprocess.run(
            ['sqlite3', '-json', db_path,
             f'SELECT * FROM "{tname}"'],
            capture_output=True, text=True, timeout=5)
        if r2.returncode == 0 and r2.stdout.strip():
            return json.loads(r2.stdout)
    except Exception:
        pass
    return None


# ── Main orchestrator ─────────────────────────────────────────────────────

def recover_database(db_path, schema_override=None):
    """Recover rows. schema_override = {table: [[col,type],...]}."""
    rows = try_sqlite3(db_path)
    if rows is not None:
        return None, {None: rows}

    with open(db_path, 'rb') as f:
        data = f.read()

    if len(data) < 100 or data[:16] != b'SQLite format 3\x00':
        return [], {}

    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    db_pages = struct.unpack('>I', data[28:32])[0]
    if db_pages == 0:
        db_pages = len(data) // page_size

    if schema_override:
        schemas = [(tn, cols) for tn, cols in schema_override.items()]
    else:
        schemas = find_schema(data, page_size)
        if not schemas:
            schemas = [('unknown', [])]

    all_rows = {tn: [] for tn, _ in schemas}
    for pn in range(db_pages):
        ps = pn * page_size
        if ps + 1 > len(data):
            break
        if data[ps] == 0x0d:
            for tn, cols in schemas:
                stypes = [ct for _, ct in cols] if cols else None
                page_rows = parse_leaf_page(data, ps, page_size, stypes)
                if page_rows:
                    all_rows[tn].extend(page_rows)

    return schemas, all_rows


def format_output(schemas, all_rows):
    """Produce the final JSON-friendly list/dict."""
    if schemas is None:
        return all_rows[None]
    results = {}
    for tn, cols in schemas:
        rows = all_rows.get(tn, [])
        if not rows:
            continue
        cnames = [cn for cn, _ in cols]
        formatted = []
        for rowid, values in sorted(rows, key=lambda x: x[0]):
            if isinstance(values, dict):
                formatted.append(values)
            else:
                row = {}
                for j, cn in enumerate(cnames):
                    row[cn] = values[j] if j < len(values) else None
                formatted.append(row)
        results[tn] = formatted
    if len(results) == 1:
        return list(results.values())[0]
    elif not results:
        return []
    return results


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db> <out.json> [schema.json]",
              file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    out_path = sys.argv[2]
    schema_override = None
    if len(sys.argv) > 3:
        with open(sys.argv[3]) as f:
            schema_override = json.load(f)

    schemas, all_rows = recover_database(db_path, schema_override)
    output = format_output(schemas, all_rows)

    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    n = (len(all_rows[None]) if schemas is None
         else sum(len(v) for v in all_rows.values()))
    print(f"Recovered {n} rows -> {out_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
