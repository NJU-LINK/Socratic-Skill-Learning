#!/usr/bin/env python3
"""
SQLite Database Corruption Recovery Tool

Recovers records from damaged SQLite database files by parsing the raw
binary format directly. Handles bit flips, zeroed regions, and corrupted
page headers.

Usage:
    python3 recover_sqlite.py <db_path> <output_json_path> [--schema 'schema_hint']

The schema hint is optional and helps identify column names when the
sqlite_master table is also corrupted.
"""

import struct
import json
import sys
import os


def read_varint(data, offset):
    """Read SQLite varint from data at offset. Returns (value, new_offset)."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, offset + i
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80:
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset


def serial_type_body_size(st):
    """Return body byte count for serial type, or -1 if unknown."""
    if st == 0: return 0
    elif st == 1: return 1
    elif st == 2: return 2
    elif st == 3: return 3
    elif st == 4: return 4
    elif st == 5: return 6
    elif st == 6: return 8
    elif st == 7: return 8
    elif st in (8, 9): return 0
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1


def decode_value(data, offset, st):
    """Decode a value from data at offset given serial type."""
    if st == 0: return None
    elif st == 1: return struct.unpack('>b', data[offset:offset+1])[0]
    elif st == 2: return struct.unpack('>h', data[offset:offset+2])[0]
    elif st == 3:
        b = data[offset:offset+3]
        v = (b[0] << 16) | (b[1] << 8) | b[2]
        return v - 0x1000000 if v >= 0x800000 else v
    elif st == 4: return struct.unpack('>i', data[offset:offset+4])[0]
    elif st == 5: return int.from_bytes(data[offset:offset+6], 'big', signed=True)
    elif st == 6: return struct.unpack('>q', data[offset:offset+8])[0]
    elif st == 7: return struct.unpack('>d', data[offset:offset+8])[0]
    elif st == 8: return 0
    elif st == 9: return 1
    elif st >= 12 and st % 2 == 0:
        blen = (st - 12) // 2
        return data[offset:offset+blen]
    elif st >= 13 and st % 2 == 1:
        tlen = (st - 13) // 2
        return data[offset:offset+tlen].decode('utf-8', errors='replace')
    return None


def parse_record(payload):
    """Parse SQLite record payload. Returns (serial_types, values) or (types, None) on corruption."""
    if len(payload) < 1:
        return None, None
    header_size, hoff = read_varint(payload, 0)
    if header_size > len(payload) or header_size < 1:
        return None, None
    serial_types = []
    while hoff < header_size:
        st, hoff = read_varint(payload, hoff)
        serial_types.append(st)
    total_body = sum(serial_type_body_size(st) for st in serial_types)
    if total_body < 0 or header_size + total_body > len(payload):
        return serial_types, None
    body_off = header_size
    values = []
    for st in serial_types:
        values.append(decode_value(payload, body_off, st))
        body_off += serial_type_body_size(st)
    return serial_types, values


def parse_record_with_types(payload, serial_types):
    """Try to parse a record with given serial types. Returns values or None."""
    header_size, hoff = read_varint(payload, 0)
    if header_size > len(payload):
        return None
    
    body_off = header_size
    values = []
    
    for st in serial_types:
        sz = serial_type_body_size(st)
        if sz < 0 or body_off + sz > len(payload):
            return None
        
        try:
            val = decode_value(payload, body_off, st)
            values.append(val)
            body_off += sz
        except:
            return None
    
    # Validate: text should be valid UTF-8 and look reasonable
    for val in values:
        if isinstance(val, str):
            try:
                val.encode('utf-8')
                # Check for obviously invalid text (all control chars, etc.)
                if val and all(ord(c) < 32 for c in val):
                    return None
            except:
                return None
    
    return values


def try_fix_serial_types(serial_types, payload, expected_types=None):
    """Try to fix corrupted serial types.
    
    Strategy:
    1. Try single-bit flips (fast, handles most common corruption)
    2. If that fails, try brute-force: iterate through valid serial type values
    3. Validate that corrected types produce consistent parses
    """
    header_size, _ = read_varint(payload, 0)
    
    # First pass: try single-bit flips (fast path)
    for i, st in enumerate(serial_types):
        sz = serial_type_body_size(st)
        if sz < 0 or sz > len(payload):
            # Try flipping individual bits
            for bit in range(8):
                fixed = st ^ (1 << bit)
                fixed_sz = serial_type_body_size(fixed)
                if fixed_sz >= 0:
                    test_types = serial_types[:i] + [fixed] + serial_types[i+1:]
                    total = sum(serial_type_body_size(s) for s in test_types)
                    if total >= 0 and header_size + total <= len(payload):
                        # Verify all other types are also valid
                        all_valid = all(serial_type_body_size(s) >= 0 for s in test_types)
                        if all_valid:
                            return test_types
    
    # Second pass: brute-force search with exact-fit heuristic
    # Try each corrupted position with all possible values
    for i, st in enumerate(serial_types):
        sz = serial_type_body_size(st)
        if sz < 0 or sz > len(payload):
            # This position is corrupted, try all possible values
            best_types = None
            best_waste = len(payload)  # worst case
            best_score = -1  # prefer text > blob > other
            
            for candidate in range(256):
                candidate_sz = serial_type_body_size(candidate)
                if candidate_sz < 0:
                    continue
                
                test_types = serial_types[:i] + [candidate] + serial_types[i+1:]
                total = sum(serial_type_body_size(s) for s in test_types)
                waste = len(payload) - header_size - total
                
                if waste < 0:
                    continue  # body too large
                
                all_valid = all(serial_type_body_size(s) >= 0 for s in test_types)
                if not all_valid:
                    continue
                
                # Calculate a score for tiebreaking (prefer text over blob)
                score = 0
                if candidate >= 13 and candidate % 2 == 1:  # text
                    score = 2
                elif candidate >= 12 and candidate % 2 == 0:  # blob
                    score = 1
                
                if waste == 0:  # exact fit
                    if score > best_score or (score == best_score and best_types is None):
                        try:
                            parsed = parse_record_with_types(payload, test_types)
                            if parsed is not None:
                                best_types = test_types
                                best_waste = waste
                                best_score = score
                        except:
                            continue
                elif waste < best_waste:
                    try:
                        parsed = parse_record_with_types(payload, test_types)
                        if parsed is not None:
                            best_types = test_types
                            best_waste = waste
                            best_score = score
                    except:
                        continue
            
            if best_types is not None:
                return best_types
    
    return serial_types


def parse_column_names(sql):
    """Extract column names from a CREATE TABLE SQL statement (possibly truncated)."""
    import re
    match = re.search(r'\((.*)', sql, re.IGNORECASE)
    if not match:
        return []
    cols_str = match.group(1)
    cols = []
    for part in cols_str.split(','):
        part = part.strip()
        if part:
            col_name = part.split()[0].strip('"`\'[]')
            # Skip table constraints
            if col_name.upper() not in ('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT'):
                cols.append(col_name)
    return cols


def extract_schema(data, page_size):
    """Extract table definitions from page 1 (sqlite_master).
    
    Returns list of dicts: {name, rootpage, sql, columns}
    """
    page = data[0:page_size]
    hdr_off = 100  # page 1 B-tree header starts after file header
    
    page_type = page[hdr_off]
    if page_type != 0x0d:
        return []
    
    cell_count = int.from_bytes(page[hdr_off+3:hdr_off+5], 'big')
    tables = []
    
    for i in range(cell_count):
        ptr_off = hdr_off + 8 + i * 2
        if ptr_off + 2 > len(page):
            break
        cell_ptr = int.from_bytes(page[ptr_off:ptr_off+2], 'big')
        abs_off = cell_ptr  # page 1 starts at offset 0
        
        payload_size, next_off = read_varint(data, abs_off)
        rowid, payload_start = read_varint(data, next_off)
        
        # Handle overflow for schema records
        payload = read_payload_with_overflow(data, payload_start, payload_size, page_size, 1)
        if payload is None:
            continue
        
        serial_types, values = parse_record(payload)
        if values is not None and len(values) >= 5:
            # sqlite_master columns: type, name, tbl_name, rootpage, sql
            obj_type = values[0]
            obj_name = values[1]
            tbl_name = values[2]
            rootpage = values[3]
            sql = values[4] if len(values) > 4 else ''
            
            if isinstance(obj_type, str) and obj_type.lower() == 'table':
                columns = parse_column_names(sql if isinstance(sql, str) else '')
                tables.append({
                    'name': tbl_name if isinstance(tbl_name, str) else obj_name,
                    'rootpage': rootpage if isinstance(rootpage, int) else 0,
                    'sql': sql if isinstance(sql, str) else '',
                    'columns': columns
                })
    
    return tables


def calculate_overflow_thresholds(page_size):
    """Calculate U (max local payload) and M (min local payload) for overflow."""
    U = page_size - 35
    M = ((U - 12) * 32 // 255) - 23
    return U, M


def read_payload_with_overflow(data, payload_start, payload_size, page_size, page_num):
    """Read payload, handling overflow pages if necessary.
    
    The local payload extends from payload_start to the end of the page.
    If payload_size > local_payload_length, overflow pages are used.
    The last 4 bytes of the local payload are the overflow page pointer.
    
    Returns the full payload bytes, or None if overflow chain is broken.
    """
    # Calculate the end of the current page
    page_end = page_num * page_size
    
    # Local payload: from payload_start to end of page
    local_payload = data[payload_start:page_end]
    local_payload_len = len(local_payload)
    
    # No overflow needed
    if payload_size <= local_payload_len:
        return data[payload_start:payload_start + payload_size]
    
    # Overflow case: local payload includes the 4-byte overflow pointer at the end
    if local_payload_len < 4:
        return None
    
    # Extract overflow page number from last 4 bytes of local payload
    overflow_page_num = int.from_bytes(local_payload[-4:], 'big')
    
    # Local data is everything except the last 4 bytes
    local_data = local_payload[:-4]
    
    # Start building full payload
    full_payload = local_data
    bytes_remaining = payload_size - len(local_data)
    current_page = overflow_page_num
    
    # Follow overflow page chain
    while bytes_remaining > 0 and current_page > 0:
        # Overflow page structure: 4-byte next pointer + (page_size - 4) bytes of data
        page_offset = (current_page - 1) * page_size
        if page_offset + page_size > len(data):
            break  # Invalid page number
        
        # Read next page pointer
        next_page = int.from_bytes(data[page_offset:page_offset+4], 'big')
        
        # Read data from this overflow page
        page_data = data[page_offset+4:page_offset+page_size]
        bytes_available = min(len(page_data), bytes_remaining)
        full_payload += page_data[:bytes_available]
        
        bytes_remaining -= bytes_available
        current_page = next_page
    
    if bytes_remaining > 0:
        # Overflow chain incomplete
        return None
    
    return full_payload


def recover_from_page_via_pointers(data, page_num, page_size):
    """Recover records from a page using the cell pointer array."""
    page_start = (page_num - 1) * page_size
    page = data[page_start:page_start + page_size]
    hdr_off = 100 if page_num == 1 else 0
    
    page_type = page[hdr_off]
    if page_type != 0x0d:
        return []
    
    cell_count = int.from_bytes(page[hdr_off+3:hdr_off+5], 'big')
    if cell_count == 0 or cell_count > 10000:
        return []
    
    records = []
    for i in range(cell_count):
        ptr_off = hdr_off + 8 + i * 2
        if ptr_off + 2 > len(page):
            break
        cell_ptr = int.from_bytes(page[ptr_off:ptr_off+2], 'big')
        abs_off = page_start + cell_ptr
        
        if abs_off >= len(data):
            continue
        
        payload_size, next_off = read_varint(data, abs_off)
        if payload_size < 1 or payload_size > len(data):
            continue
        rowid, payload_start = read_varint(data, next_off)
        
        # Read payload with overflow handling
        payload = read_payload_with_overflow(data, payload_start, payload_size, page_size, page_num)
        if payload is None:
            continue
        
        serial_types, values = parse_record(payload)
        
        if values is None and serial_types is not None:
            fixed_types = try_fix_serial_types(serial_types, payload)
            if fixed_types != serial_types:
                header_size, hoff = read_varint(payload, 0)
                body_off = header_size
                values = []
                for st in fixed_types:
                    values.append(decode_value(payload, body_off, st))
                    body_off += serial_type_body_size(st)
        
        if values is not None:
            records.append((rowid, serial_types or [], values))
    
    return records


def recover_from_page_via_scanning(data, page_num, page_size, expected_columns=2):
    """Fallback: recover records by scanning page content area."""
    page_start = (page_num - 1) * page_size
    page_end = page_start + page_size
    records = []
    found_offsets = set()
    
    offset = page_end - 1
    while offset >= page_start:
        payload_size, next_off = read_varint(data, offset)
        if payload_size < 3 or payload_size > len(data):  # Guard against corrupted varints
            offset -= 1
            continue
        rowid, payload_start = read_varint(data, next_off)
        if rowid < 0 or rowid > 10000000:
            offset -= 1
            continue
        
        # Read payload with overflow handling
        payload = read_payload_with_overflow(data, payload_start, payload_size, page_size, page_num)
        if payload is None:
            offset -= 1
            continue
        
        serial_types, values = parse_record(payload)
        
        if values is None and serial_types is not None:
            fixed_types = try_fix_serial_types(serial_types, payload)
            if fixed_types != serial_types:
                header_size, hoff = read_varint(payload, 0)
                body_off = header_size
                values = []
                for st in fixed_types:
                    values.append(decode_value(payload, body_off, st))
                    body_off += serial_type_body_size(st)
        
        if values is not None and len(values) >= expected_columns:
            # Reject all-NULL records — almost certainly false positives from scanning
            if all(v is None for v in values):
                offset -= 1
                continue
            if offset not in found_offsets:
                found_offsets.add(offset)
                records.append((rowid, serial_types or [], values))
        
        offset -= 1
    
    return records


def find_leaf_pages(data, root_page, page_size):
    """Traverse B-tree from root page to find all leaf table pages.
    
    Returns list of page numbers (1-indexed) that are leaf table pages.
    Handles both leaf (0x0D) and interior (0x0A) table B-tree pages.
    """
    leaf_pages = []
    pages_to_visit = [root_page]
    visited = set()
    
    while pages_to_visit:
        page_num = pages_to_visit.pop(0)
        if page_num in visited or page_num < 1:
            continue
        visited.add(page_num)
        
        page_start = (page_num - 1) * page_size
        if page_start + page_size > len(data):
            continue
        
        page = data[page_start:page_start + page_size]
        
        # Page 1 has 100-byte file header before B-tree header
        hdr_off = 100 if page_num == 1 else 0
        page_type = page[hdr_off]
        
        if page_type == 0x0d:  # Leaf table B-tree
            leaf_pages.append(page_num)
        elif page_type == 0x0a:  # Interior table B-tree
            cell_count = int.from_bytes(page[hdr_off+3:hdr_off+5], 'big')
            # Rightmost child pointer is at bytes 8-11 of header
            rightmost = int.from_bytes(page[hdr_off+8:hdr_off+12], 'big')
            
            # Cell pointer array starts at hdr_off + 12 for interior pages
            for i in range(cell_count):
                ptr_off = hdr_off + 12 + i * 2
                if ptr_off + 2 > len(page):
                    break
                cell_ptr = int.from_bytes(page[ptr_off:ptr_off+2], 'big')
                abs_off = page_start + cell_ptr
                # Interior cell: 4-byte left child page number + varint rowid
                if abs_off + 4 <= len(data):
                    left_child = int.from_bytes(data[abs_off:abs_off+4], 'big')
                    if 0 < left_child <= len(data) // page_size:
                        pages_to_visit.append(left_child)
            
            # Add rightmost child
            if 0 < rightmost <= len(data) // page_size:
                pages_to_visit.append(rightmost)
    
    return sorted(leaf_pages)


def recover_database(db_path):
    """Main recovery: returns list of (rowid, serial_types, values) tuples and table info."""
    data = open(db_path, 'rb').read()
    
    if len(data) < 100:
        raise ValueError("File too small to be a SQLite database")
    
    if data[0:16] != b'SQLite format 3\x00':
        raise ValueError("Not a SQLite database (bad magic)")
    
    page_size = int.from_bytes(data[16:18], 'big')
    if page_size == 1:
        page_size = 65536  # SQLite spec: 1 means 65536
    total_pages = len(data) // page_size
    
    # Extract schema (now returns structured table info)
    tables = extract_schema(data, page_size)
    
    all_records = []
    
    if tables:
        # Multi-table mode: traverse each table's B-tree
        for table in tables:
            root_page = table['rootpage']
            if root_page < 1 or root_page > total_pages:
                continue
            
            # Find all leaf pages for this table
            leaf_pages = find_leaf_pages(data, root_page, page_size)
            
            for page_num in leaf_pages:
                # Try pointer-based recovery first
                records = recover_from_page_via_pointers(data, page_num, page_size)
                
                # If pointer array seems wrong, try scanning
                if not records:
                    records = recover_from_page_via_scanning(data, page_num, page_size)
                
                # Tag records with table info
                for rowid, stypes, values in records:
                    all_records.append((rowid, stypes, values, table))
    else:
        # Fallback: scan all pages (old behavior)
        for page_num in range(2, total_pages + 1):
            records = recover_from_page_via_pointers(data, page_num, page_size)
            if not records:
                records = recover_from_page_via_scanning(data, page_num, page_size)
            for rowid, stypes, values in records:
                all_records.append((rowid, stypes, values, None))
    
    all_records.sort(key=lambda x: x[0])
    return all_records, tables


def format_value_for_json(val, serial_type=None):
    """Convert a Python value to JSON-compatible form.
    
    Args:
        val: The decoded value
        serial_type: The original SQLite serial type (for type preservation)
    """
    if val is None:
        return None
    elif isinstance(val, bytes):
        return val.hex()
    elif isinstance(val, float):
        # Preserve float type if it was stored as IEEE 754 (serial type 7)
        # even if the value is integer-valued
        if serial_type == 7:
            return val  # Keep as float
        # For other cases, convert integer-valued floats to int
        if val == int(val) and abs(val) < 2**53:
            return int(val)
        return val
    return val


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_path> <output_json> [column_names...]")
        print("  column_names: optional comma-separated column names")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    column_names = sys.argv[3].split(',') if len(sys.argv) > 3 else None
    
    records, tables = recover_database(db_path)
    
    if tables:
        for t in tables:
            print(f"Found table: {t['name']} (root page {t['rootpage']}, columns: {t['columns']})")
    
    print(f"Recovered {len(records)} records")
    
    # Build JSON output
    output = []
    for rowid, stypes, values, table_info in records:
        row = {}
        
        # Determine column names to use
        if column_names:
            names = column_names
        elif table_info and table_info.get('columns'):
            names = table_info['columns']
        else:
            names = [f"col{i}" for i in range(len(values))]
        
        for i, name in enumerate(names):
            if i < len(values):
                st = stypes[i] if i < len(stypes) else None
                row[name] = format_value_for_json(values[i], st)
        output.append(row)
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Written to {output_path}")
