#!/usr/bin/env python3
"""
Generic SQLite raw-record recovery tool.

Reads a corrupted .db file, bypasses the SQL layer, and recovers records
by parsing B-tree leaf-page cell data directly from the binary image.

Usage:
    python3 recover_sqlite.py <db_file> <output_json> [--schema-hint COL1,COL2,...]

Output: JSON array of objects keyed by column name (inferred or hinted).
"""

import struct, sys, json, re, os, argparse, math
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


def varint_len(value):
    """Return how many bytes a varint-encoded value would occupy."""
    if value < 0:
        return 9
    if value < 0x80:
        return 1
    if value < 0x4000:
        return 2
    if value < 0x200000:
        return 3
    if value < 0x10000000:
        return 4
    if value < 0x800000000:
        return 5
    if value < 0x40000000000:
        return 6
    if value < 0x2000000000000:
        return 7
    if value < 0x100000000000000:
        return 8
    return 9


def serial_type_size(st):
    """Return the byte count consumed by a serial type."""
    if st == 0:
        return 0           # NULL
    if st == 1:
        return 1           # 8-bit signed integer
    if st == 2:
        return 2           # 16-bit big-endian signed integer
    if st == 3:
        return 3           # 24-bit big-endian signed integer  *** NOT 2 ***
    if st == 4:
        return 4           # 32-bit big-endian signed integer
    if st == 5:
        return 6           # 48-bit big-endian signed integer
    if st == 6:
        return 8           # 64-bit big-endian signed integer
    if st == 7:
        return 8           # IEEE-754 64-bit float
    if st in (8, 9):
        return 0           # constant 0 / 1
    if st >= 12:
        if st % 2 == 0:
            return (st - 12) // 2   # BLOB
        else:
            return (st - 13) // 2   # TEXT
    return -1              # reserved / unknown


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
        # 8-bit signed
        v = buf[offset]
        return (v if v < 128 else v - 256), 1
    elif st == 2:
        v = int.from_bytes(buf[offset:end], 'big', signed=True)
        return v, 2
    elif st == 3:
        v = int.from_bytes(buf[offset:end], 'big', signed=True)
        return v, 3
    elif st == 4:
        return int.from_bytes(buf[offset:end], 'big', signed=True), 4
    elif st == 5:
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
        'encoding': struct.unpack('>I', data[56:60])[0],
    }


def parse_page_header(data, page_offset, page_size):
    """Parse a B-tree page header. Returns dict or None.
    
    Handles corrupted page type bytes by checking if the page has
    a plausible cell pointer array.
    """
    p = page_offset
    ptype = data[p]

    # Standard page types: 2=interior index, 5=interior table,
    #                      10=leaf index, 13=leaf table
    valid_types = (2, 5, 10, 13)

    if ptype in valid_types:
        hdr_size = 12 if ptype in (2, 5) else 8
    else:
        # Page type byte may be corrupted by bit flip.
        # Check if any valid type is within 1-bit distance.
        fixed_type = None
        for vt in valid_types:
            if (ptype ^ vt) != 0 and bin(ptype ^ vt).count('1') <= 2:
                fixed_type = vt
                break
        if fixed_type is not None:
            ptype = fixed_type
            hdr_size = 12 if ptype in (2, 5) else 8
        else:
            return None

    num_cells = struct.unpack('>H', data[p + 3:p + 5])[0]
    cell_content = struct.unpack('>H', data[p + 5:p + 7])[0]
    if cell_content == 0:
        cell_content = page_size

    # Sanity: reject pages with implausible cell counts
    if num_cells == 0 or num_cells > 2000:
        return None

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
    page_end = page_offset + 65536
    for i in range(phdr['num_cells']):
        off = base + 2 * i
        if off + 2 > page_end or off + 2 > len(data):
            break
        ptrs.append(struct.unpack('>H', data[off:off + 2])[0])
    return ptrs


# ---------------------------------------------------------------------------
# Cell / record parsing
# ---------------------------------------------------------------------------

def compute_cell_extents(ptrs, page_size):
    """
    Compute (start, end) pairs for each cell pointer.
    
    Cell pointers in a leaf table page are stored in DESCENDING order
    in the pointer array.  Cell at ptrs[i] occupies bytes from ptrs[i]
    up to (but not including) ptrs[i-1].  The first entry (i==0, highest
    offset) extends to the end of the page.
    
    Returns list of (abs_start_offset_in_page, abs_end_offset_in_page)
    aligned with the ptrs list (same index order).
    """
    n = len(ptrs)
    extents = []
    for i in range(n):
        start = ptrs[i]
        if i == 0:
            end = page_size
        else:
            end = ptrs[i - 1]
        extents.append((start, end))
    return extents


def parse_cell(data, abs_start, abs_end):
    """
    Parse one cell from a leaf-table page.
    Returns dict with cell metadata and raw info.
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
        'prefix_len': size_len + rowid_len,  # bytes before the record
    }


def validate_record(cell):
    """
    Check whether the parsed cell has consistent serial types vs.
    available cell bytes.  Returns (ok, expected_content_bytes).
    
    The cell extent (abs_end - abs_start) must equal:
        prefix_len (payload_size varint + rowid varint) + payload_size
    
    And payload_size must equal:
        header_size + sum(serial_type_sizes)
    """
    serial_sizes = [serial_type_size(st) for st in cell['serial_types']]
    if any(s < 0 for s in serial_sizes):
        return False, -1
    
    expected_content = sum(serial_sizes)
    expected_payload = cell['header_size'] + expected_content
    expected_cell = cell['prefix_len'] + expected_payload
    actual_cell = cell['abs_end'] - cell['abs_start']
    
    return expected_cell == actual_cell, expected_content


def try_fix_record(cell, data):
    """
    When serial types don't match the cell extent, attempt repairs:
    
    1. Fix corrupted serial type bytes (single-bit flips)
    2. Fix corrupted header_size (single-bit flips)
    3. Use cell extent as ground truth for content size
    
    Returns (fixed_serial_types, fixed_header_size, corrected_payload_size)
    or None if unfixable.
    """
    actual_cell_size = cell['abs_end'] - cell['abs_start']
    content_bytes_available = actual_cell_size - cell['prefix_len']
    # content_bytes_available should equal payload_size (which may be corrupted)
    
    # Try fixing header_size first
    for hs_candidate in [cell['header_size']]:
        # Also try single-bit flips on header_size
        candidates = [hs_candidate]
        for bit in range(8):
            candidates.append(hs_candidate ^ (1 << bit))
        
        for hs in candidates:
            if hs < 1 or hs > content_bytes_available:
                continue
            
            # Re-parse serial types with this header_size
            record_start = cell['abs_start'] + cell['prefix_len']
            pos = record_start
            # Skip header_size varint
            _, pos = parse_varint(data, pos)
            
            serial_types = []
            hdr_limit = record_start + hs
            if hdr_limit > cell['abs_end']:
                continue
            while pos < hdr_limit:
                st, pos = parse_varint(data, pos)
                serial_types.append(st)
            
            if not serial_types:
                continue
            
            # Check if serial type sizes match body
            body_expected = sum(serial_type_size(st) for st in serial_types)
            if any(serial_type_size(st) < 0 for st in serial_types):
                continue
            
            body_available = content_bytes_available - hs
            if body_expected == body_available:
                return serial_types, hs, content_bytes_available
    
    # Try fixing individual serial types (keep original header_size)
    serial_types = list(cell['serial_types'])
    body_available = content_bytes_available - cell['header_size']
    
    # Calculate what sizes we need
    total = sum(serial_type_size(st) for st in serial_types)
    if total == body_available:
        return serial_types, cell['header_size'], content_bytes_available
    
    # Try single-bit flips on each serial type
    for idx in range(len(serial_types)):
        orig = serial_types[idx]
        for bit in range(8):
            candidate = orig ^ (1 << bit)
            sz = serial_type_size(candidate)
            if sz < 0:
                continue
            # Check if replacing this type fixes the total
            new_total = total - serial_type_size(orig) + sz
            if new_total == body_available:
                serial_types[idx] = candidate
                return serial_types, cell['header_size'], content_bytes_available
    
    # Last resort: infer serial types from available body bytes
    # Use the known column count from schema or hint
    return None


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
    for i in range(start, min(end, len(data))):
        b = data[i]
        if 0x20 <= b < 0x7F:
            current += bytes([b])
        else:
            if len(current) >= min_len:
                results.append((i - len(current), current.decode('ascii')))
            current = b''
    if len(current) >= min_len:
        results.append((min(end, len(data)) - len(current), current.decode('ascii')))
    return results


def try_extract_record_by_pattern(data, abs_start, abs_end):
    """
    Fallback: scan cell bytes for text/numeric patterns.
    
    Handles:
    - text key + integer/float value
    - multiple text fragments
    - integer-only records
    
    Returns list of values or None.
    """
    cell_data = data[abs_start:min(abs_end, len(data))]
    fragments = extract_text_fragments(data, abs_start, abs_end, min_len=4)
    
    if not fragments:
        # Try all-numeric: look for int/float patterns in cell body
        return _try_numeric_only(data, abs_start, abs_end)
    
    # For each text fragment, try to decode what follows
    best = None
    for frag_off, frag_text in fragments:
        after = frag_off + len(frag_text)
        remaining = abs_end - after
        
        # Try to decode remaining bytes as column values
        extra_values = _decode_trailing_values(data, after, abs_end)
        
        if extra_values is not None:
            values = [frag_text] + extra_values
            if best is None or len(frag_text) > len(str(best[0])):
                best = values
    
    return best


def _try_numeric_only(data, abs_start, abs_end):
    """Try to extract purely numeric values from cell body."""
    body = data[abs_start:min(abs_end, len(data))]
    if len(body) < 2:
        return None
    
    # Skip cell prefix (payload_size + rowid varints)
    pos = abs_start
    _, pos = parse_varint(data, pos)
    _, pos = parse_varint(data, pos)
    remaining = abs_end - pos
    
    if remaining == 8:
        # Could be a single float64
        val = struct.unpack('>d', data[pos:pos + 8])[0]
        if math.isfinite(val):
            return [val]
    elif remaining == 4:
        val = int.from_bytes(data[pos:pos + 4], 'big', signed=True)
        return [val]
    elif remaining >= 1 and remaining <= 8:
        val = int.from_bytes(data[pos:pos + remaining], 'big', signed=True)
        return [val]
    
    return None


def _decode_trailing_values(data, start, end):
    """Try to decode bytes from start..end as a sequence of typed values."""
    remaining = end - start
    if remaining <= 0:
        return []
    
    # Try float64 (8 bytes)
    if remaining >= 8:
        try:
            fval = struct.unpack('>d', data[start:start + 8])[0]
            if math.isfinite(fval):
                rest = _decode_trailing_values(data, start + 8, end)
                if rest is not None:
                    return [fval] + rest
        except Exception:
            pass
    
    # Try int (1-8 bytes, whatever remains)
    if remaining <= 8:
        val = int.from_bytes(data[start:start + remaining], 'big', signed=True)
        return [val]
    
    # Try single byte int + recurse
    if remaining > 1:
        val = data[start]
        rest = _decode_trailing_values(data, start + 1, end)
        if rest is not None:
            return [val] + rest
    
    return None


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------

def infer_column_names_from_schema_page(data, page_size):
    """
    Try to read CREATE TABLE statements from page 1 (schema table)
    to get column names and types.
    """
    cols = []
    col_types = []
    
    # Page 1 has a 100-byte file header before the B-tree page header.
    # Scan for CREATE TABLE text in the first two pages.
    scan_end = min(len(data), page_size * 2)
    text_runs = extract_text_fragments(data, 0, scan_end, min_len=10)
    
    for _, txt in text_runs:
        m = re.search(r'CREATE\s+TABLE\s+\w+\s*\((.+?)\)', txt, re.IGNORECASE)
        if m:
            col_defs = m.group(1).split(',')
            for cd in col_defs:
                parts = cd.strip().split()
                if parts:
                    cols.append(parts[0].strip('"\''))
                    if len(parts) > 1:
                        col_types.append(parts[1].strip('"\'').upper())
                    else:
                        col_types.append('TEXT')
    return cols, col_types


def infer_column_names_from_records(records, hint=None):
    """
    Given a list of recovered row tuples, infer column names.
    Each tuple is (rowid, [values...]).
    """
    if hint:
        return hint, ['TEXT'] * len(hint)

    col_count = Counter()
    for _, vals in records:
        col_count[len(vals)] += 1

    if not col_count:
        return ['col0'], ['TEXT']

    ncols = col_count.most_common(1)[0][0]
    names = [f'col{i}' for i in range(ncols)]
    types = ['TEXT'] * ncols
    return names, types


# ---------------------------------------------------------------------------
# Page 1 (schema table) cell parsing
# ---------------------------------------------------------------------------

def parse_schema_page(data, page_size):
    """
    Parse page 1 to extract schema info and any schema-table records.
    Page 1 has a 100-byte file header before the B-tree page header.
    """
    if len(data) < page_size:
        return None
    
    poff = 0
    btree_offset = 100  # file header size
    ptype = data[poff + btree_offset]
    
    if ptype not in (0x0D, 0x05):
        # Try bit-flip correction
        for vt in (13, 5):
            if bin(ptype ^ vt).count('1') <= 2:
                ptype = vt
                break
        else:
            return None
    
    if ptype == 0x0D:  # leaf table
        num_cells = struct.unpack('>H', data[poff + btree_offset + 3:poff + btree_offset + 5])[0]
        ptrs = []
        base = poff + btree_offset + 8
        for i in range(num_cells):
            off = base + 2 * i
            if off + 2 > len(data):
                break
            ptrs.append(struct.unpack('>H', data[off:off + 2])[0])
        return {'type': 'leaf', 'ptrs': ptrs, 'page_offset': poff}
    
    return None


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
        return _brute_force_recover(data, schema_hint)

    page_size = fh['page_size']
    records = []

    # First, try to get schema from page 1
    schema_info = parse_schema_page(data, page_size)
    col_names_from_schema, col_types_from_schema = infer_column_names_from_schema_page(data, page_size)
    
    # Determine expected column count from hint or schema
    expected_ncols = None
    if schema_hint:
        expected_ncols = len(schema_hint)
    elif col_names_from_schema:
        expected_ncols = len(col_names_from_schema)

    # Scan all pages (skip page 1 which is the schema table)
    for pg in range(fh['num_pages']):
        poff = pg * page_size
        if poff + 8 > len(data):
            break

        # Page 1 B-tree header starts at offset 100
        btree_off = 100 if pg == 0 else 0
        
        phdr = parse_page_header(data, poff + btree_off, page_size)
        if phdr is None or phdr['type'] != 13:
            continue  # skip non-leaf-table pages
        
        # Skip page 1 (schema table) for data recovery
        if pg == 0:
            continue

        ptrs = read_cell_pointers(data, poff + btree_off, phdr)
        if not ptrs:
            continue

        # Compute cell extents using pointer array order
        extents = compute_cell_extents(ptrs, page_size)

        for ci in range(len(ptrs)):
            cell_start_in_page, cell_end_in_page = extents[ci]
            abs_start = poff + cell_start_in_page
            abs_end = poff + cell_end_in_page

            if abs_start >= len(data):
                continue
            abs_end = min(abs_end, len(data))

            # Strategy 1: standard cell parse with validation
            try:
                cell = parse_cell(data, abs_start, abs_end)
                
                # Validate: do serial type sizes match cell extent?
                ok, expected_content = validate_record(cell)
                
                if ok:
                    values = decode_record(data, cell)
                    # Additional validation: check decoded values are reasonable
                    if _values_look_valid(values):
                        records.append((cell['rowid'], values))
                        continue
                
                # Try fixing corrupted serial types / header
                fix = try_fix_record(cell, data)
                if fix is not None:
                    fixed_types, fixed_hs, fixed_payload = fix
                    cell['serial_types'] = fixed_types
                    cell['header_size'] = fixed_hs
                    cell['content_start'] = cell['record_start'] + fixed_hs
                    values = decode_record(data, cell)
                    if _values_look_valid(values):
                        records.append((cell['rowid'], values))
                        continue
                
                # Even without validation, try decoding with corrected content size
                # Use cell extent to determine actual body size
                values = decode_record_with_extent(data, cell, abs_end)
                if values and _values_look_valid(values):
                    records.append((cell['rowid'], values))
                    continue
                    
            except Exception:
                pass

            # Strategy 2: pattern-based fallback
            extracted = try_extract_record_by_pattern(data, abs_start, abs_end)
            if extracted is not None and len(extracted) >= 1:
                # Re-parse rowid from cell prefix
                pos = abs_start
                _, pos = parse_varint(data, pos)
                rowid, _ = parse_varint(data, pos)
                records.append((rowid, extracted))

    # Deduplicate by rowid (keep first occurrence)
    seen_rowids = set()
    unique_records = []
    for rowid, vals in records:
        if rowid not in seen_rowids:
            seen_rowids.add(rowid)
            unique_records.append((rowid, vals))
    records = unique_records

    # Sort by rowid
    records.sort(key=lambda r: r[0])

    # Determine column names
    if col_names_from_schema:
        col_names = col_names_from_schema
        col_types = col_types_from_schema
    else:
        col_names, col_types = infer_column_names_from_records(records, schema_hint)

    # Build output
    output = []
    for rowid, vals in records:
        row = {}
        for i, v in enumerate(vals):
            cname = col_names[i] if i < len(col_names) else f'col{i}'
            row[cname] = v
        output.append(row)

    return output


def decode_record_with_extent(data, cell, abs_end):
    """
    Decode a record using cell extent as ground truth for body size,
    ignoring potentially corrupted payload_size.
    """
    serial_types = cell['serial_types']
    if not serial_types:
        return None
    
    # Try to use serial types directly
    offset = cell['content_start']
    values = []
    for st in serial_types:
        val, consumed = decode_serial_value(data, offset, st)
        values.append(val)
        offset += consumed
        # Stop if we've gone past the cell boundary
        if offset > abs_end:
            break
    
    # Check if we consumed all available bytes reasonably
    return values if values else None


def _values_look_valid(values):
    """Heuristic check that decoded values are reasonable."""
    if not values:
        return False
    
    has_meaningful = False
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            # Reject strings with control characters (except common ones)
            # that suggest corruption
            clean = all(0x20 <= ord(c) < 0x7F or c in '\t\n\r' for c in v)
            if clean and len(v.strip()) > 0:
                has_meaningful = True
            elif not clean:
                return False
        elif isinstance(v, (int, float)):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return False
            has_meaningful = True
        elif isinstance(v, bytes):
            has_meaningful = True
    
    return has_meaningful


def _brute_force_recover(data, schema_hint=None):
    """When the file header is too damaged, scan for record-like patterns."""
    results = []
    fragments = extract_text_fragments(data, 0, len(data), min_len=4)
    for frag_off, frag_text in fragments:
        after = frag_off + len(frag_text)
        if after + 8 <= len(data):
            try:
                fval = struct.unpack('>d', data[after:after + 8])[0]
                if math.isfinite(fval):
                    results.append((frag_off, [frag_text, fval]))
                    continue
            except Exception:
                pass
        if after + 1 <= len(data):
            results.append((frag_off, [frag_text, data[after]]))

    results.sort(key=lambda r: r[0])
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
