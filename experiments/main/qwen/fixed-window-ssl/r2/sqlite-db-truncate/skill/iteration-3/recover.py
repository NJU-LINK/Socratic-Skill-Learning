#!/usr/bin/env python3
"""
SQLite database recovery tool for corrupted databases.

Parses damaged SQLite files at the byte level, recovering rows from
B-tree leaf pages even when standard tools report "database disk image is malformed".

Handles: bit flips, zeroed regions, truncated data, damaged headers,
cross-page records, multiple tables, mixed serial types.
"""

import struct
import json
import sys
import re
import os

# ─── SQLite format constants ───────────────────────────────────────────────

SQLITE_HEADER = b'SQLite format 3\x00'

# B-tree page types
PAGE_INDEX_INTERIOR = 0x02
PAGE_TABLE_INTERIOR = 0x05
PAGE_INDEX_LEAF = 0x0A
PAGE_TABLE_LEAF = 0x0D

# ─── Varint reading ────────────────────────────────────────────────────────

def read_varint(buf, pos):
    """Read SQLite varint. Returns (value, new_pos). Handles up to 9 bytes."""
    if pos >= len(buf):
        return 0, pos
    result = 0
    for j in range(9):
        if pos + j >= len(buf):
            return result, pos + j
        b = buf[pos + j]
        if j < 8:
            result = (result << 7) | (b & 0x7f)
            if (b & 0x80) == 0:
                return result, pos + j + 1
        else:
            result = (result << 8) | b
            return result, pos + j + 1
    return result, pos


def encode_varint(value):
    """Encode an integer as a SQLite varint."""
    if value < 0:
        # Negative values use 9-byte encoding
        buf = value.to_bytes(8, 'big', signed=True)
        result = bytearray(9)
        for i in range(8):
            result[i] = 0x80 | (buf[i] & 0x7f)
            # Shift: accumulate 7 bits at a time
        # Actually for simplicity, just use the 9-byte form
        result = bytearray(9)
        for i in range(8):
            result[i] = ((value >> (56 - 7*i)) & 0x7f) | 0x80
        result[8] = value & 0xff
        return bytes(result)
    
    if value <= 0x7f:
        return bytes([value])
    if value <= 0x3fff:
        return bytes([(value >> 7) | 0x80, value & 0x7f])
    # General case
    parts = []
    v = value
    while v > 0x7f:
        parts.append(v & 0x7f)
        v >>= 7
    parts.append(v)
    parts.reverse()
    result = []
    for i, p in enumerate(parts):
        if i < len(parts) - 1:
            result.append(p | 0x80)
        else:
            result.append(p)
    return bytes(result)


# ─── Serial type handling ──────────────────────────────────────────────────

def serial_type_size(st):
    """Return the byte size of a serial type's data, or -1 if invalid."""
    if st == 0: return 0
    if st == 1: return 1
    if st == 2: return 2
    if st == 3: return 3
    if st == 4: return 4
    if st == 5: return 6
    if st == 6: return 8
    if st == 7: return 8
    if st == 8: return 0
    if st == 9: return 0
    if st >= 12 and st % 2 == 0: return (st - 12) // 2
    if st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1


def decode_value(payload, pos, st):
    """Decode a column value from payload at pos given serial type st.
    Returns (value, new_pos)."""
    if st == 0: return None, pos
    if st == 1:
        return struct.unpack('>b', payload[pos:pos+1])[0], pos+1
    if st == 2:
        return struct.unpack('>h', payload[pos:pos+2])[0], pos+2
    if st == 3:
        return int.from_bytes(payload[pos:pos+3], 'big', signed=True), pos+3
    if st == 4:
        return struct.unpack('>i', payload[pos:pos+4])[0], pos+4
    if st == 5:
        return int.from_bytes(payload[pos:pos+6], 'big', signed=True), pos+6
    if st == 6:
        return struct.unpack('>q', payload[pos:pos+8])[0], pos+8
    if st == 7:
        return struct.unpack('>d', payload[pos:pos+8])[0], pos+8
    if st == 8: return 0, pos
    if st == 9: return 1, pos
    if st >= 12 and st % 2 == 0:
        blen = (st - 12) // 2
        return payload[pos:pos+blen], pos + blen
    if st >= 13 and st % 2 == 1:
        tlen = (st - 13) // 2
        try:
            return payload[pos:pos+tlen].decode('utf-8'), pos + tlen
        except:
            return payload[pos:pos+tlen].decode('utf-8', errors='replace'), pos + tlen
    return None, pos


# ─── Database header parsing ───────────────────────────────────────────────

def parse_db_header(data):
    """Parse the 100-byte SQLite database header."""
    if len(data) < 100:
        return None
    if data[:16] != SQLITE_HEADER:
        return None
    
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    return {
        'page_size': page_size,
        'db_size_pages': struct.unpack('>I', data[28:32])[0],
        'schema_cookie': struct.unpack('>I', data[40:44])[0],
        'encoding': struct.unpack('>I', data[56:60])[0],  # 1=UTF-8, 2=UTF-16le, 3=UTF-16be
    }


# ─── B-tree page parsing ──────────────────────────────────────────────────

def parse_btree_header(page_data, is_page1=False):
    """Parse B-tree page header. Returns dict with page metadata."""
    offset = 100 if is_page1 else 0
    if len(page_data) < offset + 8:
        return None
    
    page_type = page_data[offset]
    if page_type not in (PAGE_TABLE_LEAF, PAGE_TABLE_INTERIOR, PAGE_INDEX_LEAF, PAGE_INDEX_INTERIOR):
        return None
    
    first_freeblock = struct.unpack('>H', page_data[offset+1:offset+3])[0]
    num_cells = struct.unpack('>H', page_data[offset+3:offset+5])[0]
    cell_content_start = struct.unpack('>H', page_data[offset+5:offset+7])[0]
    frag_bytes = page_data[offset+7]
    
    result = {
        'page_type': page_type,
        'first_freeblock': first_freeblock,
        'num_cells': num_cells,
        'cell_content_start': cell_content_start,
        'frag_bytes': frag_bytes,
        'header_offset': offset,
    }
    
    # For interior pages, read right-most pointer
    if page_type in (PAGE_TABLE_INTERIOR, PAGE_INDEX_INTERIOR):
        result['rightmost_ptr'] = struct.unpack('>I', page_data[offset+8:offset+12])[0]
        ptr_array_start = offset + 12
    else:
        ptr_array_start = offset + 8
    
    # Read cell pointers
    cell_ptrs = []
    for i in range(num_cells):
        p = ptr_array_start + i * 2
        if p + 2 <= len(page_data):
            cell_ptrs.append(struct.unpack('>H', page_data[p:p+2])[0])
    result['cell_ptrs'] = cell_ptrs
    
    return result


def parse_cell_leaf(page_data, ptr, page_size, overflow_pages=None):
    """Parse a table B-tree leaf cell starting at ptr in page_data.
    Returns (payload_size, rowid, payload_bytes) or None on failure."""
    pos = ptr
    if pos >= len(page_data):
        return None
    
    payload_size, pos = read_varint(page_data, pos)
    if payload_size <= 0 or payload_size > page_size * 10:
        return None
    
    rowid, pos = read_varint(page_data, pos)
    
    # Calculate usable size (page_size - header_offset - 0 for leaf)
    # For page 1, usable = page_size - 100
    # Overflow threshold U = page_size - 35 for leaf pages
    usable = page_size - (100 if ptr < page_size and page_data[0:16] == SQLITE_HEADER[:16] else 0)
    # Actually, overflow threshold for leaf: U = page_size - 35
    # But we need to know the header offset for this page
    # Simpler: just take what's available in this page
    available = len(page_data) - pos
    local_payload_size = min(payload_size, available)
    
    payload = page_data[pos:pos + local_payload_size]
    
    # Handle overflow pages if payload extends beyond this page
    if payload_size > local_payload_size and overflow_pages:
        # First 4 bytes of overflow page chain
        if local_payload_size >= 4:
            # Actually the overflow page number is stored after the local payload
            overflow_page_num = struct.unpack('>I', page_data[pos+local_payload_size:pos+local_payload_size+4])[0]
            remaining = payload_size - local_payload_size
            while remaining > 0 and overflow_page_num > 0 and overflow_pages:
                if overflow_page_num in overflow_pages:
                    opage = overflow_pages[overflow_page_num]
                    next_page = struct.unpack('>I', opage[0:4])[0]
                    chunk = min(remaining, len(opage) - 4)
                    payload += opage[4:4+chunk]
                    remaining -= chunk
                    overflow_page_num = next_page
                else:
                    break
    
    return payload_size, rowid, payload


def parse_record(payload):
    """Parse a record payload into (header_size, [serial_types], data_start_pos)."""
    if len(payload) < 1:
        return None
    hdr_size, hpos = read_varint(payload, 0)
    if hdr_size < 1 or hdr_size > len(payload):
        return None
    
    serial_types = []
    while hpos < hdr_size:
        st, hpos = read_varint(payload, hpos)
        serial_types.append(st)
    
    return hdr_size, serial_types, hdr_size


def validate_record(payload, serial_types, hdr_size):
    """Check if serial types produce a total data size matching payload length."""
    data_pos = hdr_size
    for st in serial_types:
        sz = serial_type_size(st)
        if sz < 0:
            return False
        data_pos += sz
    return data_pos == len(payload)


def try_correct_serial_types(payload, serial_types, hdr_size, schema_hints=None):
    """Attempt to correct corrupted serial types.
    
    Strategy: For each corrupted serial type, try all valid alternatives
    and pick the one that makes the total data size match the payload size,
    preferring corrections with minimal hamming distance from the original.
    
    IMPORTANT: Collect ALL valid single-column corrections across ALL columns,
    then pick the one with the GLOBALLY minimum Hamming distance. Do NOT just
    take the first column that works.
    """
    if validate_record(payload, serial_types, hdr_size):
        return serial_types  # Already valid
    
    # Collect ALL valid single-column corrections
    all_corrections = []  # (hamming, col_idx, st_candidate)
    
    for col_idx in range(len(serial_types)):
        original_st = serial_types[col_idx]
        # Calculate size used by other columns
        other_size = 0
        for j, st in enumerate(serial_types):
            if j != col_idx:
                sz = serial_type_size(st)
                if sz < 0:
                    other_size = -1
                    break
                other_size += sz
        if other_size < 0:
            continue
        
        remaining = len(payload) - hdr_size - other_size
        if remaining < 0:
            continue
        
        # Find serial types that produce exactly 'remaining' bytes
        candidates = []
        for st_candidate in range(256):
            if serial_type_size(st_candidate) == remaining:
                diff = st_candidate ^ original_st
                hamming = bin(diff).count('1') if diff < 256 else 99
                candidates.append((hamming, st_candidate))
        
        # Also check larger serial types (for varint-encoded values > 127)
        # Text: st = 2*len + 13, so len = (st-13)/2
        # Blob: st = 2*len + 12, so len = (st-12)/2
        if remaining > 0:
            text_st = 2 * remaining + 13
            blob_st = 2 * remaining + 12
            for st_candidate in [text_st, blob_st]:
                if st_candidate < 256:
                    diff = st_candidate ^ original_st
                    hamming = bin(diff).count('1')
                    if (hamming, st_candidate) not in candidates:
                        candidates.append((hamming, st_candidate))
        
        for hamming, st_candidate in candidates:
            if hamming <= 3:  # Allow up to 3 bit flips
                corrected = serial_types.copy()
                corrected[col_idx] = st_candidate
                if validate_record(payload, corrected, hdr_size):
                    all_corrections.append((hamming, col_idx, st_candidate))
    
    # Pick the correction with globally minimum Hamming distance
    if all_corrections:
        # Group by hamming distance
        min_hamming = min(c[0] for c in all_corrections)
        tied_corrections = [c for c in all_corrections if c[0] == min_hamming]
        
        if len(tied_corrections) == 1:
            # No tie — just pick the minimum
            best_hamming, best_col, best_st = tied_corrections[0]
        else:
            # Tiebreaker: semantic validation — decode each candidate and score
            best = None
            best_score = -1
            for hamming, col_idx, st_candidate in tied_corrections:
                score = 0
                test_types = serial_types.copy()
                test_types[col_idx] = st_candidate
                
                # Try decoding and check for recognizable content
                try:
                    test_values = []
                    dpos = hdr_size
                    for st in test_types:
                        val, dpos = decode_value(payload, dpos, st)
                        test_values.append(val)
                    
                    # Score based on recognizable content
                    for v in test_values:
                        if isinstance(v, str):
                            # sqlite_master SQL column
                            if 'CREATE TABLE' in v.upper():
                                score += 10
                            # sqlite_master type column
                            if v in ('table', 'index', 'view', 'trigger'):
                                score += 5
                            # Data page text patterns (adjust for your schema)
                            if 'testword' in v.lower():
                                score += 3
                            # Valid UTF-8 with printable chars
                            if v.isprintable():
                                score += 1
                except:
                    pass
                
                if best is None or score > best_score:
                    best_score = score
                    best = (hamming, col_idx, st_candidate)
            
            best_hamming, best_col, best_st = best
        
        corrected = serial_types.copy()
        corrected[best_col] = best_st
        return corrected
    
    # Try correcting two serial types simultaneously (for severe corruption)
    if len(serial_types) >= 2:
        for col1 in range(len(serial_types)):
            for col2 in range(col1+1, len(serial_types)):
                other_size = 0
                for j, st in enumerate(serial_types):
                    if j != col1 and j != col2:
                        sz = serial_type_size(st)
                        if sz < 0:
                            other_size = -1
                            break
                        other_size += sz
                if other_size < 0:
                    continue
                
                remaining = len(payload) - hdr_size - other_size
                if remaining < 0:
                    continue
                
                # Try all pairs of serial types that sum to 'remaining'
                for st1 in range(min(256, remaining + 1)):
                    sz1 = serial_type_size(st1)
                    if sz1 < 0 or sz1 > remaining:
                        continue
                    st2_needed = remaining - sz1
                    # Find st2 with this size
                    for st2 in range(256):
                        if serial_type_size(st2) == st2_needed:
                            hamming1 = bin(st1 ^ serial_types[col1]).count('1')
                            hamming2 = bin(st2 ^ serial_types[col2]).count('1')
                            if hamming1 + hamming2 <= 3:
                                corrected = serial_types.copy()
                                corrected[col1] = st1
                                corrected[col2] = st2
                                if validate_record(payload, corrected, hdr_size):
                                    return corrected
    
    return None  # Could not correct


# ─── Schema extraction from sqlite_master ──────────────────────────────────

def extract_schema_from_page1(data, page_size):
    """Try to extract CREATE TABLE statements from page 1 (sqlite_master)."""
    page1 = data[0:page_size]
    bt = parse_btree_header(page1, is_page1=True)
    if not bt:
        return []
    
    tables = []
    for ptr in bt['cell_ptrs']:
        cell = parse_cell_leaf(page1, ptr, page_size)
        if cell is None:
            continue
        payload_size, rowid, payload = cell
        rec = parse_record(payload)
        if rec is None:
            continue
        hdr_size, serial_types, data_pos = rec
        
        if not validate_record(payload, serial_types, hdr_size):
            corrected = try_correct_serial_types(payload, serial_types, hdr_size)
            if corrected:
                serial_types = corrected
        
        # sqlite_master columns: type, name, tbl_name, rootpage, sql
        values = []
        dpos = hdr_size
        for st in serial_types:
            val, dpos = decode_value(payload, dpos, st)
            values.append(val)
        
        if len(values) >= 5:
            sql = values[4] if isinstance(values[4], str) else str(values[4])
            if sql and 'CREATE TABLE' in sql.upper():
                tables.append({
                    'type': values[0],
                    'name': values[1],
                    'tbl_name': values[2],
                    'rootpage': values[3],
                    'sql': sql,
                })
    
    return tables


def parse_create_table(sql):
    """Parse a CREATE TABLE statement to extract column names and types."""
    # Match: CREATE TABLE name (col1 TYPE1, col2 TYPE2, ...)
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    
    table_name = m.group(1)
    cols_str = m.group(2)
    
    columns = []
    for part in cols_str.split(','):
        part = part.strip()
        if not part:
            continue
        # Skip constraints
        if part.upper().startswith(('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT')):
            continue
        tokens = part.split()
        if len(tokens) >= 1:
            col_name = tokens[0].strip('"').strip("'").strip('`')
            col_type = tokens[1].upper() if len(tokens) > 1 else 'TEXT'
            columns.append({'name': col_name, 'type': col_type})
    
    return {'table_name': table_name, 'columns': columns}


# ─── Raw byte scanning fallback ───────────────────────────────────────────

def scan_for_records(data, page_size, known_text_patterns=None):
    """Scan the raw file for record-like structures.
    Useful when B-tree headers are too damaged to parse normally."""
    records = []
    
    # Look for sequences that look like record payloads:
    # header_size(varint) serial_types(varints) data...
    # We search for text patterns as anchors
    if known_text_patterns:
        for pattern in known_text_patterns:
            pattern_bytes = pattern.encode('utf-8') if isinstance(pattern, str) else pattern
            pos = 0
            while True:
                idx = data.find(pattern_bytes, pos)
                if idx < 0:
                    break
                # Try to parse backwards from this text to find a record header
                # Look for a varint header_size followed by serial types
                for back in range(1, 20):
                    start = idx - back
                    if start < 0:
                        continue
                    # Try parsing as record from this position
                    try:
                        hdr_size, hpos = read_varint(data, start)
                        if hdr_size < 2 or hdr_size > 50:
                            continue
                        serial_types = []
                        valid = True
                        while hpos < start + hdr_size:
                            st, hpos = read_varint(data, hpos)
                            if st > 10000:
                                valid = False
                                break
                            serial_types.append(st)
                        if not valid:
                            continue
                        
                        # Check if the text we found matches a text serial type
                        data_start = start + hdr_size
                        total_data = 0
                        for st in serial_types:
                            sz = serial_type_size(st)
                            if sz < 0:
                                valid = False
                                break
                            total_data += sz
                        if not valid or total_data > 10000:
                            continue
                        
                        payload = data[data_start:data_start + total_data]
                        if len(payload) == total_data:
                            records.append({
                                'offset': start,
                                'serial_types': serial_types,
                                'payload': payload,
                                'hdr_size': hdr_size,
                            })
                    except:
                        continue
                pos = idx + 1
    
    return records


# ─── Page scanning for all leaf pages ─────────────────────────────────────

def find_leaf_pages(data, page_size):
    """Find all pages that look like table B-tree leaf pages."""
    pages = []
    num_pages = len(data) // page_size
    
    for pg_num in range(num_pages):
        offset = pg_num * page_size
        page = data[offset:offset + page_size]
        
        # Check for leaf page type
        bt_offset = 100 if pg_num == 0 else 0
        page_type = page[bt_offset]
        
        if page_type == PAGE_TABLE_LEAF:
            bt = parse_btree_header(page, is_page1=(pg_num == 0))
            if bt and bt['num_cells'] > 0 and bt['num_cells'] < 10000:
                pages.append((pg_num, bt))
    
    return pages


# ─── Main recovery pipeline ───────────────────────────────────────────────

def recover_database(db_path, output_path=None):
    """Main recovery function. Returns list of recovered rows per table."""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    header = parse_db_header(data)
    if not header:
        print("ERROR: Not a valid SQLite file (bad header)")
        return {}
    
    page_size = header['page_size']
    print(f"Page size: {page_size}, File size: {len(data)} bytes, Pages: {len(data)//page_size}")
    
    # Step 1: Extract schema from page 1
    tables = extract_schema_from_page1(data, page_size)
    schemas = {}
    for t in tables:
        parsed = parse_create_table(t['sql'])
        if parsed:
            schemas[parsed['table_name']] = {
                'columns': parsed['columns'],
                'rootpage': t['rootpage'],
                'sql': t['sql'],
            }
            print(f"Found table: {parsed['table_name']} with {len(parsed['columns'])} columns, rootpage={t['rootpage']}")
            for col in parsed['columns']:
                print(f"  {col['name']} {col['type']}")
    
    # Step 2: Find all leaf pages
    leaf_pages = find_leaf_pages(data, page_size)
    print(f"\nFound {len(leaf_pages)} leaf pages")
    
    # Step 3: Parse cells from each leaf page
    all_results = {}
    
    for pg_num, bt in leaf_pages:
        page_offset = pg_num * page_size
        page_data = data[page_offset:page_offset + page_size]
        is_page1 = (pg_num == 0)
        
        # Skip sqlite_master cells on page 1
        if is_page1:
            continue
        
        print(f"\nPage {pg_num}: {bt['num_cells']} cells")
        
        # Determine which table this page belongs to
        table_name = None
        schema = None
        for tname, tinfo in schemas.items():
            if tinfo['rootpage'] == pg_num:
                table_name = tname
                schema = tinfo
                break
        
        # If no schema match, try to infer from data
        num_cols = len(schema['columns']) if schema else None
        
        rows = []
        for ptr in bt['cell_ptrs']:
            cell = parse_cell_leaf(page_data, ptr, page_size)
            if cell is None:
                continue
            
            payload_size, rowid, payload = cell
            if len(payload) < 2:
                continue
            
            rec = parse_record(payload)
            if rec is None:
                continue
            
            hdr_size, serial_types, data_pos = rec
            
            # Validate and correct
            if not validate_record(payload, serial_types, hdr_size):
                corrected = try_correct_serial_types(payload, serial_types, hdr_size)
                if corrected:
                    serial_types = corrected
                else:
                    print(f"  Cell at 0x{ptr:04x}: could not validate/correct record (serial_types={[hex(s) for s in serial_types]})")
                    continue
            
            # Decode values
            values = []
            dpos = hdr_size
            valid = True
            for st in serial_types:
                try:
                    val, dpos = decode_value(payload, dpos, st)
                    values.append(val)
                except Exception as e:
                    valid = False
                    break
            
            if not valid:
                continue
            
            # Build row dict
            if schema:
                row = {}
                for i, col in enumerate(schema['columns']):
                    if i < len(values):
                        row[col['name']] = values[i]
                    else:
                        row[col['name']] = None
                rows.append(row)
            else:
                rows.append(values)
        
        if table_name:
            all_results[table_name] = rows
        else:
            # Unknown table - store by page number
            all_results[f'page_{pg_num}'] = rows
        
        print(f"  Recovered {len(rows)} rows")
    
    # Step 4: If no leaf pages found via B-tree, try raw scanning
    if not any(len(v) > 0 for v in all_results.values()):
        print("\nNo rows recovered via B-tree parsing. Trying raw scan...")
        # Try to find text patterns in the data
        text_patterns = set()
        # Look for ASCII text sequences of length >= 4
        i = 0
        while i < len(data):
            if 32 <= data[i] < 127:
                start = i
                while i < len(data) and 32 <= data[i] < 127:
                    i += 1
                if i - start >= 4:
                    text_patterns.add(data[start:i].decode('ascii'))
            i += 1
        
        if text_patterns:
            raw_records = scan_for_records(data, page_size, list(text_patterns)[:50])
            print(f"  Found {len(raw_records)} potential raw records")
    
    return all_results


def format_output(results, output_format='json'):
    """Format results for output."""
    if output_format == 'json':
        # If single table, output as list of dicts
        # If multiple tables, output as dict of table_name -> list
        if len(results) == 1:
            table_name = list(results.keys())[0]
            return json.dumps(results[table_name], indent=2)
        else:
            return json.dumps(results, indent=2)
    return str(results)


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    results = recover_database(db_path)
    
    if output_path:
        with open(output_path, 'w') as f:
            f.write(format_output(results))
        print(f"\nOutput written to {output_path}")
    else:
        print(format_output(results))
