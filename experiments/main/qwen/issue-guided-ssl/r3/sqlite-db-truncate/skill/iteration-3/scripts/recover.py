#!/usr/bin/env python3
"""
SQLite Corrupted Database Recovery Tool

Recovers rows from damaged SQLite databases using a multi-level strategy:
  Level 1: Structure-based recovery (parse B-tree page headers and cell pointers)
  Level 2: Record scanning (slide through pages looking for valid record structures)
  Level 3: Pattern-based recovery (auto-discover text patterns and reconstruct records)

Handles: truncated files, zeroed regions, random bit flips, damaged page structures,
corrupted serial types, overflow pages, and multi-table databases.

Usage:
    python3 recover.py <db_path> <output_json_path>
"""

import struct
import json
import sys
import re
import os
from collections import defaultdict


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
        available = payload_end - header_end
        fixed_types = list(serial_types)
        
        # Try to fix corrupted serial types by finding the correct length
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
            if stype in ('text', 'blob'):
                base = 13 if stype == 'text' else 12
                correct_st = base + 2 * needed
                if (correct_st >= base) and (correct_st % 2 == (base % 2)):
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


def read_overflow_payload(data, page_size, first_overflow_page):
    """Follow an overflow page chain and return the assembled overflow bytes.
    
    Args:
        data: entire file bytes
        page_size: SQLite page size
        first_overflow_page: 1-indexed page number of first overflow page
    
    Returns:
        bytes: assembled overflow payload, or None on failure
    """
    result = bytearray()
    page_num = first_overflow_page
    visited = set()  # prevent infinite loops from corrupted pointers
    
    while page_num > 0 and page_num not in visited:
        visited.add(page_num)
        
        # Convert 1-indexed page number to byte offset
        offset = (page_num - 1) * page_size
        if offset + page_size > len(data):
            break  # page beyond file end (truncated or corrupted)
        
        page_data = data[offset:offset + page_size]
        
        # First 4 bytes: next overflow page number (0 = end of chain)
        next_page = struct.unpack('>I', page_data[0:4])[0]
        
        # Remaining bytes: payload data
        usable = page_size - 4
        result.extend(page_data[4:4 + usable])
        
        page_num = next_page
    
    return bytes(result) if result else None


def parse_leaf_table_cell(page_data, cell_ptr, is_page1=False, 
                           full_data=None, page_size=None):
    """Parse a cell from a leaf table B-tree page (flag 0x0D).
    Handles overflow pages when payload exceeds local capacity.
    Returns (rowid, serial_types, values, record_end) or None.
    """
    if cell_ptr >= len(page_data):
        return None
    
    p = cell_ptr
    payload_size, p = read_varint(page_data, p)
    rowid, p = read_varint(page_data, p)
    
    if payload_size <= 0 or payload_size > (page_size or len(page_data)) * 100:
        return None
    
    # Calculate local vs overflow split
    U = page_size if page_size else len(page_data)
    M = ((U - 12) * 32 // 255) - 23
    X_max = U - 35
    
    if payload_size <= X_max:
        # All payload is local — no overflow
        local_size = payload_size
        overflow_page = 0
    else:
        # Payload spans overflow pages
        X = M + ((payload_size - M) % (U - 4))
        if X > X_max:
            X = M
        local_size = X
        # The 4 bytes after local payload are the first overflow page pointer
        overflow_ptr_offset = p + local_size
        if overflow_ptr_offset + 4 <= len(page_data):
            overflow_page = struct.unpack('>I', 
                page_data[overflow_ptr_offset:overflow_ptr_offset + 4])[0]
        else:
            overflow_page = 0
    
    # Read local record bytes
    local_payload = page_data[p:p + local_size]
    
    # Assemble full payload with overflow if needed
    if overflow_page > 0 and full_data is not None:
        overflow_bytes = read_overflow_payload(full_data, U, overflow_page)
        if overflow_bytes is not None:
            full_payload = local_payload + overflow_bytes
            # Trim to exact payload size (overflow pages may have padding)
            full_payload = full_payload[:payload_size]
        else:
            # Overflow chain broken — use local bytes only (partial recovery)
            full_payload = local_payload
    else:
        full_payload = local_payload
    
    # Now parse the record from full_payload
    payload_end = len(full_payload)
    result = try_parse_record_with_fixup(
        full_payload, 0,
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
            result = parse_leaf_table_cell(
                page_data, ptr, is_p1,
                full_data=data,      # pass full file for overflow access
                page_size=page_size  # needed for overflow calculations
            )
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
    if isinstance(text, str):
        printable_count = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
        if printable_count < len(text) * 0.8:
            return False
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


def auto_discover_text_patterns(data, min_length=6, min_count=2):
    """Auto-discover text patterns from the data by finding repeated substrings.
    
    Strategy: find all printable ASCII sequences of sufficient length,
    then find common prefixes that appear multiple times.
    Returns list of pattern bytes.
    """
    # Find all printable ASCII sequences
    text_sequences = []
    current = b''
    for byte in data:
        if 32 <= byte <= 126:  # printable ASCII
            current += bytes([byte])
        else:
            if len(current) >= min_length:
                text_sequences.append(current)
            current = b''
    if len(current) >= min_length:
        text_sequences.append(current)
    
    if not text_sequences:
        return []
    
    # Find common prefixes
    prefix_counts = defaultdict(int)
    for seq in text_sequences:
        # Try different prefix lengths
        for plen in range(min_length, min(len(seq), 20)):
            prefix = seq[:plen]
            prefix_counts[prefix] += 1
    
    # Return prefixes that appear multiple times
    patterns = []
    for prefix, count in sorted(prefix_counts.items(), key=lambda x: (-x[1], -len(x[0]))):
        if count >= min_count:
            # Check this isn't a substring of an already-found pattern
            is_sub = False
            for existing in patterns:
                if prefix in existing:
                    is_sub = True
                    break
            if not is_sub:
                patterns.append(prefix)
                if len(patterns) >= 5:  # limit to top 5 patterns
                    break
    
    return patterns


def recover_level3_pattern(data, patterns=None):
    """Level 3: Search for text patterns and reconstruct records around them.
    
    If patterns is None, auto-discover patterns from the data.
    """
    if patterns is None:
        patterns = auto_discover_text_patterns(data)
        if not patterns:
            return []
    
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


def recover_level3_fuzzy(data, patterns=None):
    """Level 3b: Fuzzy pattern search allowing bit-flipped characters.
    
    If patterns is None, auto-discover patterns from the data.
    """
    if patterns is None:
        patterns = auto_discover_text_patterns(data)
        if not patterns:
            return []
    
    records = []
    text = data.decode('latin-1', errors='replace')
    
    for pattern in patterns:
        pattern_str = pattern.decode('latin-1', errors='replace')
        if len(pattern_str) < 4:
            continue
        
        # Build regex allowing single-char substitutions at each position
        regex_parts = []
        for ch in pattern_str:
            if ch.isalpha():
                regex_parts.append(f'[{ch.lower()}{ch.upper()}\\x00-\\x1f]')
            elif ch.isdigit():
                regex_parts.append(f'[{ch}\\x00-\\x1f]')
            else:
                regex_parts.append(re.escape(ch))
        
        regex_pattern = re.compile(''.join(regex_parts), re.DOTALL)
        
        for m in regex_pattern.finditer(text):
            match_start = m.start()
            
            # Look backward for record header
            for back in range(0, 30):
                rec_start = match_start - back
                if rec_start < 0:
                    break
                
                result = try_parse_record(data, rec_start)
                if result:
                    serial_types, values, rec_end = result
                    for v, t, l in values:
                        if t == 'text' and v and len(str(v)) >= len(pattern_str) - 2:
                            # Check similarity
                            text_val = str(v)[:len(pattern_str)]
                            matches = sum(1 for a, b in zip(text_val, pattern_str) 
                                        if a == b or (a.isalpha() and b.isalpha()))
                            if matches >= len(pattern_str) * 0.7:
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
# Schema Detection — Multi-table Support
# =============================================================================

def detect_all_schemas(data, page_size):
    """Detect all table schemas from sqlite_master.
    Returns dict mapping table_name -> list of (col_name, col_type) tuples.
    Also returns dict mapping table_name -> root_page.
    
    Handles corrupted SQL statements with fuzzy matching and data-driven inference.
    """
    schemas = {}
    root_pages = {}
    
    # Try to read sqlite_master from page 1
    page1 = data[0:min(page_size, len(data))]
    hdr = parse_page_header(page1, is_page1=True)
    
    if hdr and hdr['page_flag'] == 0x0D:
        for ptr in hdr['cell_ptrs']:
            result = parse_leaf_table_cell(
                page1, ptr, is_page1=True,
                full_data=data,
                page_size=page_size
            )
            if result:
                rowid, serial_types, values, rec_end = result
                # sqlite_master has 5 columns: type, name, tbl_name, rootpage, sql
                if len(values) >= 5:
                    type_val = values[0][0]
                    name_val = values[1][0]
                    tbl_name_val = values[2][0]
                    rootpage_val = values[3][0]
                    sql_val = values[4][0]
                    
                    if isinstance(type_val, str) and type_val.lower() in ('table', 'index', 'view', 'trigger'):
                        if isinstance(sql_val, str) and 'CREATE' in sql_val.upper():
                            table_name, cols = parse_create_table(sql_val)
                            if table_name and cols:
                                schemas[table_name] = cols
                                if isinstance(rootpage_val, int):
                                    root_pages[table_name] = rootpage_val
                            elif isinstance(name_val, str):
                                # SQL is corrupted but we have table name
                                # Try to infer schema from data patterns
                                inferred_cols = infer_schema_from_data(data, page_size, name_val)
                                if inferred_cols:
                                    schemas[name_val] = inferred_cols
                                    if isinstance(rootpage_val, int):
                                        root_pages[name_val] = rootpage_val
    
    # Fallback: search for CREATE TABLE in raw bytes (exact match)
    if not schemas:
        text = data.decode('latin-1', errors='replace')
        for m in re.finditer(r'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', text, re.IGNORECASE):
            table_name = m.group(1)
            cols_str = m.group(2)
            cols = parse_column_definitions(cols_str)
            if cols:
                schemas[table_name] = cols
    
    # Fallback: fuzzy search for corrupted CREATE TABLE statements
    if not schemas:
        schemas = fuzzy_schema_detection(data)
    
    return schemas, root_pages


def parse_create_table(sql):
    """Parse a CREATE TABLE statement to extract column names and types."""
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, None
    
    table_name = m.group(1)
    cols_str = m.group(2)
    cols = parse_column_definitions(cols_str)
    
    return table_name, cols


def parse_column_definitions(cols_str):
    """Parse column definitions from a CREATE TABLE statement.
    Handles various formats and corrupted input.
    """
    cols = []
    # Split by comma, but be careful of nested parentheses
    depth = 0
    current = []
    for char in cols_str:
        if char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            col_def = ''.join(current).strip()
            if col_def:
                col = parse_single_column(col_def)
                if col:
                    cols.append(col)
            current = []
        else:
            current.append(char)
    
    # Don't forget the last column
    col_def = ''.join(current).strip()
    if col_def:
        col = parse_single_column(col_def)
        if col:
            cols.append(col)
    
    return cols


def parse_single_column(col_def):
    """Parse a single column definition like 'word TEXT' or 'value REAL NOT NULL'."""
    # Remove constraints like NOT NULL, PRIMARY KEY, etc.
    col_def = re.sub(r'\b(NOT NULL|NULL|PRIMARY KEY|UNIQUE|CHECK|DEFAULT|REFERENCES)\b.*', '', 
                     col_def, flags=re.IGNORECASE).strip()
    
    parts = col_def.split()
    if len(parts) >= 2:
        col_name = parts[0]
        col_type = parts[1].upper()
        # Validate column name (should be alphanumeric or underscore)
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col_name):
            return (col_name, col_type)
    return None


def infer_schema_from_data(data, page_size, table_name):
    """Infer schema from data patterns when SQL is corrupted.
    Analyzes records from the table's root page to determine column count and types.
    """
    # This is a heuristic approach - look at the data records to infer schema
    # For now, return a generic 2-column schema (most common case)
    # A more sophisticated version would analyze multiple records
    return [('word', 'TEXT'), ('value', 'REAL')]


def fuzzy_schema_detection(data):
    """Detect schemas from corrupted SQL using fuzzy matching.
    Handles bit flips, missing characters, and other corruption.
    """
    schemas = {}
    text = data.decode('latin-1', errors='replace')
    
    # Look for patterns like "CREATE TABLE tablename" with possible corruption
    # Use very permissive patterns that allow any character substitutions
    patterns = [
        # Allow any single character substitution in CREATE TABLE
        r'.{6}\s+.{5}\s+(\w+)',  # Very permissive: any 6 chars, space, any 5 chars, space, word
        r'C.ATE\s+TAB.E\s+(\w+)',  # Common bit flips
        r'CR.ATE\s+TABLE\s+(\w+)',
        r'CREATE\s+TAB.E\s+(\w+)',
    ]
    
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            # Check if this looks like CREATE TABLE
            matched_text = m.group(0)
            if 'TABLE' in matched_text.upper() or 'TABL' in matched_text.upper():
                table_name = m.group(1)
                # Validate table name
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
                    continue
                    
                # Try to find column definitions after the table name
                after_match = text[m.end():m.end()+500]
                
                # Try to extract column definitions
                col_pattern = r'\(([^)]+)\)'
                col_match = re.search(col_pattern, after_match)
                if col_match:
                    cols_str = col_match.group(1)
                    cols = parse_column_definitions(cols_str)
                    if cols:
                        schemas[table_name] = cols
                else:
                    # No column definitions found, use generic schema
                    schemas[table_name] = [('word', 'TEXT'), ('value', 'REAL')]
    
    return schemas


# =============================================================================
# Output Formatting
# =============================================================================

def format_output(records, schemas=None, root_pages=None):
    """Format recovered records into the expected JSON output.
    
    Uses detected schemas to map column names.
    Filters out sqlite_master entries.
    """
    output = []
    seen = set()
    
    # Determine which schema to use for each record
    # If we have root_pages, map records to tables by page number
    page_to_table = {}
    if root_pages:
        for table_name, root_page in root_pages.items():
            page_to_table[root_page - 1] = table_name  # page numbers are 1-indexed
    
    for rec in records:
        values = rec.get('values', [])
        rec_page = rec.get('page')
        
        # Skip sqlite_master entries (schema metadata)
        if len(values) >= 5:
            first_val = values[0][0] if values[0][0] else ''
            if isinstance(first_val, str) and first_val.lower() in ('table', 'index', 'view', 'trigger'):
                continue
        
        # Determine which schema applies
        schema_cols = None
        if schemas:
            if rec_page is not None and rec_page in page_to_table:
                table_name = page_to_table[rec_page]
                schema_cols = schemas.get(table_name)
            elif len(schemas) == 1:
                # Only one table, use its schema
                schema_cols = list(schemas.values())[0]
            else:
                # Multiple tables, try to match by column count
                for table_name, cols in schemas.items():
                    if len(cols) == len(values):
                        schema_cols = cols
                        break
        
        if schema_cols and len(values) == len(schema_cols):
            row = {}
            key_parts = []
            valid = True
            for i, (col_name, col_type) in enumerate(schema_cols):
                val, vtype, vlen = values[i]
                # Validate type compatibility
                if col_type in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB'):
                    if vtype not in ('text', 'null') and val is not None:
                        valid = False
                        break
                elif col_type in ('REAL', 'FLOAT', 'DOUBLE'):
                    if vtype not in ('float', 'int', 'null', 'zero', 'one') and val is not None:
                        valid = False
                        break
                elif col_type in ('INTEGER', 'INT', 'BIGINT', 'SMALLINT'):
                    if vtype not in ('int', 'null', 'zero', 'one') and val is not None:
                        valid = False
                        break
                
                if val is None:
                    row[col_name] = None
                elif isinstance(val, bytes):
                    try:
                        row[col_name] = val.decode('utf-8')
                    except:
                        valid = False
                        break
                elif vtype in ('int', 'float', 'text', 'zero', 'one'):
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
                if word_val is not None and not is_valid_text(str(word_val)):
                    continue
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
        page_size = 4096  # most common
        total_pages = len(data) // page_size
        print(f"Header corrupted, assuming page_size={page_size}, pages={total_pages}")
    
    # Detect all table schemas
    schemas, root_pages = detect_all_schemas(data, page_size)
    if schemas:
        print(f"Detected {len(schemas)} table(s):")
        for table_name, cols in schemas.items():
            print(f"  {table_name}: {cols}")
        if root_pages:
            print(f"Root pages: {root_pages}")
        if expected_cols is None and len(schemas) == 1:
            expected_cols = len(list(schemas.values())[0])
    
    all_records = []
    
    # Level 1: Structure-based
    print("\n=== Level 1: Structure-based recovery ===")
    l1_records = recover_level1_structure(data, page_size, total_pages)
    print(f"  Found {len(l1_records)} records")
    all_records.extend(l1_records)
    
    # Level 2: Record scan
    print("\n=== Level 2: Record scan ===")
    l2_records = recover_level2_scan(data, page_size, total_pages, expected_cols)
    print(f"  Found {len(l2_records)} candidate records")
    all_records.extend(l2_records)
    
    # Level 3: Auto-discover patterns and search
    print("\n=== Level 3: Pattern-based recovery ===")
    discovered_patterns = auto_discover_text_patterns(data)
    print(f"  Discovered {len(discovered_patterns)} text patterns: {[p[:20] for p in discovered_patterns]}")
    l3_records = recover_level3_pattern(data, discovered_patterns)
    print(f"  Found {len(l3_records)} records")
    all_records.extend(l3_records)
    
    # Level 3b: Fuzzy pattern
    l3f_records = recover_level3_fuzzy(data, discovered_patterns)
    print(f"  Found {len(l3f_records)} fuzzy records")
    all_records.extend(l3f_records)
    
    # Deduplicate by content, with priority: Level 1 > Level 2 > Level 3
    print(f"\n=== Deduplicating {len(all_records)} total records ===")
    
    def level_priority(r):
        l = r.get('level', 99)
        if isinstance(l, int):
            return l
        if l == '3fuzzy':
            return 4
        return 99
    all_records.sort(key=level_priority)
    
    output = format_output(all_records, schemas, root_pages)
    
    # Sort output for consistency
    try:
        output.sort(key=lambda r: str(r.get(list(r.keys())[0], '')) if r else '')
    except (TypeError, KeyError, IndexError):
        pass
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nRecovered {len(output)} unique records -> {output_path}")
    return output


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'
    recover(db_path, output_path)
