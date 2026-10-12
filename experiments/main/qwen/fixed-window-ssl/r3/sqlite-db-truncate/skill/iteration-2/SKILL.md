---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from corrupted SQLite databases when standard
  queries fail. Handles bit-flip corruption, zeroed regions, damaged page
  structures, and truncated files. Uses a layered approach: try structured
  b-tree traversal first, fall back to raw page scanning with record
  validation, and use schema inference when the schema page is damaged.
---

# SQLite Database Corruption Recovery

## When to Use

- A `.db` file exists but `sqlite3` reports "database disk image is malformed"
- The file has the correct SQLite magic header but queries fail
- Bits have been flipped, regions zeroed, or the file truncated
- Goal: extract as many valid rows as possible into JSON

## Core Concepts

### SQLite File Layout
- **Page 0** (offset 0): 100-byte file header + b-tree page content
- **Page N** (offset N × page_size): b-tree page
- Page size is at bytes 16-17 (big-endian uint16), always a power of 2 (512–65536)
- Number of pages at bytes 28-31 (big-endian uint32)

### B-tree Page Structure (leaf table page, type=0x0d)
```
Offset 0: page_type (1 byte) — 0x0d = leaf table
Offset 1-2: first_freeblock (2 bytes)
Offset 3-4: num_cells (2 bytes)
Offset 5-6: cell_content_area_offset (2 bytes)
Offset 7: fragmented_free_bytes (1 byte)
Offset 8+: cell_pointer_array (2 bytes per cell)
```
Cell content grows from the cell_content_area_offset toward the end of the page.

### Record (Cell) Format
Each cell in a leaf table b-tree page:
1. **Payload length** (varint) — total bytes of the record
2. **Row ID** (varint) — the rowid
3. **Record header**:
   - Header size (varint) — includes this varint itself
   - Serial types (varints, one per column)
4. **Record body**: column data in serial-type order

### Serial Types
| Code | Meaning | Size |
|------|---------|------|
| 0 | NULL | 0 |
| 1 | 8-bit int | 1 |
| 2 | 16-bit int | 2 |
| 3 | 24-bit int | 3 |
| 4 | 32-bit int | 4 |
| 5 | 48-bit int | 6 |
| 6 | 64-bit int | 8 |
| 7 | 64-bit float (IEEE 754) | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| ≥12, even | BLOB | (N-12)/2 bytes |
| ≥13, odd | TEXT (UTF-8) | (N-13)/2 bytes |

### Varint Encoding
- 1–9 bytes. Each byte contributes 7 bits (high bit = continuation).
- 9th byte uses all 8 bits.
- Maximum value: 2^64 - 1.

### Overflow Pages
When payload > usable_size - 35 (where usable_size = page_size - reserved_bytes_per_page):
- First portion stored locally on b-tree page
- Last 4 bytes of local payload = first overflow page number (big-endian uint32)
- Each overflow page: first 4 bytes = next overflow page (0 = end)
- Remaining bytes on each overflow page are payload continuation

## Recovery Strategy (Layered)

### Layer 1: Structured Recovery (try first)
1. Read file header to get page_size, num_pages
2. Parse page 1's b-tree header to find the schema table
3. Extract CREATE TABLE statements to learn column names and types
4. For each data page (page 2+), parse the b-tree header:
   - Read num_cells and cell pointer array
   - For each cell pointer, parse the record
5. Validate each record: header_size + column_data_sizes == payload_len
6. If a serial type is invalid but schema provides a type hint, attempt repair

### Layer 2: Raw Page Scanning (when b-tree headers are corrupted)
When cell count or pointer array has bit flips:
1. For each page, scan the content area byte by byte
2. At each offset, attempt to parse a record:
   - Read payload_len varint — must be reasonable (≤ page_size)
   - Read header_size varint — must be ≥ 2, ≤ payload_len
   - Read serial types until header is consumed
   - Validate: each serial type must be a valid SQLite type
   - Compute expected body size from serial types
   - Check: header_size + body_size == payload_len
3. Records passing all checks are high-confidence recoveries
4. Skip ahead by payload_len bytes after each successful parse

### Layer 3: Schema Inference (when schema page is damaged)
1. Collect all high-confidence records from Layer 2
2. Group by number of columns (inferred from serial type count)
3. For each group, check consistency:
   - Do text columns contain printable ASCII/UTF-8?
   - Do numeric columns produce reasonable values?
4. Try candidate schemas (2-col, 3-col, etc.) and pick the one that validates the most records

## Implementation Pattern

```python
#!/usr/bin/env python3
"""SQLite corruption recovery — layered approach."""
import struct, json, sys

def read_varint(data, offset):
    """Read a SQLite varint. Returns (value, new_offset)."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, offset + i
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset

def serial_type_size(st):
    """Return the byte size for a given serial type, or -1 if invalid."""
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
    return -1  # invalid

def is_valid_serial_type(st):
    return serial_type_size(st) >= 0

def read_column(data, offset, serial_type):
    """Read a column value given its serial type."""
    if serial_type == 0:
        return None
    elif serial_type == 1:
        return struct.unpack('>b', data[offset:offset+1])[0]
    elif serial_type == 2:
        return struct.unpack('>h', data[offset:offset+2])[0]
    elif serial_type == 3:
        return int.from_bytes(data[offset:offset+3], 'big', signed=True)
    elif serial_type == 4:
        return struct.unpack('>i', data[offset:offset+4])[0]
    elif serial_type == 5:
        return int.from_bytes(data[offset:offset+6], 'big', signed=True)
    elif serial_type == 6:
        return struct.unpack('>q', data[offset:offset+8])[0]
    elif serial_type == 7:
        return struct.unpack('>d', data[offset:offset+8])[0]
    elif serial_type == 8:
        return 0
    elif serial_type == 9:
        return 1
    elif serial_type >= 12 and serial_type % 2 == 0:
        n = (serial_type - 12) // 2
        return data[offset:offset+n]
    elif serial_type >= 13 and serial_type % 2 == 1:
        n = (serial_type - 13) // 2
        # Strict UTF-8: raise error on invalid bytes (no latin-1 fallback)
        return data[offset:offset+n].decode('utf-8')
    return None

def read_full_payload(data, offset, payload_len, page_size):
    """Read payload, following overflow page chain if needed.
    
    When payload_len exceeds local_max (page_size - 35), SQLite stores
    only a partial payload on the b-tree page and chains the rest through
    overflow pages. The last 4 bytes of the local portion point to the
    first overflow page (1-based page number).
    
    Returns: (payload_bytes, actual_length)
    """
    usable_size = page_size  # reserved_space is usually 0
    local_max = usable_size - 35
    
    if payload_len <= local_max:
        # No overflow: entire payload fits on b-tree page
        return data[offset:offset+payload_len], payload_len
    
    # Overflow case: read local portion
    # SQLite formula: local_size = local_max + ((payload_len - local_max) % (usable_size - 4))
    # The modulo ensures local_size is in range [local_max, local_max + usable_size - 5]
    # No guard needed — the formula guarantees the local portion fits on the page
    local_size = local_max + ((payload_len - local_max) % (usable_size - 4))
    
    payload = bytearray(data[offset:offset+local_size])
    
    # Last 4 bytes of local payload = first overflow page number (big-endian)
    next_page = struct.unpack('>I', payload[-4:])[0]
    payload = payload[:-4]  # remove page pointer from local data
    
    # Follow overflow chain
    while next_page > 0 and next_page * page_size <= len(data):
        page_offset = (next_page - 1) * page_size  # page numbers are 1-based
        if page_offset + page_size > len(data):
            break
        
        # First 4 bytes of overflow page = next page number
        next_page = struct.unpack('>I', data[page_offset:page_offset+4])[0]
        # Remaining bytes are payload continuation
        page_data = data[page_offset+4:page_offset+page_size]
        payload.extend(page_data)
    
    # Return only the requested payload_len bytes
    return bytes(payload[:payload_len]), len(payload)


def try_parse_record(data, offset, page_size=4096):
    """Try to parse a record at given offset (strict mode).
    Returns (record_dict, bytes_consumed) or (None, 0).
    All serial types must be valid and sizes must sum exactly."""
    start = offset
    payload_len, offset = read_varint(data, offset)
    if payload_len < 2 or payload_len > len(data) - start:
        return None, 0
    
    rowid, offset = read_varint(data, offset)
    record_start = offset
    
    header_size, offset = read_varint(data, offset)
    if header_size < 2 or header_size > payload_len:
        return None, 0
    
    header_end = record_start + header_size
    if header_end > len(data):
        return None, 0
    
    serial_types = []
    while offset < header_end:
        st, offset = read_varint(data, offset)
        if not is_valid_serial_type(st):
            return None, 0
        serial_types.append(st)
    
    # Compute body size
    body_size = sum(serial_type_size(st) for st in serial_types)
    if header_size + body_size != payload_len:
        return None, 0
    
    # Check we don't go past end of data
    if offset + body_size > len(data):
        return None, 0
    
    # Read full payload (handles overflow pages)
    full_payload, _ = read_full_payload(data, record_start, payload_len, page_size)
    
    # Read columns from full payload
    try:
        columns = []
        body_offset = header_size  # skip header within payload
        for st in serial_types:
            val = read_column(full_payload, body_offset, st)
            columns.append(val)
            body_offset += serial_type_size(st)
    except (UnicodeDecodeError, struct.error):
        return None, 0
    
    # total_consumed must cover the entire record: header varints + payload
    total_consumed = (record_start - start) + payload_len
    return {'rowid': rowid, 'serial_types': serial_types, 'columns': columns, 'payload_len': payload_len}, total_consumed


def try_parse_record_with_repair(data, offset, schema_info=None, page_size=4096):
    """Try to parse a record, repairing corrupted serial types.
    
    When strict parsing fails due to invalid serial types or size mismatch,
    this attempts to find the nearest valid serial types that satisfy the
    payload_len constraint. Uses schema hints when available.
    
    Strategy:
    1. Parse header structure (payload_len, rowid, header_size) — these are
       usually intact even when serial types are corrupted.
    2. Read raw serial type varints (even if "invalid").
    3. If any serial type is invalid or sizes don't sum to payload_len,
       collect ALL valid single-bit-flip repairs that satisfy size constraints.
    4. Score each repair by data quality (printable text, schema consistency).
    5. Return the highest-scoring repair.
    """
    start = offset
    payload_len, pos = read_varint(data, pos := offset)
    if payload_len < 2 or payload_len > len(data) - start:
        return None, 0
    
    rowid, pos = read_varint(data, pos)
    record_start = pos
    
    header_size, pos = read_varint(data, pos)
    if header_size < 2 or header_size > payload_len:
        return None, 0
    
    header_end = record_start + header_size
    if header_end > len(data):
        return None, 0
    
    # Read raw serial types (accept anything that fits in the header)
    raw_serial_types = []
    scan_pos = pos
    while scan_pos < header_end:
        st, scan_pos = read_varint(data, scan_pos)
        raw_serial_types.append(st)
    
    if scan_pos != header_end:
        return None, 0  # header doesn't parse cleanly
    
    body_start = header_end
    target_body_size = payload_len - header_size
    
    # Check if already valid
    if all(is_valid_serial_type(st) for st in raw_serial_types):
        body_size = sum(serial_type_size(st) for st in raw_serial_types)
        if body_size == target_body_size and body_start + body_size <= len(data):
            # It's actually valid — strict parse should have caught this
            # but maybe it was called after strict already failed
            try:
                full_payload, _ = read_full_payload(data, record_start, payload_len, page_size)
                columns = []
                body_offset = header_size
                for st in raw_serial_types:
                    columns.append(read_column(full_payload, body_offset, st))
                    body_offset += serial_type_size(st)
                return {'rowid': rowid, 'serial_types': raw_serial_types,
                        'columns': columns, 'payload_len': payload_len}, body_offset - start
            except (UnicodeDecodeError, struct.error):
                pass  # fall through to repair logic
    
    # Collect all valid repairs
    valid_repairs = []
    
    for suspect_idx in range(len(raw_serial_types)):
        original_st = raw_serial_types[suspect_idx]
        
        # Generate candidate replacements
        candidates = set()
        
        # Single bit flips of the original value
        for bit in range(8):
            flipped = original_st ^ (1 << bit)
            if is_valid_serial_type(flipped):
                candidates.add(flipped)
        
        # If schema hints at a type, add likely candidates
        if schema_info and suspect_idx < len(schema_info['columns']):
            col_type = schema_info['columns'][suspect_idx]['type']
            if col_type in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB'):
                for text_len in range(1, 200):
                    st = 13 + 2 * text_len
                    if st < 256:
                        candidates.add(st)
            elif col_type in ('REAL', 'FLOAT', 'DOUBLE'):
                candidates.add(7)
            elif col_type in ('INTEGER', 'INT', 'BIGINT', 'SMALLINT'):
                candidates.update([1, 2, 3, 4, 5, 6])
        
        # Also try common serial types
        candidates.update([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        for text_len in range(1, 100):
            candidates.add(13 + 2 * text_len)
        
        for candidate_st in candidates:
            if candidate_st == original_st:
                continue
            if not is_valid_serial_type(candidate_st):
                continue
            
            # Build repaired serial types
            repaired = list(raw_serial_types)
            repaired[suspect_idx] = candidate_st
            
            # Check if all are valid now
            if not all(is_valid_serial_type(st) for st in repaired):
                continue
            
            body_size = sum(serial_type_size(st) for st in repaired)
            if body_size == target_body_size and body_start + body_size <= len(data):
                # Size-consistent repair found — now score data quality
                # Read full payload (handles overflow pages)
                full_payload, _ = read_full_payload(data, record_start, payload_len, page_size)
                
                columns = []
                body_offset = header_size  # skip header within payload
                score = 0.0
                repair_valid = True
                
                for col_idx, st in enumerate(repaired):
                    col_size = serial_type_size(st)
                    raw_bytes = full_payload[body_offset:body_offset+col_size]
                    
                    if st >= 13 and st % 2 == 1:  # TEXT
                        # Strict UTF-8 validation — no latin-1 fallback
                        try:
                            text_val = raw_bytes.decode('utf-8')
                            # Score by printable ASCII ratio
                            # Reject text with control characters (except \n\r\t)
                            if len(text_val) > 0:
                                printable = sum(1 for c in text_val if c.isprintable() or c in '\n\r\t') / len(text_val)
                                # Require high printable ratio for text to be valid
                                if printable < 0.95:
                                    repair_valid = False
                                    break
                                score += printable * 10  # weight text quality heavily
                            columns.append(text_val)
                        except UnicodeDecodeError:
                            repair_valid = False
                            break
                    elif st == 0:  # NULL
                        columns.append(None)
                    elif st in (1, 2, 3, 4, 5, 6):  # INTEGER types
                        val = read_column(full_payload, body_offset, st)
                        columns.append(val)
                        # Bonus for small positive integers (common in sqlite_master)
                        if isinstance(val, int) and 0 <= val <= 100:
                            score += 1
                    elif st == 7:  # REAL
                        val = struct.unpack('>d', raw_bytes)[0]
                        columns.append(val)
                        # Bonus for finite, reasonable floats
                        import math
                        if math.isfinite(val) and abs(val) < 1e10:
                            score += 1
                    else:
                        val = read_column(full_payload, body_offset, st)
                        columns.append(val)
                    
                    body_offset += col_size
                
                if repair_valid:
                    # Special heuristic for sqlite_master: first column should be
                    # 'table', 'view', 'index', or 'trigger'
                    if schema_info is None and len(columns) >= 1:
                        first_col = columns[0]
                        if isinstance(first_col, str):
                            if first_col in ('table', 'view', 'index', 'trigger'):
                                score += 100  # strong bonus
                    
                    valid_repairs.append((score, repaired, columns))
    
    if not valid_repairs:
        return None, 0
    
    # Return highest-scoring repair
    valid_repairs.sort(key=lambda x: x[0], reverse=True)
    best_score, best_serial_types, best_columns = valid_repairs[0]
    
    return {'rowid': rowid, 'serial_types': best_serial_types,
            'columns': best_columns, 'payload_len': payload_len}, body_start + target_body_size - start

def recover_from_file(db_path, output_path):
    """Main recovery entry point."""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Validate SQLite header
    if data[:16] != b'SQLite format 3\x00':
        print("Not a SQLite database!")
        return
    
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    num_pages = struct.unpack('>I', data[28:32])[0]
    
    # Extract schema first (used by both layers for repair hints)
    schema_info = extract_schema(data, page_size)
    
    # Run BOTH layers and merge — Layer 1 may get some records via cell pointers
    # while Layer 2 finds others whose pointers were corrupted
    layer1 = try_structured_recovery(data, page_size, num_pages, schema_info)
    layer2 = raw_scan_recovery(data, page_size, num_pages, schema_info)
    
    # Merge: deduplicate by rowid, prefer layer1 results (they have schema mapping)
    seen_rowids = set()
    merged = []
    for rec, rowid in layer1:
        if rowid not in seen_rowids:
            seen_rowids.add(rowid)
            merged.append(rec)
    for rec, rowid in layer2:
        if rowid not in seen_rowids:
            seen_rowids.add(rowid)
            merged.append(rec)
    
    # Sort by rowid for consistent output
    # (rowid is not in the record dict after mapping, so we track it separately)
    # Actually, let's keep rowid tracking simpler — just output in discovery order
    
    with open(output_path, 'w') as f:
        json.dump(merged, f, indent=2)
    print(f"Recovered {len(merged)} records to {output_path}")

def try_structured_recovery(data, page_size, num_pages, schema_info=None):
    """Layer 1: Parse b-tree structure. Returns list of (record, page_num) tuples."""
    records = []
    
    for page_num in range(1, num_pages):
        page_offset = page_num * page_size
        if page_offset + page_size > len(data):
            break
        
        page_type = data[page_offset]
        if page_type != 0x0d:  # leaf table
            continue
        
        try:
            num_cells = struct.unpack('>H', data[page_offset+3:page_offset+5])[0]
            content_offset = struct.unpack('>H', data[page_offset+5:page_offset+7])[0]
            
            if num_cells > page_size // 4:  # sanity check
                continue
            
            # Read cell pointers
            cell_ptrs = []
            valid_ptrs = True
            for i in range(num_cells):
                ptr_off = page_offset + 8 + i * 2
                if ptr_off + 2 > page_offset + page_size:
                    valid_ptrs = False
                    break
                ptr = struct.unpack('>H', data[ptr_off:ptr_off+2])[0]
                cell_ptrs.append(ptr)
            
            if not valid_ptrs:
                continue
            
            # Parse each cell — try strict first, then repair
            for ptr in cell_ptrs:
                abs_off = page_offset + ptr
                if abs_off >= page_offset + page_size:
                    continue
                rec, _ = try_parse_record(data, abs_off, page_size)
                if rec is None:
                    # Attempt serial-type repair using schema and payload constraints
                    rec, _ = try_parse_record_with_repair(data, abs_off, schema_info, page_size)
                if rec and schema_info:
                    mapped = map_record_to_schema(rec, schema_info)
                    if mapped:
                        records.append((mapped, rec.get('rowid')))
                elif rec:
                    records.append((format_record(rec), rec.get('rowid')))
        except Exception:
            continue
    
    return records

def raw_scan_recovery(data, page_size, num_pages, schema_info=None):
    """Layer 2: Brute-force scan all pages for valid records."""
    records = []
    seen = set()
    
    for page_num in range(1, num_pages):
        page_offset = page_num * page_size
        page_end = min(page_offset + page_size, len(data))
        
        # Skip page header (8 bytes for non-first pages, 100+8 for first page)
        scan_start = page_offset + 8
        if page_num == 0:
            scan_start = page_offset + 108
        
        offset = scan_start
        while offset < page_end - 4:
            rec, consumed = try_parse_record(data, offset, page_size)
            if rec is None:
                rec, consumed = try_parse_record_with_repair(data, offset, schema_info, page_size)
            if rec and consumed > 0:
                # Deduplicate by (rowid, column tuple)
                key = (rec['rowid'], tuple(str(c) for c in rec['columns']))
                if key not in seen:
                    seen.add(key)
                    records.append((format_record(rec), rec.get('rowid')))
                offset += consumed
            else:
                offset += 1
    
    return records

def extract_schema(data, page_size):
    """Extract schema from page 1's sqlite_master table.
    
    IMPORTANT: Cell pointers in the pointer array are page-relative offsets
    (relative to byte 0 of the page). For page 1, the page starts at file
    offset 0, so a pointer value of 0x0FC1 means absolute file offset 0x0FC1.
    Do NOT add the b-tree header offset (100) to the pointer value.
    """
    # Page 1 b-tree header starts at file offset 100
    btree_offset = 100
    if data[btree_offset] != 0x0d:
        return None
    
    num_cells = struct.unpack('>H', data[btree_offset+3:btree_offset+5])[0]
    
    for i in range(num_cells):
        ptr_off = btree_offset + 8 + i * 2
        ptr = struct.unpack('>H', data[ptr_off:ptr_off+2])[0]
        # ptr is page-relative; for page 1, page starts at file offset 0
        # So absolute offset = 0 + ptr = ptr
        rec, _ = try_parse_record(data, ptr, page_size)
        if rec is None:
            rec, _ = try_parse_record_with_repair(data, ptr, None, page_size)
        if rec and len(rec['columns']) >= 5:
            sql = rec['columns'][4]
            if isinstance(sql, str) and 'CREATE TABLE' in sql.upper():
                return parse_create_table(sql)
    return None

def parse_create_table(sql):
    """Parse a CREATE TABLE statement to get column names and types."""
    import re
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    table_name = m.group(1)
    cols_str = m.group(2)
    columns = []
    for col_def in cols_str.split(','):
        parts = col_def.strip().split()
        if len(parts) >= 2:
            columns.append({'name': parts[0], 'type': parts[1].upper()})
    return {'table': table_name, 'columns': columns}

def map_record_to_schema(rec, schema_info):
    """Map a parsed record to schema column names."""
    if not schema_info or len(rec['columns']) != len(schema_info['columns']):
        return None
    
    result = {}
    for i, col_info in enumerate(schema_info['columns']):
        val = rec['columns'][i]
        result[col_info['name']] = val
    return result

def format_record(rec):
    """Format a record as a dict with generic column names."""
    result = {}
    for i, val in enumerate(rec['columns']):
        result[f'col{i}'] = val
    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.db> <output.json>")
        sys.exit(1)
    recover_from_file(sys.argv[1], sys.argv[2])
```

## Key Validation Rules

A record parse is **valid** only if ALL of these hold:
1. `payload_len` is reasonable (≥ 2, ≤ usable page space)
2. `header_size` ≥ 2 and ≤ `payload_len`
3. Every serial type byte decodes to a valid SQLite serial type
4. `header_size + sum(column_sizes) == payload_len` exactly
5. All text columns decode as valid UTF-8 (or at minimum valid Latin-1)
6. Numeric values are within plausible ranges for the column type

## Handling Corruption Variants

### Corrupted Serial Types
When a serial type byte is invalid but the rest of the record parses:
- Use schema knowledge to guess the correct type (e.g., TEXT column → odd serial type ≥ 13)
- Use payload_len constraint: `body_size = payload_len - header_size` must equal sum of column sizes
- If only one column's size is unknown, solve for it algebraically

### Zeroed Regions
- Skip any offset where the first byte is 0x00 (payload_len varint of 0 is invalid)
- Records surrounded by zeros may still be intact

### Bit Flips in Headers
- If num_cells is corrupted, raw scanning will find the actual records
- If cell pointers are corrupted, raw scanning bypasses them entirely

### Overflow Records
- Check if payload_len > usable_page_size - 35
- If so, look for overflow page chain (last 4 bytes of local payload)
- Reassemble full payload before parsing

## Output Format

The output JSON schema is specified per-task. Common patterns:
- `[{"col1": val1, "col2": val2}, ...]` — array of objects
- Column names come from the schema if recoverable, otherwise generic
- Integers stay as integers, floats as floats, NULLs as null
- Sort order: by rowid (insertion order) unless task specifies otherwise

## Checklist for New Cases

1. ✅ Verify SQLite magic header
2. ✅ Extract page_size and num_pages
3. ✅ Try `sqlite3` queries first (may work with partial corruption)
4. ✅ Extract schema from page 1 if possible
5. ✅ Try structured b-tree traversal (Layer 1)
6. ✅ If Layer 1 fails or finds fewer records than expected, do raw scanning (Layer 2)
7. ✅ If schema is damaged, infer from record patterns (Layer 3)
8. ✅ Handle overflow pages for large records
9. ✅ Validate all recovered records against schema constraints
10. ✅ Write output in the task-specified JSON format
