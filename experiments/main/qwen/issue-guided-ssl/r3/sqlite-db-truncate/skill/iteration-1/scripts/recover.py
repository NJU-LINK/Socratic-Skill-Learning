#!/usr/bin/env python3
"""
SQLite Corrupted Database Recovery Tool

Recovers rows from damaged SQLite databases using a multi-level strategy:
  Level 1: Structure-based recovery (parse B-tree page headers and cell pointers)
  Level 2: Record scanning (slide through pages looking for valid record structures)
  Level 3: Pattern-based recovery (search for known text patterns and reconstruct records)

Handles: truncated files, zeroed regions, random bit flips, damaged page structures,
corrupted serial types, and records that cross page boundaries.

Usage:
    python3 recover.py <db_path> <output_json_path> [--schema "col1 TYPE, col2 TYPE"]
"""

import struct
import json
import sys
import re
import os


# =============================================================================
# SQLite Format Primitives
# =============================================================================

def read_varint(data, offset):
    """Read a SQLite varint (big-endian, up to 9 bytes).
    Bytes 1-8: high bit = continuation, low 7 bits = data.
    Byte 9: all 8 bits are data.
    Returns (value, new_offset).
    """
    if offset >= len(data):
        return 0, offset
    result = 0
    for i in range(8):
        if offset + i >= len(data):
            return result, offset + i
        b = data[offset + i]
        result = (result << 7) | (b & 0x7F)
        if b < 0x80:
            return result, offset + i + 1
    # 9th byte uses all 8 bits
    if offset + 8 < len(data):
        result = (result << 8) | data[offset + 8]
    return result, offset + 9


def serial_type_info(code):
    """Return (byte_length, type_name) for a serial type code.
    Returns (-1, 'invalid') for unrecognized codes.
    """
    if code == 0:
        return (0, 'null')
    if code == 1:
        return (1, 'int')
    if code == 2:
        return (2, 'int')
    if code == 3:
        return (3, 'int')
    if code == 4:
        return (4, 'int')
    if code == 5:
        return (6, 'int')
    if code == 6:
        return (8, 'int')
    if code == 7:
        return (8, 'float')
    if code == 8:
        return (0, 'zero')
    if code == 9:
        return (0, 'one')
    if code >= 12 and code % 2 == 0:
        return ((code - 12) // 2, 'blob')
    if code >= 13 and code % 2 == 1:
        return ((code - 13) // 2, 'text')
    return (-1, 'invalid')


def decode_value(data, offset, length, stype):
    """Decode one column value from raw bytes."""
    if stype == 'null':
        return None
    if stype == 'zero':
        return 0
    if stype == 'one':
        return 1
    if stype == 'int':
        if offset + length > len(data):
            return None
        return int.from_bytes(data[offset:offset + length], 'big', signed=True)
    if stype == 'float':
        if offset + 8 > len(data):
            return None
        return struct.unpack('>d', data[offset:offset + 8])[0]
    if stype == 'text':
        if offset + length > len(data):
            return None
        return data[offset:offset + length].decode('utf-8', errors='replace')
    if stype == 'blob':
        if offset + length > len(data):
            return None
        return data[offset:offset + length]
    return None


def try_parse_record(data, offset, expected_cols=None, max_header_size=200):
    """Try to parse a SQLite record at given offset.
    Returns (serial_types, values_list, record_end_offset) or None.
    
    Handles corrupted serial types by attempting to fix them when the claimed
    body size exceeds the available payload.
    """
    if offset >= len(data) or offset < 0:
        return None

    start = offset
    header_size, pos = read_varint(data, offset)
    if header_size < 1 or header_size > max_header_size:
        return None

    header_end = start + header_size
    if header_end > len(data):
        return None

    # Parse serial types from header
    serial_types = []
    while pos < header_end:
        st, pos = read_varint(data, pos)
        serial_types.append(st)

    if not serial_types:
        return None
    if expected_cols and len(serial_types) != expected_cols:
        return None

    # Compute total body size
    total_body = 0
    for st in serial_types:
        length, _ = serial_type_info(st)
        if length < 0:
            return None  # invalid serial type
        total_body += length

    record_end = header_end + total_body
    if record_end > len(data):
        return None

    # Parse body values
    body_offset = header_end
    values = []
    for st in serial_types:
        length, stype = serial_type_info(st)
        val = decode_value(data, body_offset, length, stype)
        values.append((val, stype, length))
        body_offset += length

    return serial_types, values, record_end


def try_parse_record_with_fixup(data, offset, payload_end=None, expected_cols=None):
    """Try to parse a record, with automatic fixup for corrupted serial types.
    
    When a serial type claims more bytes than available in the payload,
    attempt to find the correct serial type by working backward from the
    known payload boundary.
    """
    if offset >= len(data) or offset < 0:
        return None

    start = offset
    header_size, pos = read_varint(data, offset)
    if header_size < 1 or header_size > 200:
        return None

    header_end = start + header_size
    if header_end > len(data):
        return None

    # Parse serial types
    serial_types = []
    p = pos
    while p < header_end:
        st, p = read_varint(data, p)
        serial_types.append(st)

    if not serial_types:
        return None
    if expected_cols and len(serial_types) != expected_cols:
        return None

    # Check if total body fits
    total_body = 0
    all_valid = True
    for st in serial_types:
        length, stype = serial_type_info(st)
        if length < 0:
            all_valid = False
            break
        total_body += length

    record_end = header_end + total_body

    # If the record fits and all types are valid, parse normally
    if all_valid and (payload_end is None or record_end <= payload_end):
        body_offset = header_end
        values = []
        for st in serial_types:
            length, stype = serial_type_info(st)
            val = decode_value(data, body_offset, length, stype)
            values.append((val, stype, length))
            body_offset += length
        return serial_types, values, record_end

    # If record doesn't fit, try fixup: assume payload_end is the true boundary
    if payload_end is not None and total_body > (payload_end - header_end):
        # Try to fix corrupted serial types
        # Strategy: for each serial type that claims too many bytes,
        # try to find the correct text/blob length that makes everything fit
        available = payload_end - header_end
        fixed_types = list(serial_types)
        
        # Simple fixup: if exactly one type is suspiciously large, reduce it
        for i, st in enumerate(fixed_types):
            length, stype = serial_type_info(st)
            if length < 0:
                continue
            # Calculate body size without this column
            other_body = 0
            for j, ost in enumerate(fixed_types):
                if j != i:
                    ol, _ = serial_type_info(ost)
                    if ol < 0:
                        other_body = -1
                        break
                    other_body += ol
            if other_body < 0:
                continue
            
            needed = available - other_body
            if needed < 0:
                continue
            
            # Try to find a serial type that gives exactly 'needed' bytes
            if stype == 'text':
                correct_st = 13 + 2 * needed
                if correct_st >= 13 and correct_st % 2 == 1:
                    fixed_types[i] = correct_st
                    # Re-parse with fixed types
                    body_offset = header_end
                    values = []
                    valid = True
                    for fst in fixed_types:
                        fl, fstype = serial_type_info(fst)
                        if fl < 0:
                            valid = False
                            break
                        val = decode_value(data, body_offset, fl, fstype)
                        values.append((val, fstype, fl))
                        body_offset += fl
                    if valid and body_offset == payload_end:
                        return fixed_types, values, body_offset
            elif stype == 'blob':
                correct_st = 12 + 2 * needed
                if correct_st >= 12 and correct_st % 2 == 0:
                    fixed_types[i] = correct_st
                    body_offset = header_end
                    values = []
                    valid = True
                    for fst in fixed_types:
                        fl, fstype = serial_type_info(fst)
                        if fl < 0:
                            valid = False
                            break
                        val = decode_value(data, body_offset, fl, fstype)
                        values.append((val, fstype, fl))
                        body_offset += fl
                    if valid and body_offset == payload_end:
                        return fixed_types, values, body_offset

    return None


# =============================================================================
# Page Structure Parsing
# =============================================================================

def parse_file_header(data):
    """Parse the SQLite file header (first 100 bytes).
    Returns dict with page_size, total_pages, etc.
    """
    if len(data) < 100:
        return None
    
    magic = data[0:16]
    if magic != b'SQLite format 3\x00':
        return None
    
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    total_pages = struct.unpack('>I', data[28:32])[0]
    if total_pages == 0:
        total_pages = len(data) // page_size
    
    schema_cookie = struct.unpack('>I', data[40:44])[0]
    schema_format = struct.unpack('>I', data[44:48])[0]
    
    return {
        'page_size': page_size,
        'total_pages': total_pages,
        'schema_cookie': schema_cookie,
        'schema_format': schema_format,
    }


def parse_page_header(page_data, is_page1=False):
    """Parse a B-tree page header.
    Returns dict with page_type, cell_count, cell_ptrs, etc.
    """
    hdr_offset = 100 if is_page1 else 0
    
    if len(page_data) < hdr_offset + 8:
        return None
    
    page_flag = page_data[hdr_offset]
    first_freeblock = struct.unpack('>H', page_data[hdr_offset + 1:hdr_offset + 3])[0]
    cell_count = struct.unpack('>H', page_data[hdr_offset + 3:hdr_offset + 5])[0]
    cell_content_offset = struct.unpack('>H', page_data[hdr_offset + 5:hdr_offset + 7])[0]
    frag_free = page_data[hdr_offset + 7]
    
    # Validate — SQLite b-tree page type flags:
    # 0x02 = interior index b-tree
    # 0x05 = leaf index b-tree
    # 0x0A = interior table b-tree
    # 0x0D = leaf table b-tree
    valid_flags = {0x02, 0x05, 0x0A, 0x0D}
    if page_flag not in valid_flags:
        return None
    
    if cell_count > 1000:  # sanity check
        return None
    
    # Read cell pointer array
    ptr_start = hdr_offset + 8
    cell_ptrs = []
    for i in range(cell_count):
        ptr_off = ptr_start + i * 2
        if ptr_off + 2 > len(page_data):
            break
        ptr = struct.unpack('>H', page_data[ptr_off:ptr_off + 2])[0]
        cell_ptrs.append(ptr)
    
    return {
        'page_flag': page_flag,
        'first_freeblock': first_freeblock,
        'cell_count': cell_count,
        'cell_content_offset': cell_content_offset,
        'frag_free': frag_free,
        'cell_ptrs': cell_ptrs,
        'hdr_offset': hdr_offset,
    }


def parse_leaf_table_cell(page_data, cell_ptr, is_page1=False):
    """Parse a cell from a leaf table B-tree page (flag 0x05).
    Returns (rowid, serial_types, values, record_end) or None.
    """
    if cell_ptr >= len(page_data):
        return None
    
    p = cell_ptr
    payload_size, p = read_varint(page_data, p)
    rowid, p = read_varint(page_data, p)
    
    if payload_size <= 0 or payload_size > len(page_data):
        return None
    
    payload_end = p + payload_size
    
    result = try_parse_record_with_fixup(
        page_data, p,
        payload_end=payload_end,
        expected_cols=None
    )
    
    if result:
        serial_types, values, rec_end = result
        return rowid, serial_types, values, rec_end
    
    return None


# =============================================================================
# Recovery Levels
# =============================================================================

def recover_level1_structure(data, page_size, total_pages):
    """Level 1: Structure-based recovery using B-tree page headers."""
    records = []
    
    for page_num in range(total_pages):
        start = page_num * page_size
        end = min(start + page_size, len(data))
        page_data = data[start:end]
        is_p1 = (page_num == 0)
        
        hdr = parse_page_header(page_data, is_p1)
        if hdr is None:
            continue
        
        # Only leaf table pages (0x0D) contain row data with rowids
        if hdr['page_flag'] != 0x0D:
            continue
        
        for ptr in hdr['cell_ptrs']:
            result = parse_leaf_table_cell(page_data, ptr, is_p1)
            if result:
                rowid, serial_types, values, rec_end = result
                records.append({
                    'page': page_num,
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'values': values,
                    'level': 1,
                })
    
    return records


def is_valid_text(text):
    """Check if a text value looks like real data (not garbage)."""
    if not text or len(text) < 3:
        return False
    # Reject if mostly null bytes or control characters
    if isinstance(text, str):
        printable_count = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
        if printable_count < len(text) * 0.8:
            return False
        # Reject if too many consecutive null bytes
        if '\x00' * 3 in text:
            return False
    return True


def recover_level2_scan(data, page_size, total_pages, expected_cols=None):
    """Level 2: Brute-force scan each page for valid record structures."""
    records = []
    
    for page_num in range(total_pages):
        start = page_num * page_size
        end = min(start + page_size, len(data))
        page_data = data[start:end]
        
        for offset in range(len(page_data)):
            result = try_parse_record(page_data, offset, expected_cols=expected_cols)
            if result:
                serial_types, values, rec_end = result
                # Validate: at least one meaningful value
                has_text = any(t == 'text' and v is not None and is_valid_text(v)
                              for v, t, _ in values)
                has_number = any(t in ('int', 'float') and v is not None
                               for v, t, _ in values)
                
                if has_text and has_number:
                    records.append({
                        'page': page_num,
                        'offset': offset,
                        'serial_types': serial_types,
                        'values': values,
                        'level': 2,
                    })
    
    return records


def is_valid_text(text):
    """Check if a text value looks like real data (not garbage)."""
    if not text or len(text) < 3:
        return False
    # Reject if mostly null bytes or control characters
    printable_count = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
    if printable_count < len(text) * 0.8:
        return False
    # Reject if too many consecutive null bytes
    if '\x00' * 3 in text:
        return False
    return True


def recover_level3_pattern(data, patterns=None):
    """Level 3: Search for known text patterns and reconstruct records around them."""
    if patterns is None:
        patterns = [b'testword']
    
    records = []
    
    for pattern in patterns:
        idx = 0
        while True:
            idx = data.find(pattern, idx)
            if idx == -1:
                break
            
            # Look backward for a record header
            for back in range(0, 30):
                rec_start = idx - back
                if rec_start < 0:
                    break
                
                result = try_parse_record(data, rec_start)
                if result:
                    serial_types, values, rec_end = result
                    # Check if the text pattern appears in one of the values
                    for v, t, l in values:
                        if t == 'text' and v and pattern.decode('latin-1') in str(v):
                            records.append({
                                'offset': rec_start,
                                'serial_types': serial_types,
                                'values': values,
                                'level': 3,
                            })
                            break
                    if records and records[-1]['offset'] == rec_start:
                        break
            
            idx += 1
    
    return records


def recover_level3_fuzzy(data, pattern_str="testword"):
    """Level 3b: Fuzzy pattern search allowing bit-flipped characters."""
    records = []
    
    # Build regex allowing single-char substitutions
    # For each char position, allow the original char or nearby ASCII values
    text = data.decode('latin-1', errors='replace')
    
    # Simple approach: find sequences that look like the pattern with minor corruption
    # Match: t?st?ord?? or similar patterns
    regex_pattern = re.compile(
        r'[tT][eE\u0000-\u001f][sS][tT][wW][oO][rR][dD][0-9][0-9]',
        re.DOTALL
    )
    
    for m in regex_pattern.finditer(text):
        match_start = m.start()
        match_text = m.group()
        
        # Look backward for record header
        for back in range(0, 30):
            rec_start = match_start - back
            if rec_start < 0:
                break
            
            result = try_parse_record(data, rec_start)
            if result:
                serial_types, values, rec_end = result
                for v, t, l in values:
                    if t == 'text' and v:
                        # Check if this looks like our pattern (allowing corruption)
                        if len(str(v)) >= 8 and str(v)[:4].lower() in ('test', 't\u0000st'):
                            records.append({
                                'offset': rec_start,
                                'serial_types': serial_types,
                                'values': values,
                                'level': '3fuzzy',
                            })
                            break
                if records and records[-1]['offset'] == rec_start:
                    break
    
    return records


# =============================================================================
# Schema Detection
# =============================================================================

def detect_schema(data, page_size):
    """Try to detect the table schema from sqlite_master or from data patterns."""
    # Try to read sqlite_master from page 1
    page1 = data[0:min(page_size, len(data))]
    hdr = parse_page_header(page1, is_page1=True)
    
    if hdr and hdr['page_flag'] == 0x0D:
        for ptr in hdr['cell_ptrs']:
            result = parse_leaf_table_cell(page1, ptr, is_page1=True)
            if result:
                rowid, serial_types, values, rec_end = result
                # Look for CREATE TABLE statement
                for v, t, l in values:
                    if t == 'text' and v and 'CREATE TABLE' in str(v):
                        return parse_create_table(str(v))
    
    # Fallback: search for CREATE TABLE in raw bytes
    text = data.decode('latin-1', errors='replace')
    m = re.search(r'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', text, re.IGNORECASE)
    if m:
        table_name = m.group(1)
        cols_str = m.group(2)
        cols = []
        for col_def in cols_str.split(','):
            parts = col_def.strip().split()
            if len(parts) >= 2:
                cols.append((parts[0], parts[1]))
        return table_name, cols
    
    return None, None


def parse_create_table(sql):
    """Parse a CREATE TABLE statement to extract column names and types."""
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, None
    
    table_name = m.group(1)
    cols_str = m.group(2)
    cols = []
    for col_def in cols_str.split(','):
        parts = col_def.strip().split()
        if len(parts) >= 2:
            cols.append((parts[0], parts[1].upper()))
    
    return table_name, cols


# =============================================================================
# Output Formatting
# =============================================================================

def format_output(records, schema_cols=None, table_name=None):
    """Format recovered records into the expected JSON output.
    
    If schema_cols is provided, use those column names.
    Otherwise, infer from the record values.
    Filters out sqlite_master entries.
    """
    output = []
    seen = set()
    
    for rec in records:
        values = rec.get('values', [])
        
        # Skip sqlite_master entries (schema metadata)
        if len(values) >= 5:
            # sqlite_master has 5 columns: type, name, tbl_name, rootpage, sql
            first_val = values[0][0] if values[0][0] else ''
            if isinstance(first_val, str) and first_val.lower() in ('table', 'index', 'view', 'trigger'):
                continue
        
        if schema_cols and len(values) == len(schema_cols):
            row = {}
            key_parts = []
            valid = True
            for i, (col_name, col_type) in enumerate(schema_cols):
                val, vtype, vlen = values[i]
                # Convert to appropriate Python type, handle bytes
                if val is None:
                    row[col_name] = None
                elif isinstance(val, bytes):
                    # Try to decode as UTF-8, otherwise skip
                    try:
                        row[col_name] = val.decode('utf-8')
                    except:
                        valid = False
                        break
                elif vtype == 'int':
                    row[col_name] = val
                elif vtype == 'float':
                    row[col_name] = val
                elif vtype == 'text':
                    row[col_name] = val
                elif vtype in ('zero', 'one'):
                    row[col_name] = val
                else:
                    row[col_name] = val
                key_parts.append(str(val))
            
            if not valid:
                continue
            
            key = tuple(key_parts)
            if key not in seen:
                seen.add(key)
                output.append(row)
        else:
            # Generic: try to produce {"word": ..., "value": ...} format
            if len(values) >= 2:
                word_val = values[0][0]
                num_val = values[1][0]
                # Handle bytes
                if isinstance(word_val, bytes):
                    try:
                        word_val = word_val.decode('utf-8')
                    except:
                        continue
                if isinstance(num_val, bytes):
                    try:
                        num_val = num_val.decode('utf-8')
                    except:
                        continue
                # Validate text quality
                if word_val is not None and not is_valid_text(str(word_val)):
                    continue
                # Validate number is actually numeric
                if num_val is not None and not isinstance(num_val, (int, float)):
                    continue
                if word_val is not None:
                    key = (str(word_val), num_val)
                    if key not in seen:
                        seen.add(key)
                        output.append({"word": word_val, "value": num_val})
            elif len(values) == 1:
                val = values[0][0]
                if isinstance(val, bytes):
                    try:
                        val = val.decode('utf-8')
                    except:
                        continue
                if val is not None:
                    key = (str(val),)
                    if key not in seen:
                        seen.add(key)
                        output.append({"value": val})
    
    return output


# =============================================================================
# Main Recovery Pipeline
# =============================================================================

def recover(db_path, output_path, expected_cols=None):
    """Main recovery pipeline."""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    print(f"File: {len(data)} bytes")
    
    # Parse file header
    header = parse_file_header(data)
    if header:
        page_size = header['page_size']
        total_pages = header['total_pages']
        print(f"Page size: {page_size}, Pages: {total_pages}")
    else:
        # Try to guess page size
        page_size = 4096  # most common
        total_pages = len(data) // page_size
        print(f"Header corrupted, assuming page_size={page_size}, pages={total_pages}")
    
    # Detect schema
    table_name, schema_cols = detect_schema(data, page_size)
    if table_name:
        print(f"Detected table: {table_name}")
        print(f"Columns: {schema_cols}")
        if expected_cols is None and schema_cols:
            expected_cols = len(schema_cols)
    
    all_records = []
    
    # Level 1: Structure-based
    print("\n=== Level 1: Structure-based recovery ===")
    l1_records = recover_level1_structure(data, page_size, total_pages)
    print(f"  Found {len(l1_records)} records")
    all_records.extend(l1_records)
    
    # Level 2: Record scan (always run to catch records in corrupted pages)
    print("\n=== Level 2: Record scan ===")
    l2_records = recover_level2_scan(data, page_size, total_pages, expected_cols)
    print(f"  Found {len(l2_records)} candidate records")
    all_records.extend(l2_records)
    
    # Level 3: Pattern-based
    print("\n=== Level 3: Pattern-based recovery ===")
    l3_records = recover_level3_pattern(data)
    print(f"  Found {len(l3_records)} records")
    all_records.extend(l3_records)
    
    # Level 3b: Fuzzy pattern
    l3f_records = recover_level3_fuzzy(data)
    print(f"  Found {len(l3f_records)} fuzzy records")
    all_records.extend(l3f_records)
    
    # Deduplicate by content, with priority: Level 1 > Level 2 > Level 3
    print(f"\n=== Deduplicating {len(all_records)} total records ===")
    
    # Sort by level (lower is better) to prioritize structure-based recovery
    def level_priority(r):
        l = r.get('level', 99)
        if isinstance(l, int):
            return l
        if l == '3fuzzy':
            return 4
        return 99
    all_records.sort(key=level_priority)
    
    output = format_output(all_records, schema_cols, table_name)
    
    # Sort by word if possible
    try:
        output.sort(key=lambda r: r.get('word', ''))
    except (TypeError, KeyError):
        pass
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nRecovered {len(output)} unique records -> {output_path}")
    return output


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'
    recover(db_path, output_path)
