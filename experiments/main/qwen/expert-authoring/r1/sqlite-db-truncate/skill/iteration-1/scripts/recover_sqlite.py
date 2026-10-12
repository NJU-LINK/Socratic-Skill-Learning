#!/usr/bin/env python3
"""
Generic SQLite raw-record recovery tool.

Reads a corrupted .db file, bypasses the SQL layer, and recovers records
by parsing B-tree leaf-page cell data directly from the binary image.

Usage:
    python3 recover_sqlite.py <db_file> <output_json> [--schema-hint COL1,COL2,...]

Output: JSON array of objects keyed by column name (inferred or hinted).
"""

import struct, sys, json, re, os, argparse
from collections import Counter

# ---------------------------------------------------------------------------
# Varint helpers
# ---------------------------------------------------------------------------

def parse_varint(buf, offset, max_bytes=9):
    """Parse a SQLite varint. Returns (value, new_offset)."""
    result = 0
    for i in range(max_bytes):
        if offset + i >= len(buf):
            return result, offset + i
        b = buf[offset + i]
        if i < 8:
            result = (result << 7) | (b & 0x7F)
            if not (b & 0x80):
                return result, offset + i + 1
        else:  # 9th byte uses all 8 bits
            result = (result << 8) | b
            return result, offset + i + 1
    return result, offset + max_bytes


def serial_type_size(st):
    """Return the byte count consumed by a serial type, or -1 for NULL/const."""
    if st == 0:
        return 0
    if 1 <= st <= 6:
        return [0, 1, 2, 2, 4, 6, 8][st]  # st=3 → 2 bytes (but st=3 is int16)
    if st == 7:
        return 8  # IEEE-754 float64
    if st in (8, 9):
        return 0  # constant 0 / 1
    if st >= 12:
        if st % 2 == 0:
            return (st - 12) // 2  # blob
        else:
            return (st - 13) // 2  # text
    return -1


def decode_serial_value(buf, offset, st):
    """Decode one value given its serial type. Returns (value, bytes_consumed)."""
    sz = serial_type_size(st)
    if sz < 0:
        return None, 0
    end = offset + sz
    if end > len(buf):
        return None, sz

    if st == 0:
        return None, 0
    elif st == 1:
        return buf[offset], 1
    elif st == 2:
        return int.from_bytes(buf[offset:end], 'big'), 2
    elif st == 3:
        return int.from_bytes(buf[offset:end], 'big'), 2
    elif st == 4:
        return int.from_bytes(buf[offset:end], 'big', signed=True), 4
    elif st == 5:
        # 48-bit signed int
        raw = buf[offset:end]
        val = int.from_bytes(raw, 'big')
        if val >= (1 << 47):
            val -= (1 << 48)
        return val, 6
    elif st == 6:
        return int.from_bytes(buf[offset:end], 'big', signed=True), 8
    elif st == 7:
        return struct.unpack('>d', buf[offset:end])[0], 8
    elif st == 8:
        return 0, 0
    elif st == 9:
        return 1, 0
    elif st >= 12:
        raw = buf[offset:end]
        if st % 2 == 0:
            return raw, sz  # blob
        else:
            try:
                return raw.decode('utf-8'), sz
            except UnicodeDecodeError:
                return raw.decode('latin-1'), sz
    return None, sz


# ---------------------------------------------------------------------------
# Page-level parsing
# ---------------------------------------------------------------------------

def parse_file_header(data):
    """Parse the 100-byte SQLite file header."""
    if len(data) < 100 or data[:16] != b'SQLite format 3\0':
        return None
    page_size_raw = struct.unpack('>H', data[16:18])[0]
    page_size = 65536 if page_size_raw == 1 else page_size_raw
    return {
        'page_size': page_size,
        'write_version': data[18],
        'read_version': data[19],
        'num_pages': len(data) // page_size,
        'encoding': struct.unpack('>I', data[56:60])[0],  # 1=UTF8,2=UTF16le,3=UTF16be
    }


def parse_page_header(data, page_offset, page_size):
    """Parse a B-tree page header. Returns dict or None."""
    p = page_offset
    ptype = data[p]
    # ptype: 2=interior index, 5=interior table, 10=leaf index, 13=leaf table
    if ptype not in (2, 5, 10, 13):
        return None

    if ptype in (2, 5):  # interior
        hdr_size = 12
    else:
        hdr_size = 8

    num_cells = struct.unpack('>H', data[p + 3:p + 5])[0]
    cell_content = struct.unpack('>H', data[p + 5:p + 7])[0]
    if cell_content == 0:
        cell_content = page_size

    rightmost = None
    if ptype in (2, 5):
        rightmost = struct.unpack('>I', data[p + 8:p + 12])[0]

    return {
        'type': ptype,
        'hdr_size': hdr_size,
        'num_cells': num_cells,
        'cell_content': cell_content,
        'rightmost': rightmost,
    }


def read_cell_pointers(data, page_offset, phdr):
    """Read the cell pointer array from a B-tree page."""
    ptrs = []
    base = page_offset + phdr['hdr_size']
    for i in range(phdr['num_cells']):
        off = base + 2 * i
        if off + 2 > page_offset + 65536:
            break
        ptrs.append(struct.unpack('>H', data[off:off + 2])[0])
    return ptrs


# ---------------------------------------------------------------------------
# Cell / record parsing
# ---------------------------------------------------------------------------

def parse_cell(data, abs_start, abs_end):
    """
    Parse one cell from a leaf-table page.
    Returns dict with keys: payload_size, rowid, serial_types, content_start, abs_end
    """
    pos = abs_start
    payload_size, pos = parse_varint(data, pos)
    size_len = pos - abs_start
    rowid, pos = parse_varint(data, pos)
    rowid_len = pos - abs_start - size_len
    record_start = pos

    header_size, pos = parse_varint(data, pos)
    serial_types = []
    hdr_limit = record_start + header_size
    if hdr_limit > abs_end:
        hdr_limit = abs_end
    while pos < hdr_limit:
        st, pos = parse_varint(data, pos)
        serial_types.append(st)

    content_start = record_start + header_size

    return {
        'payload_size': payload_size,
        'rowid': rowid,
        'serial_types': serial_types,
        'content_start': content_start,
        'record_start': record_start,
        'header_size': header_size,
        'abs_start': abs_start,
        'abs_end': abs_end,
    }


def decode_record(data, cell):
    """
    Decode a record from cell info using serial types.
    Returns list of column values.
    """
    offset = cell['content_start']
    values = []
    for st in cell['serial_types']:
        val, consumed = decode_serial_value(data, offset, st)
        values.append(val)
        offset += consumed
    return values


# ---------------------------------------------------------------------------
# Fallback: pattern-based extraction
# ---------------------------------------------------------------------------

def extract_text_fragments(data, start, end, min_len=4):
    """Find all printable-ASCII runs of at least min_len bytes."""
    results = []
    current = b''
    for i in range(start, end):
        b = data[i]
        if 0x20 <= b < 0x7F:
            current += bytes([b])
        else:
            if len(current) >= min_len:
                results.append((i - len(current), current.decode('ascii')))
            current = b''
    if len(current) >= min_len:
        results.append((end - len(current), current.decode('ascii')))
    return results


def try_extract_record_by_pattern(data, abs_start, abs_end):
    """
    Fallback: scan cell bytes for a text key pattern and try to
    decode an adjacent numeric value (int or float64).
    Returns (text_value, numeric_value) or (None, None).
    """
    # Search for any text run that looks like a key
    fragments = extract_text_fragments(data, abs_start, abs_end, min_len=4)

    best = None
    for frag_off, frag_text in fragments:
        # Try to read a numeric value immediately after the text
        after = frag_off + len(frag_text)
        remaining = abs_end - after

        num_val = None
        if remaining >= 8:
            # Try float64 first
            try:
                fval = struct.unpack('>d', data[after:after + 8])[0]
                if not (fval != fval):  # not NaN
                    num_val = fval
            except Exception:
                pass
        if num_val is None and remaining >= 1:
            num_val = data[after]

        if num_val is not None:
            # Prefer longer text fragments (more likely the real key)
            if best is None or len(frag_text) > len(best[0]):
                best = (frag_text, num_val)

    return best if best else (None, None)


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------

def infer_column_names_from_schema_page(data, page_size):
    """
    Try to read CREATE TABLE statements from page 1 (schema table)
    to get column names.
    """
    cols = []
    # Scan for CREATE TABLE text
    text_runs = extract_text_fragments(data, 0, min(len(data), page_size * 2), min_len=10)
    for _, txt in text_runs:
        m = re.search(r'CREATE\s+TABLE\s+\w+\s*\((.+?)\)', txt, re.IGNORECASE)
        if m:
            col_defs = m.group(1).split(',')
            for cd in col_defs:
                parts = cd.strip().split()
                if parts:
                    cols.append(parts[0].strip('"\''))
    return cols


def infer_column_names_from_records(records, hint=None):
    """
    Given a list of recovered row tuples, infer column names.
    Each tuple is (rowid, [values...]).
    """
    if hint:
        return hint

    # Count columns across records
    col_count = Counter()
    for _, vals in records:
        col_count[len(vals)] += 1

    if not col_count:
        return ['col0']

    ncols = col_count.most_common(1)[0][0]
    names = []

    # Try to guess types for each column position
    for c in range(ncols):
        types_seen = Counter()
        for _, vals in records:
            if c < len(vals):
                v = vals[c]
                if isinstance(v, str):
                    types_seen['text'] += 1
                elif isinstance(v, float):
                    types_seen['float'] += 1
                elif isinstance(v, int):
                    types_seen['int'] += 1
                elif v is None:
                    types_seen['null'] += 1
                else:
                    types_seen['blob'] += 1
        names.append(f'col{c}')

    return names


# ---------------------------------------------------------------------------
# Main recovery pipeline
# ---------------------------------------------------------------------------

def recover(db_path, schema_hint=None):
    """
    Main entry point: recover records from a corrupted SQLite database.
    Returns list of dicts.
    """
    with open(db_path, 'rb') as f:
        data = f.read()

    if not data:
        return []

    fh = parse_file_header(data)
    if fh is None:
        # Header too corrupted; try brute-force text scanning
        return _brute_force_recover(data, schema_hint)

    page_size = fh['page_size']
    records = []

    # Scan all pages for leaf-table pages
    for pg in range(fh['num_pages']):
        poff = pg * page_size
        if poff + 8 > len(data):
            break

        phdr = parse_page_header(data, poff, page_size)
        if phdr is None or phdr['type'] != 13:
            continue  # skip non-leaf-table pages

        ptrs = read_cell_pointers(data, poff, phdr)
        if not ptrs:
            continue

        # Process each cell
        for ci in range(len(ptrs)):
            abs_start = poff + ptrs[ci]
            if ci == 0:
                abs_end = poff + page_size
            else:
                abs_end = poff + ptrs[ci - 1]

            if abs_start >= len(data):
                continue
            abs_end = min(abs_end, len(data))

            # Strategy 1: standard cell parse
            try:
                cell = parse_cell(data, abs_start, abs_end)
                values = decode_record(data, cell)
                # Validate: at least one string column
                if any(isinstance(v, str) and len(v) > 0 for v in values):
                    records.append((cell['rowid'], values))
                    continue
            except Exception:
                pass

            # Strategy 2: pattern-based fallback
            txt, num = try_extract_record_by_pattern(data, abs_start, abs_end)
            if txt is not None:
                # Re-parse rowid from cell prefix
                pos = abs_start
                _, pos = parse_varint(data, pos)
                rowid, _ = parse_varint(data, pos)
                records.append((rowid, [txt, num]))

    # Sort by rowid
    records.sort(key=lambda r: r[0])

    # Determine column names
    col_names = infer_column_names_from_schema_page(data, page_size)
    if not col_names:
        col_names = infer_column_names_from_records(records, schema_hint)

    # Build output
    output = []
    for rowid, vals in records:
        row = {}
        for i, v in enumerate(vals):
            cname = col_names[i] if i < len(col_names) else f'col{i}'
            row[cname] = v
        output.append(row)

    return output


def _brute_force_recover(data, schema_hint=None):
    """When the file header is too damaged, scan for record-like patterns."""
    # Try to find text + numeric pairs
    results = []
    fragments = extract_text_fragments(data, 0, len(data), min_len=4)
    for frag_off, frag_text in fragments:
        after = frag_off + len(frag_text)
        if after + 8 <= len(data):
            try:
                fval = struct.unpack('>d', data[after:after + 8])[0]
                if not (fval != fval):
                    results.append((frag_off, [frag_text, fval]))
                    continue
            except Exception:
                pass
        if after + 1 <= len(data):
            results.append((frag_off, [frag_text, data[after]]))

    results.sort(key=lambda r: r[0])
    # Deduplicate overlapping fragments
    deduped = []
    last_end = -1
    for off, vals in results:
        if off >= last_end:
            deduped.append(vals)
            last_end = off + len(vals[0])

    col_names = schema_hint or ['col0', 'col1']
    return [
        {col_names[i] if i < len(col_names) else f'col{i}': v
         for i, v in enumerate(row)}
        for row in deduped
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Recover records from corrupted SQLite DB')
    parser.add_argument('db_file', help='Path to corrupted .db file')
    parser.add_argument('output_json', help='Path for recovered JSON output')
    parser.add_argument('--schema-hint', default=None,
                        help='Comma-separated column names (e.g., word,value)')
    args = parser.parse_args()

    hint = args.schema_hint.split(',') if args.schema_hint else None
    records = recover(args.db_file, hint)

    with open(args.output_json, 'w') as f:
        json.dump(records, f, indent=2, default=str)

    print(f"Recovered {len(records)} records → {args.output_json}")


if __name__ == '__main__':
    main()
