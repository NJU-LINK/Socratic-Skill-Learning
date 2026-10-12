#!/usr/bin/env python3
"""
Recover rows from a corrupted SQLite database file.

Usage:
    python3 recover_sqlite.py <input.db> <output.json> [--schema-hint 'CREATE TABLE ...']

Handles: random bit flips, zeroed regions, truncated pages, damaged B-tree
headers.  Falls back to raw byte scanning when structural metadata is too
corrupted to parse normally.
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Varint helpers
# ---------------------------------------------------------------------------

def read_varint(buf: bytes, pos: int):
    """Read a SQLite varint. Returns (value, new_pos)."""
    result = 0
    for i in range(9):
        if pos >= len(buf):
            return result, pos
        b = buf[pos]
        pos += 1
        if i < 8:
            result = (result << 7) | (b & 0x7F)
            if b < 0x80:
                return result, pos
        else:
            result = (result << 8) | b
    return result, pos


def serial_type_body_size(st: int):
    """Return the number of body bytes implied by a serial type, or -1 if invalid."""
    if st == 0 or st == 8 or st == 9:
        return 0
    if 1 <= st <= 6:
        return [0, 1, 2, 3, 4, 6, 8][st]
    if st == 7:
        return 8
    if st >= 12 and st % 2 == 0:
        return (st - 12) // 2
    if st >= 13 and st % 2 == 1:
        return (st - 13) // 2
    return -1


# ---------------------------------------------------------------------------
# Record parsing
# ---------------------------------------------------------------------------

def parse_record(rec_bytes: bytes):
    """Parse SQLite record-format bytes → list of Python values, or None."""
    if not rec_bytes or rec_bytes[0] < 2:
        return None
    header_size = rec_bytes[0]
    if header_size > len(rec_bytes):
        return None

    hpos = 1
    serial_types = []
    while hpos < header_size:
        st, hpos = read_varint(rec_bytes, hpos)
        serial_types.append(st)

    dpos = header_size
    values = []
    for st in serial_types:
        bsz = serial_type_body_size(st)
        if bsz < 0:
            return None  # invalid serial type
        if dpos + bsz > len(rec_bytes):
            return None  # overflow
        if st == 0:
            values.append(None)
        elif st == 8:
            values.append(0)
        elif st == 9:
            values.append(1)
        elif 1 <= st <= 6:
            values.append(int.from_bytes(rec_bytes[dpos:dpos + bsz], 'big', signed=True))
        elif st == 7:
            values.append(struct.unpack('>d', rec_bytes[dpos:dpos + 8])[0])
        elif st >= 13 and st % 2 == 1:
            try:
                values.append(rec_bytes[dpos:dpos + bsz].decode('utf-8'))
            except UnicodeDecodeError:
                values.append(rec_bytes[dpos:dpos + bsz].decode('latin-1'))
        else:
            values.append(rec_bytes[dpos:dpos + bsz])  # blob
        dpos += bsz

    return values


# ---------------------------------------------------------------------------
# Serial-type correction (single-bit-flip repair)
# ---------------------------------------------------------------------------

def total_body_size(serial_types):
    """Sum of body bytes for a list of serial types. Returns -1 if any invalid."""
    total = 0
    for st in serial_types:
        bsz = serial_type_body_size(st)
        if bsz < 0:
            return -1
        total += bsz
    return total


def try_fix_serial_types(raw_types, expected_body):
    """
    Given a list of raw serial-type values and the expected total body size,
    return a corrected list (fixing single-bit flips), or None if unfixable.
    """
    # First check if already valid
    if total_body_size(raw_types) == expected_body:
        return list(raw_types)

    # Try fixing each position with a single-bit flip
    for idx in range(len(raw_types)):
        original = raw_types[idx]
        for bit in range(8):
            candidate = original ^ (1 << bit)
            if candidate == original:
                continue
            trial = list(raw_types)
            trial[idx] = candidate
            if total_body_size(trial) == expected_body:
                return trial

    # Try fixing with two-bit flips (rare but possible)
    for idx in range(len(raw_types)):
        original = raw_types[idx]
        for b1 in range(8):
            for b2 in range(b1 + 1, 8):
                candidate = original ^ (1 << b1) ^ (1 << b2)
                if candidate == original:
                    continue
                trial = list(raw_types)
                trial[idx] = candidate
                if total_body_size(trial) == expected_body:
                    return trial

    return None


# ---------------------------------------------------------------------------
# SQLite file-level parsing
# ---------------------------------------------------------------------------

def read_file_header(data: bytes):
    """Extract basic info from the 100-byte database header."""
    if len(data) < 100:
        return None
    magic = data[:16]
    if not magic.startswith(b'SQLite format 3'):
        return None
    ps_raw = int.from_bytes(data[16:18], 'big')
    page_size = 65536 if ps_raw == 1 else ps_raw
    page_count = len(data) // page_size
    return {
        'page_size': page_size,
        'page_count': page_count,
        'encoding': 'utf-8',  # default; could parse offset 56 for details
    }


def parse_btree_page_header(page: bytes, is_page1: bool = False):
    """Parse the B-tree page header at the start of *page* (or offset 100 for page 1)."""
    offset = 100 if is_page1 else 0
    if offset + 8 > len(page):
        return None
    flags = page[offset]
    if flags not in (0x02, 0x05, 0x0a, 0x0d):
        return None
    freeblock = int.from_bytes(page[offset + 1:offset + 3], 'big')
    num_cells = int.from_bytes(page[offset + 3:offset + 5], 'big')
    content_offset = int.from_bytes(page[offset + 5:offset + 7], 'big')
    frag_bytes = page[offset + 7]
    hdr_size = 12 if flags in (0x02, 0x05) else 8
    return {
        'flags': flags,
        'freeblock': freeblock,
        'num_cells': num_cells,
        'content_offset': content_offset,
        'frag_bytes': frag_bytes,
        'hdr_size': hdr_size,
        'cell_ptr_start': offset + hdr_size,
    }


def get_cell_pointers(page: bytes, hdr: dict):
    """Read the cell pointer array."""
    ptrs = []
    base = hdr['cell_ptr_start']
    for i in range(hdr['num_cells']):
        off = base + i * 2
        if off + 2 > len(page):
            break
        ptrs.append(int.from_bytes(page[off:off + 2], 'big'))
    return ptrs


def parse_cell(page: bytes, ptr: int):
    """Parse a single cell starting at page-relative offset *ptr*.
    Returns (payload_size, rowid, record_bytes) or None.
    """
    if ptr >= len(page):
        return None
    payload_size, pos = read_varint(page, ptr)
    rowid, pos = read_varint(page, pos)
    record = page[pos:pos + payload_size]
    if len(record) < payload_size:
        # Pad with zeros if truncated
        record = record + b'\x00' * (payload_size - len(record))
    return payload_size, rowid, record


def parse_schema_from_master(page1: bytes):
    """
    Try to parse sqlite_master from page 1 to extract CREATE TABLE statements.
    Returns a list of dicts: {name, rootpage, sql}.
    Uses recover_cell so that corrupted serial types in the master table
    are corrected the same way as data-table cells.
    """
    hdr = parse_btree_page_header(page1, is_page1=True)
    if hdr is None:
        # Fallback: scan for CREATE TABLE in raw bytes
        return _scan_schema_fallback(page1)
    ptrs = get_cell_pointers(page1, hdr)
    schemas = []
    # sqlite_master always has 5 columns: type, name, tbl_name, rootpage, sql
    for ptr in ptrs:
        result = recover_cell(page1, ptr, num_cols=5)
        if result is None:
            continue
        rowid, vals = result
        if len(vals) >= 5 and isinstance(vals[4], str) and 'CREATE' in vals[4].upper():
            schemas.append({
                'type': vals[0],
                'name': vals[1],
                'tbl_name': vals[2],
                'rootpage': vals[3],
                'sql': vals[4],
            })
    if not schemas:
        return _scan_schema_fallback(page1)
    return schemas


def _scan_schema_fallback(data: bytes):
    """Fallback: search for CREATE TABLE statements in raw bytes."""
    schemas = []
    for m in re.finditer(rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', data):
        tbl_name = m.group(1).decode('utf-8', errors='replace')
        sql = m.group(0).decode('utf-8', errors='replace')
        schemas.append({
            'type': 'table',
            'name': tbl_name,
            'tbl_name': tbl_name,
            'rootpage': 2,  # default guess
            'sql': sql,
        })
    return schemas


def parse_create_table(sql: str):
    """Extract column names and affinities from a CREATE TABLE statement."""
    m = re.match(r'CREATE\s+TABLE\s+\S+\s*\((.*)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    cols = []
    for part in re.split(r',', body):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].strip('"').strip("'").strip('`')
        affinity = tokens[1].upper() if len(tokens) > 1 else 'BLOB'
        # Simplify affinity
        if 'INT' in affinity:
            affinity = 'INTEGER'
        elif 'REAL' in affinity or 'FLOA' in affinity or 'DOUB' in affinity:
            affinity = 'REAL'
        elif 'TEXT' in affinity or 'CHAR' in affinity or 'CLOB' in affinity:
            affinity = 'TEXT'
        elif 'BLOB' in affinity:
            affinity = 'BLOB'
        cols.append({'name': name, 'affinity': affinity})
    return cols


# ---------------------------------------------------------------------------
# Cell recovery with serial-type correction
# ---------------------------------------------------------------------------

def recover_cell(page: bytes, ptr: int, num_cols: int):
    """
    Attempt to recover a cell, correcting single-bit-flip corruption in
    serial-type bytes.  Returns (rowid, values_list) or None.
    """
    cell = parse_cell(page, ptr)
    if cell is None:
        return None
    payload_size, rowid, record = cell
    if not record or record[0] < 2:
        return None

    header_size = record[0]
    if header_size > len(record):
        return None

    # Read raw serial types
    hpos = 1
    raw_types = []
    while hpos < header_size:
        st, hpos = read_varint(record, hpos)
        raw_types.append(st)

    if not raw_types:
        return None

    expected_body = payload_size - header_size

    # Try to fix serial types
    fixed = try_fix_serial_types(raw_types, expected_body)
    if fixed is None:
        return None

    # Build a corrected record and parse
    new_header = bytes([header_size])
    for st in fixed:
        # Re-encode as varint (most types fit in one byte)
        if st < 0x80:
            new_header += bytes([st])
        else:
            # Multi-byte varint encoding
            parts = []
            val = st
            while val > 0:
                parts.append(val & 0x7F)
                val >>= 7
            parts.reverse()
            for j, p in enumerate(parts):
                if j < len(parts) - 1:
                    new_header += bytes([p | 0x80])
                else:
                    new_header += bytes([p])

    corrected_record = new_header + record[header_size:]
    values = parse_record(corrected_record)
    if values is None:
        return None

    return rowid, values


# ---------------------------------------------------------------------------
# Fallback: scan for records in raw bytes
# ---------------------------------------------------------------------------

def scan_for_records(data: bytes, page_start: int, page_end: int, num_cols: int,
                     known_prefixes=None):
    """
    Brute-force scan a region for plausible SQLite records.
    Yields (rowid_guess, values) for each record found.
    """
    known_prefixes = known_prefixes or []
    pos = page_start
    while pos < page_end - 4:
        # Try to interpret data[pos:] as a cell
        payload_size, p2 = read_varint(data, pos)
        if payload_size < 3 or payload_size > 4000:
            pos += 1
            continue
        rowid, p3 = read_varint(data, p2)
        if rowid < 1 or rowid > 10_000_000:
            pos += 1
            continue
        record = data[p3:p3 + payload_size]
        if len(record) < 3:
            pos += 1
            continue
        header_size = record[0]
        if header_size < 2 or header_size > payload_size:
            pos += 1
            continue

        # Read serial types
        hpos = 1
        raw_types = []
        while hpos < header_size:
            st, hpos = read_varint(record, hpos)
            raw_types.append(st)

        if len(raw_types) != num_cols:
            pos += 1
            continue

        expected_body = payload_size - header_size
        fixed = try_fix_serial_types(raw_types, expected_body)
        if fixed is None:
            pos += 1
            continue

        # Check text prefixes
        new_header = bytes([header_size] + [st if st < 0x80 else st for st in fixed])
        corrected = new_header + record[header_size:]
        values = parse_record(corrected)
        if values is None:
            pos += 1
            continue

        # If we have known prefixes, check that text values match
        if known_prefixes:
            match = False
            for v in values:
                if isinstance(v, str):
                    for pfx in known_prefixes:
                        if v.startswith(pfx) or pfx in v:
                            match = True
                            break
            if not match:
                pos += 1
                continue

        yield rowid, values
        pos += payload_size + (p3 - pos)  # skip past this record


# ---------------------------------------------------------------------------
# Main recovery pipeline
# ---------------------------------------------------------------------------

def recover(db_path: str, schema_hint: str = None):
    """Recover rows from a corrupted SQLite database."""
    data = Path(db_path).read_bytes()
    fhdr = read_file_header(data)
    if fhdr is None:
        print("ERROR: Not a valid SQLite file", file=sys.stderr)
        return []

    page_size = fhdr['page_size']
    page_count = fhdr['page_count']
    print(f"File: {db_path}, page_size={page_size}, pages={page_count}",
          file=sys.stderr)

    # --- Step 1: Get schema ---
    columns = []
    table_name = None
    root_pages = []

    if schema_hint:
        columns = parse_create_table(schema_hint)
        # Try to extract table name
        m = re.match(r'CREATE\s+TABLE\s+(\S+)', schema_hint, re.IGNORECASE)
        if m:
            table_name = m.group(1).strip('"').strip("'").strip('`')
    else:
        # Try to parse sqlite_master from page 1
        page1 = data[:page_size]
        schemas = parse_schema_from_master(page1)
        for s in schemas:
            if s['type'] == 'table' and not s['name'].startswith('sqlite_'):
                table_name = s['name']
                columns = parse_create_table(s['sql'])
                rp = s['rootpage']
                if isinstance(rp, int) and rp > 0:
                    root_pages.append(rp)
                break

    if not columns:
        print("ERROR: Could not determine schema", file=sys.stderr)
        return []

    num_cols = len(columns)
    col_names = [c['name'] for c in columns]
    print(f"Table: {table_name}, columns: {col_names}", file=sys.stderr)

    # --- Step 2: Determine which pages to scan ---
    if not root_pages:
        # Assume data starts on page 2
        root_pages = list(range(2, page_count + 1))

    all_rows = []
    seen_rowids = set()

    for pg_num in root_pages:
        pg_start = (pg_num - 1) * page_size
        pg_end = pg_start + page_size
        if pg_end > len(data):
            pg_end = len(data)
        page = data[pg_start:pg_end]

        # Try structured parsing first
        hdr = parse_btree_page_header(page, is_page1=(pg_num == 1))
        if hdr and hdr['flags'] == 0x0d:
            ptrs = get_cell_pointers(page, hdr)
            for ptr in ptrs:
                result = recover_cell(page, ptr, num_cols)
                if result:
                    rowid, values = result
                    if rowid not in seen_rowids and len(values) == num_cols:
                        seen_rowids.add(rowid)
                        all_rows.append((rowid, values))

        # Also scan the entire page for records that might be outside
        # the cell-pointer array (e.g., if pointers are corrupted)
        content_start = 0
        if hdr:
            content_start = hdr.get('content_offset', 0)
        for rowid, values in scan_for_records(
                page, 0, len(page), num_cols,
                known_prefixes=[]):
            if rowid not in seen_rowids and len(values) == num_cols:
                seen_rowids.add(rowid)
                all_rows.append((rowid, values))

    # Sort by rowid
    all_rows.sort(key=lambda x: x[0])

    # Build result dicts
    result = []
    for rowid, values in all_rows:
        row = {}
        for i, col in enumerate(columns):
            if i < len(values):
                row[col['name']] = values[i]
            else:
                row[col['name']] = None
        result.append(row)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Recover rows from corrupted SQLite DB')
    parser.add_argument('input', help='Path to corrupted .db file')
    parser.add_argument('output', help='Path to write recovered JSON')
    parser.add_argument('--schema-hint', default=None,
                        help='CREATE TABLE statement if schema cannot be parsed')
    args = parser.parse_args()

    rows = recover(args.input, args.schema_hint)
    print(f"Recovered {len(rows)} rows", file=sys.stderr)

    with open(args.output, 'w') as f:
        json.dump(rows, f, indent=2)
    print(f"Written to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
