---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from corrupted SQLite databases when standard
  queries fail. Combines intact SQLite structure parsing with raw page,
  record-header, varint, serial-type, and byte-level analysis to extract
  recoverable records and serialize them using the task-specific JSON schema.
---

# SQLite Database Corruption Recovery

## Overview

This skill recovers data from SQLite databases that have been damaged by
mechanisms such as byte-level bit flips, zeroed regions, truncation, or
damaged page structures. The core strategy is to bypass the SQLite query
engine entirely and parse the raw binary format directly, using structural
consistency checks to detect and repair corruption.

## SQLite Binary Format Essentials

### File Header (first 100 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 | Magic: "SQLite format 3\000" |
| 16 | 2 | Page size (1 means 65536) |
| 18 | 1 | File format write version |
| 19 | 1 | File format read version |
| 20 | 1 | Reserved space per page |
| 24 | 4 | File change counter |
| 28 | 4 | Database size in pages |

### B-tree Page Structure

Each page starts with a b-tree header:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Page type (0x02=index interior, 0x05=table interior, 0x0a=index leaf, 0x0d=table leaf) |
| 1 | 2 | First freeblock offset |
| 3 | 2 | Number of cells |
| 5 | 2 | Cell content area start offset |
| 7 | 1 | Fragmented free bytes |
| 8 | 4 | Right-most pointer (interior pages only) |

**Page 1 special case**: The file header occupies the first 100 bytes, so the
b-tree header starts at offset 100 within the file.

### Cell Pointer Array

Immediately after the b-tree header, there are `num_cells` 2-byte big-endian
cell pointer offsets (relative to the page start).

### Table Leaf Cell Format

Each table leaf cell contains:
1. Payload size (varint, 1-9 bytes)
2. Row ID (varint, 1-9 bytes)
3. Payload (record bytes)

### Record Format

A record payload consists of:
1. Header size (varint) — includes itself
2. Serial types (sequence of varints, one per column)
3. Data section (concatenated values)

### Serial Type Encoding

| Serial Type | Meaning | Size |
|-------------|---------|------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit big-endian signed int | 2 |
| 3 | 24-bit big-endian signed int | 3 |
| 4 | 32-bit big-endian signed int | 4 |
| 5 | 48-bit big-endian signed int | 6 |
| 6 | 64-bit big-endian signed int | 8 |
| 7 | IEEE 754 64-bit float | 8 |
| 8 | Integer constant 0 | 0 |
| 9 | Integer constant 1 | 0 |
| N≥12, even | BLOB of length (N-12)/2 | (N-12)/2 |
| N≥13, odd | Text of length (N-13)/2, UTF-8 | (N-13)/2 |

**Critical**: The serial type in each record is authoritative for how that
specific value was stored. Column type affinity (from CREATE TABLE) is only
a suggestion — a REAL column may store integers, a TEXT column may store
numbers, etc. Always decode based on the serial type bytes, never the schema.

### Varint Encoding

SQLite varints use 1-9 bytes. Each byte contributes 7 bits (high bit = continuation).
The 9th byte uses all 8 bits.

## Recovery Methodology

### Phase 1: File Structure Analysis

1. Read the file header to determine page size and page count
2. Verify the magic string is intact (or repairable)
3. Identify which pages are b-tree pages by checking page type bytes

### Phase 2: Schema Recovery

1. Parse page 1's b-tree structure to find the sqlite_master table
2. Extract CREATE TABLE statements to learn column names and declared types
3. **Handle schema corruption**: The SQL text may be truncated if its serial
   type was corrupted. Check if the payload has remaining bytes after the
   declared serial type lengths — if so, append them as additional text.
4. Extract column names and types from the SQL (even partial SQL is useful)

### Phase 3: Data Page Parsing

For each page in the database:

1. Check if the page type is 0x0d (table leaf)
2. Parse the b-tree header to get cell count
3. Read the cell pointer array
4. For each cell pointer, parse the cell:
   - Read payload size varint
   - Read rowid varint
   - Extract payload bytes
   - Parse record header (serial types)
   - Decode values from data section

**When cell pointers are corrupted or missing:**

If the cell pointer array is zeroed, corrupted, or the page header is damaged,
use heuristic record scanning:

```python
def scan_for_records(page_data, page_offset, expected_columns):
    """Scan a page for valid record signatures when cell pointers fail."""
    records = []
    
    # Scan for potential record starts
    for pos in range(len(page_data)):
        # Look for valid header size
        header_size = page_data[pos]
        if header_size < 2 or header_size > 50:  # Reasonable range
            continue
        
        # Check if we have enough data for the header
        if pos + header_size > len(page_data):
            continue
        
        # Try to parse serial types
        serial_types = []
        hpos = 1
        valid = True
        while hpos < header_size:
            st = page_data[pos + hpos]
            # Check if serial type is valid
            if st > 1000:  # Unreasonably large
                valid = False
                break
            serial_types.append(st)
            hpos += 1
        
        if not valid or len(serial_types) != expected_columns:
            continue
        
        # Check if serial types match expected pattern
        # (e.g., text + int/float for our typical case)
        if not is_plausible_serial_pattern(serial_types):
            continue
        
        # Try to decode the data section
        data_start = pos + header_size
        try:
            values = decode_values(serial_types, page_data[data_start:])
            if all(v is not None for v in values):
                records.append({
                    'offset': pos,
                    'serial_types': serial_types,
                    'values': values,
                })
        except:
            continue
    
    return records

def is_plausible_serial_pattern(serial_types):
    """Check if serial types form a plausible pattern."""
    # Must have at least one text/blob or numeric type
    has_text = any(st >= 13 and st % 2 == 1 for st in serial_types)
    has_numeric = any(1 <= st <= 7 for st in serial_types)
    return has_text or has_numeric
```

**Page header validation and repair:**

Before parsing a page, validate the header:

```python
def validate_page_header(data, page_offset, page_size):
    """Validate and potentially repair a page header."""
    page_type = data[page_offset]
    
    # Check if page type is valid
    valid_types = {0x02, 0x05, 0x0a, 0x0d}
    if page_type not in valid_types:
        # Try to infer page type from context
        # Check if it looks like a leaf table page
        num_cells = struct.unpack('>H', data[page_offset+3:page_offset+5])[0]
        if 0 < num_cells < 1000:  # Reasonable cell count
            # Assume it's a leaf table page
            return 0x0d
        return None
    
    # Validate cell count
    num_cells = struct.unpack('>H', data[page_offset+3:page_offset+5])[0]
    if num_cells > page_size // 10:  # Unreasonably high
        return None
    
    # Validate cell content start
    cell_content_start = struct.unpack('>H', data[page_offset+5:page_offset+7])[0]
    if cell_content_start > page_size:
        return None
    
    return page_type
```

### Phase 4: Corruption Detection and Repair

**Cross-cell consistency check** (primary technique for bit-flip corruption):

1. Group cells by their serial type pattern (tuple of serial types)
2. Find the most common pattern using majority vote
3. For cells with different patterns:
   - Compare each serial type position
   - If a serial type differs by exactly one bit (XOR is a power of 2),
     it's likely a bit-flip corruption
   - Replace the corrupted serial type with the expected value
4. Re-decode the cell with corrected serial types

**Why this works**: Bit-flip corruption changes individual bits. A serial type
like 0x61 (text length 42) vs the correct 0x21 (text length 10) differs by
exactly bit 6. The cross-cell pattern reveals the correct value because most
cells are uncorrupted.

**Multi-bit corruption handling:**

When multiple bits are flipped in a serial type, the single-bit XOR check
fails. Use additional heuristics:

```python
def detect_multibit_corruption(cell, expected_pattern, all_cells):
    """Detect multi-bit corruption using payload consistency checks."""
    serial_types = cell['serial_types']
    data_section = cell['data_section']
    
    for i, st in enumerate(serial_types):
        if st != expected_pattern[i]:
            # Check if the serial type produces a valid payload
            expected_st = expected_pattern[i]
            
            # Heuristic 1: Check if decoded value makes sense
            try:
                val, _ = decode_serial_value(data_section, 0, st)
                expected_val, _ = decode_serial_value(data_section, 0, expected_st)
                
                # If expected type is text, check if it's valid UTF-8
                if expected_st >= 13 and expected_st % 2 == 1:
                    if isinstance(expected_val, str) and expected_val.isprintable():
                        # Expected value looks good, current might be corrupted
                        return expected_st
                
                # If expected type is numeric, check if it's reasonable
                if 1 <= expected_st <= 7:
                    if isinstance(expected_val, (int, float)):
                        # Check magnitude is reasonable
                        if abs(expected_val) < 1e10:
                            return expected_st
            except:
                pass
            
            # Heuristic 2: Check payload size consistency
            expected_size = get_serial_type_size(expected_st)
            actual_size = get_serial_type_size(st)
            if expected_size != actual_size:
                # Size mismatch suggests corruption
                return expected_st
    
    return None

def get_serial_type_size(serial_type):
    """Get the data size for a serial type."""
    if serial_type == 0: return 0
    elif 1 <= serial_type <= 6:
        return {1:1, 2:2, 3:3, 4:4, 5:6, 6:8}[serial_type]
    elif serial_type == 7: return 8
    elif serial_type in (8, 9): return 0
    elif serial_type >= 12 and serial_type % 2 == 0:
        return (serial_type - 12) // 2
    elif serial_type >= 13 and serial_type % 2 == 1:
        return (serial_type - 13) // 2
    return 0
```

**Additional corruption heuristics**:
- If cell pointers are corrupted, scan the page for recognizable record
  signatures (e.g., text patterns, valid serial type sequences)
- If the page header is corrupted, try to reconstruct cell count from the
  cell pointer array length
- For zeroed regions, check if adjacent cells have valid data that can be
  used to infer missing values

### Phase 5: Value Decoding and Output

1. Decode each value according to its serial type:
   - Integer types (1-6): Use big-endian signed integer decoding
   - Float type (7): Use `struct.unpack('>d', bytes)` for IEEE 754 double
   - Text types (odd ≥13): Decode as UTF-8
   - Blob types (even ≥12): Keep as bytes or hex-encode
   - NULL (0): Use `null` in JSON
2. Map decoded values to column names from the schema
3. Handle type coercion for JSON output:
   - Integers stay as integers
   - Floats stay as floats (check if rounding is appropriate)
   - Text stays as strings
4. Write output in the task-specified JSON format

## Handling Variation Axes

### Corruption Mechanism

- **Bit flips**: Use cross-cell consistency to detect and repair
- **Zeroed regions**: Look for intact cells outside the zeroed area; use
  cell pointer array to skip zeroed cells
- **Truncation**: If file is truncated, recover what's available from
  intact pages
- **Damaged page structures**: If page type byte is corrupted, scan for
  recognizable b-tree header patterns (valid cell counts, reasonable
  cell content start offsets)
- **Split fragments**: For records that span pages (overflow pages),
  reassemble by following the overflow chain

### Schema and Value Encoding

- **Multiple tables**: Parse sqlite_master to find all table definitions;
  each table may have a different root page
- **Column order**: Always use the order from the CREATE TABLE statement
- **Mixed serial types**: Some cells may use integers while others use
  floats for the same column — decode each cell independently
- **NULLs**: Serial type 0 indicates NULL; include in output as `null`
- **Cross-page records**: If payload exceeds usable page space, SQLite
  stores overflow on linked pages; follow the overflow pointer

### Record Identification

- **Textual keys**: Search for recognizable text patterns in raw page data
- **Numeric keys**: Use rowid values from cell headers
- **Multiple tables**: Each table's data lives on different pages; use
  the rootpage from sqlite_master to locate them
- **Partially damaged headers**: If the record header is corrupted but
  the data section is intact, try to infer serial types from the data
  length and cross-cell patterns

### Recovery Scale

- **Small datasets**: Manual inspection of hex dumps is feasible
- **Large datasets**: Automate the parsing with scripts; use batch
  processing for cell extraction
- **Multiple tables**: Process each table independently; merge results
  if relationships are needed

## Large Database Handling

For databases with hundreds of records or multiple tables, data spans
multiple pages connected by interior b-tree nodes. You must traverse the
full b-tree structure, not just scan leaf pages.

### Interior Table B-tree Pages (Type 0x05)

Interior pages organize the b-tree hierarchy. They contain no data payloads,
only routing information.

**Header format** (12 bytes total):
- Bytes 0-7: Standard b-tree header (same as leaf pages)
- Bytes 8-11: Right-most child page number (4-byte big-endian)

**Cell format** (no payload):
- Bytes 0-3: Left child page number (4-byte big-endian)
- Bytes 4+: Rowid (varint) — the maximum rowid in the left subtree

**Traversal algorithm**:
```python
def traverse_table_btree(data, page_size, page_num):
    """Recursively traverse table b-tree, yielding all leaf cells."""
    page_offset = (page_num - 1) * page_size
    header_offset = page_offset + (100 if page_num == 1 else 0)
    page_type = data[header_offset]
    
    if page_type == 0x05:  # Interior table page
        # Read right-most pointer
        rightmost = struct.unpack('>I', data[header_offset+8:header_offset+12])[0]
        num_cells = struct.unpack('>H', data[header_offset+3:header_offset+5])[0]
        
        # Read cell pointers
        cell_ptrs = []
        for i in range(num_cells):
            ptr = struct.unpack('>H', data[header_offset+12+2*i:header_offset+14+2*i])[0]
            cell_ptrs.append(ptr)
        
        # Traverse left subtrees
        # CRITICAL: Cell pointers are relative to PAGE START, not b-tree header
        # For page 1, page_offset=0 but header_offset=100
        # A cell pointer value of 0x0fc1 means file offset 0x0fc1, not 0x1061
        for ptr in cell_ptrs:
            abs_pos = page_offset + ptr  # ← CORRECT: resolve from page start
            left_child = struct.unpack('>I', data[abs_pos:abs_pos+4])[0]
            rowid, _ = read_varint(data, abs_pos + 4)
            yield from traverse_table_btree(data, page_size, left_child)
        
        # Traverse right-most subtree
        yield from traverse_table_btree(data, page_size, rightmost)
    
    elif page_type == 0x0d:  # Leaf table page
        # Parse and yield all cells as before
        yield from parse_leaf_page(data, page_size, page_num)
```

**Why this matters**: A database with 200 rows at ~20 bytes each needs ~4KB+
of data, which overflows a single 4096-byte page. Without interior page
traversal, you silently miss most of the data.

### Overflow Pages

When a single record's payload exceeds the usable page space, SQLite stores
part of the payload on the leaf page and the rest on linked overflow pages.

**Overflow threshold**:
- For table leaf pages: if payload > (usable_size - 35), overflow is used
- Usable size = page_size - reserved_space_per_page

**Overflow mechanism**:
1. The leaf cell stores the first K bytes of the payload
2. The last 4 bytes of those K bytes are the overflow page number
3. Overflow page format:
   - Bytes 0-3: Next overflow page number (0 = last page)
   - Bytes 4+: Payload data

**Calculating K** (bytes stored on leaf page):
```python
U = usable_size
P = payload_size
if P <= U - 35:
    K = P  # No overflow
else:
    M = ((U - 12) * 64 // 255) - 23  # Minimum local payload
    K = M + ((P - M) % (U - 4))
    if K > U - 35:
        K = M
```

**Reassembly algorithm**:
```python
def read_payload_with_overflow(data, page_size, leaf_offset, cell_pos, payload_size):
    """Read payload, following overflow chain if needed."""
    U = page_size  # Assuming no reserved space
    
    if payload_size <= U - 35:
        # All on leaf page
        return data[cell_pos:cell_pos + payload_size]
    
    # Calculate bytes on leaf page
    M = ((U - 12) * 64 // 255) - 23
    K = M + ((payload_size - M) % (U - 4))
    if K > U - 35:
        K = M
    
    # Read first part from leaf
    payload = bytearray(data[cell_pos:cell_pos + K])
    
    # Read overflow page number (last 4 bytes of K)
    overflow_page = struct.unpack('>I', payload[K-4:K])[0]
    payload = payload[:K-4]  # Remove the overflow pointer
    
    # Follow overflow chain
    while overflow_page != 0:
        overflow_offset = (overflow_page - 1) * page_size
        next_page = struct.unpack('>I', data[overflow_offset:overflow_offset+4])[0]
        chunk = data[overflow_offset+4:overflow_offset+page_size]
        payload.extend(chunk)
        overflow_page = next_page
    
    return bytes(payload[:payload_size])  # Trim to actual size
```

**Corruption considerations**:
- If an overflow page is corrupted, you may only recover partial payloads
- Check that the reassembled payload length matches the declared payload size
- If the overflow chain is broken (invalid page number), stop and use what
  you have

## Implementation Template

### Complete End-to-End Recovery

```python
#!/usr/bin/env python3
"""Complete SQLite corruption recovery pipeline."""
import struct
import json
import re
from collections import Counter

# === Helper Functions ===

def read_varint(data, pos):
    """Read SQLite varint (1-9 bytes)."""
    result = 0
    for i in range(9):
        if pos + i >= len(data):
            return result, pos + i
        byte = data[pos + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, pos + i + 1
        else:
            result = (result << 8) | byte
            return result, pos + i + 1
    return result, pos

def decode_serial_value(data, pos, serial_type):
    """Decode value by serial type. Returns (value, new_pos)."""
    if serial_type == 0:
        return None, pos
    elif 1 <= serial_type <= 6:
        sizes = {1:1, 2:2, 3:3, 4:4, 5:6, 6:8}
        sz = sizes[serial_type]
        val = int.from_bytes(data[pos:pos+sz], 'big', signed=True)
        return val, pos + sz
    elif serial_type == 7:
        val = struct.unpack('>d', data[pos:pos+8])[0]
        return val, pos + 8
    elif serial_type == 8:
        return 0, pos
    elif serial_type == 9:
        return 1, pos
    elif serial_type >= 12 and serial_type % 2 == 0:
        blen = (serial_type - 12) // 2
        return data[pos:pos+blen], pos + blen
    elif serial_type >= 13 and serial_type % 2 == 1:
        tlen = (serial_type - 13) // 2
        return data[pos:pos+tlen].decode('utf-8', errors='replace'), pos + tlen
    return None, pos

def parse_record(payload):
    """Parse record into serial_types list and data_section bytes."""
    header_size = payload[0]
    serial_types = []
    hpos = 1
    while hpos < header_size:
        st, hpos = read_varint(payload, hpos)
        serial_types.append(st)
    return serial_types, payload[header_size:]

def decode_values(serial_types, data_section):
    """Decode all values from a record."""
    values = []
    pos = 0
    for st in serial_types:
        val, pos = decode_serial_value(data_section, pos, st)
        values.append(val)
    return values

# === Schema Recovery ===

def recover_schema(data, page_size):
    """Recover schema from page 1 sqlite_master table."""
    # Page 1 b-tree header at offset 100
    btree_off = 100
    num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
    
    tables = []
    for i in range(num_cells):
        cell_ptr = struct.unpack('>H', data[btree_off+8+2*i:btree_off+10+2*i])[0]
        abs_pos = cell_ptr  # Page 1: pointers relative to page start (offset 0)
        
        payload_size, pos = read_varint(data, abs_pos)
        rowid, pos = read_varint(data, pos)
        payload = data[pos:pos+payload_size]
        serial_types, data_section = parse_record(payload)
        values = decode_values(serial_types, data_section)
        
        # Check for truncated SQL
        if len(values) >= 5 and isinstance(values[4], str):
            total_declared = sum(
                (st - 13) // 2 if st >= 13 and st % 2 == 1 else
                (st - 12) // 2 if st >= 12 and st % 2 == 0 else
                {0:0, 1:1, 2:2, 3:3, 4:4, 5:6, 6:8, 7:8, 8:0, 9:0}.get(st, 0)
                for st in serial_types
            )
            remaining = len(data_section) - total_declared
            if remaining > 0:
                values[4] += data_section[total_declared:].decode('utf-8', errors='replace')
        
        # sqlite_master: type, name, tbl_name, rootpage, sql
        if len(values) >= 5 and values[0] == 'table':
            sql = values[4]
            col_match = re.findall(r'(\w+)\s+(TEXT|REAL|INTEGER|BLOB)', sql, re.IGNORECASE)
            col_names = [c[0] for c in col_match]
            rootpage = values[3]
            tables.append({
                'name': values[1],
                'rootpage': rootpage,
                'columns': col_names,
                'sql': sql,
            })
    
    return tables

# === Corruption Detection ===

def detect_and_fix_corruption(cells):
    """Use cross-cell consistency to detect bit-flip corruption."""
    # Group by column count
    col_count_groups = {}
    for cell in cells:
        n = len(cell['serial_types'])
        col_count_groups.setdefault(n, []).append(cell)
    
    for n, group in col_count_groups.items():
        if len(group) < 2:
            continue
        patterns = [tuple(c['serial_types']) for c in group]
        most_common, count = Counter(patterns).most_common(1)[0]
        
        for cell in group:
            if tuple(cell['serial_types']) != most_common:
                for i in range(len(cell['serial_types'])):
                    if i < len(most_common):
                        xor = cell['serial_types'][i] ^ most_common[i]
                        if xor and (xor & (xor - 1)) == 0:  # single bit flip
                            cell['serial_types'][i] = most_common[i]
    
    return cells

# === Data Recovery ===

def recover_table_data(data, page_size, rootpage, col_names):
    """Recover all rows from a table starting at rootpage."""
    rows = []
    pages_to_visit = [rootpage]
    
    while pages_to_visit:
        page_num = pages_to_visit.pop(0)
        page_offset = (page_num - 1) * page_size
        btree_off = page_offset + (100 if page_num == 1 else 0)
        
        page_type = data[btree_off]
        
        if page_type == 0x0d:  # Leaf table page
            num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
            
            cells = []
            for i in range(num_cells):
                ptr = struct.unpack('>H', data[btree_off+8+2*i:btree_off+10+2*i])[0]
                abs_pos = page_offset + ptr  # Pointers relative to page start
                
                payload_size, pos = read_varint(data, abs_pos)
                rowid, pos = read_varint(data, pos)
                payload = data[pos:pos+payload_size]
                serial_types, data_section = parse_record(payload)
                
                cells.append({
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'data_section': data_section,
                })
            
            # Detect and fix corruption
            cells = detect_and_fix_corruption(cells)
            
            # Decode values
            for cell in cells:
                values = decode_values(cell['serial_types'], cell['data_section'])
                row = {}
                for i, col_name in enumerate(col_names):
                    if i < len(values):
                        val = values[i]
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='replace')
                        row[col_name] = val
                rows.append(row)
        
        elif page_type == 0x05:  # Interior table page
            # Read right-most pointer
            rightmost = struct.unpack('>I', data[btree_off+8:btree_off+12])[0]
            num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
            
            # Read cell pointers and traverse
            for i in range(num_cells):
                ptr = struct.unpack('>H', data[btree_off+12+2*i:btree_off+14+2*i])[0]
                abs_pos = page_offset + ptr  # Pointers relative to page start
                left_child = struct.unpack('>I', data[abs_pos:abs_pos+4])[0]
                pages_to_visit.append(left_child)
            
            pages_to_visit.append(rightmost)
    
    return rows

# === Main Recovery Pipeline ===

def recover_database(db_path, output_path):
    """Complete recovery pipeline."""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Parse file header
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    # Recover schema
    tables = recover_schema(data, page_size)
    print(f"Found {len(tables)} tables: {[t['name'] for t in tables]}")
    
    # Recover data from each table
    all_rows = []
    for table in tables:
        rows = recover_table_data(data, page_size, table['rootpage'], table['columns'])
        all_rows.extend(rows)
        print(f"Recovered {len(rows)} rows from table '{table['name']}'")
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(all_rows, f, indent=2)
    
    print(f"Wrote {len(all_rows)} total rows to {output_path}")
    return all_rows

if __name__ == '__main__':
    recover_database('/app/trunc.db', '/app/recover.json')
```

### Quick Start (Minimal Code)

For simple cases with a single table and bit-flip corruption:

```python
import struct, json, re

data = open('corrupted.db', 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0] or 65536

# Recover schema from page 1
cell_ptr = struct.unpack('>H', data[108:110])[0]
payload = data[cell_ptr+2:cell_ptr+2+data[cell_ptr]]
sql = payload[6:].decode('utf-8', errors='replace')
cols = [c[0] for c in re.findall(r'(\w+)\s+(TEXT|REAL|INTEGER)', sql)]

# Parse page 2 data
page2 = data[page_size:]
num_cells = struct.unpack('>H', page2[3:5])[0]
cells = []
for i in range(num_cells):
    ptr = struct.unpack('>H', page2[8+2*i:10+2*i])[0]
    payload = page2[ptr+2:ptr+2+page2[ptr]]
    stypes = list(payload[1:payload[0]])
    cells.append({'stypes': stypes, 'data': payload[payload[0]:]})

# Fix single-bit-flip corruption
from collections import Counter
pattern = Counter([tuple(c['stypes']) for c in cells]).most_common(1)[0][0]
for c in cells:
    for i in range(len(c['stypes'])):
        xor = c['stypes'][i] ^ pattern[i]
        if xor and (xor & (xor-1)) == 0:
            c['stypes'][i] = pattern[i]

# Decode and output
rows = []
for c in cells:
    pos, vals = 0, []
    for st in c['stypes']:
        if st == 1: vals.append(int.from_bytes(c['data'][pos:pos+1], 'big', signed=True)); pos += 1
        elif st == 7: vals.append(struct.unpack('>d', c['data'][pos:pos+8])[0]); pos += 8
        elif st >= 13 and st % 2 == 1:
            tlen = (st-13)//2; vals.append(c['data'][pos:pos+tlen].decode()); pos += tlen
    rows.append(dict(zip(cols, vals)))

json.dump(rows, open('recover.json', 'w'), indent=2)
```

## Verification Checklist

After recovery, verify:

- [ ] All cell pointers were successfully parsed
- [ ] Serial type patterns are consistent across cells (or corruption was repaired)
- [ ] All values decoded without buffer overruns
- [ ] Text values are valid UTF-8
- [ ] Float values are reasonable (not NaN or Inf unless expected)
- [ ] Output JSON matches the required schema
- [ ] Row count matches expectations (check for missing rows in corrupted regions)

## Common Pitfalls

1. **Assuming column type matches serial type**: Always decode by serial type,
   not by the column's declared type in CREATE TABLE.

2. **Ignoring page 1 offset**: Page 1's b-tree header starts at offset 100,
   not offset 0.

3. **Cell pointer base offset confusion**: Cell pointers are ALWAYS relative to
   the PAGE START, not the b-tree header. For page 1, this means:
   - B-tree header is at offset 100 (due to file header)
   - But cell pointer 0x0fc1 resolves to file offset 0x0fc1, NOT 0x1061
   - Use `page_offset + ptr`, not `header_offset + ptr`
   - This is especially tricky because it works correctly for pages 2+
     (where page_offset == header_offset) but fails on page 1

4. **Varint misreads**: Varints can be 1-9 bytes; don't assume single-byte.

5. **Truncated schema SQL**: The schema cell's SQL text may be truncated if
   its serial type was corrupted. Check for remaining bytes after declared
   lengths and append them.

6. **Float precision**: IEEE 754 doubles may have floating-point noise.
   Consider rounding if the task expects "round" numbers.

7. **Missing cells**: If the cell pointer array is corrupted, some cells
   may be missed. Scan the entire page for recognizable record signatures.

8. **Majority vote failures**: Cross-cell consistency assumes most cells are
   uncorrupted. If >50% of cells share the same corruption pattern, the
   majority vote will be wrong. In such cases:
   - Look for structural validity (does the decoded data make sense?)
   - Check if the serial type produces a reasonable payload size
   - Use domain knowledge (e.g., text should be valid UTF-8)

## Fallback Strategies

When automated recovery fails, try these approaches:

### SQLite Built-in Recovery

```bash
# Try SQLite's .recover command
sqlite3 corrupted.db ".recover" > recovered.sql

# Try .dump with error handling
sqlite3 corrupted.db ".dump" 2>/dev/null > dump.sql
```

These work when corruption is minor and SQLite can still parse most of the database.

### Hex Editor Manual Recovery

For severe corruption, manually inspect the hex dump:

1. **Search for recognizable patterns**: Look for table names, column names, or
   known data values in the raw bytes
2. **Identify record boundaries**: Valid records start with a header size byte
   followed by serial types
3. **Manually extract payloads**: Once you find a valid record, extract the
   payload and decode it

### Brute-Force Serial Type Inference

If the record header is corrupted but the data section is intact:

1. **Try all possible serial type combinations**: For a 2-column record with
   11 bytes of data, try combinations like:
   - (0x21, 0x01): text(10) + int8
   - (0x01, 0x21): int8 + text(10)
   - (0x21, 0x07): text(10) + float64
2. **Validate each combination**: Check if the decoded values make sense
   (valid UTF-8, reasonable numbers, etc.)
3. **Use domain knowledge**: If you know the data format, use it to guide
   the inference

### Partial Recovery

When only some pages are corrupted:

1. **Recover what you can**: Extract data from intact pages
2. **Identify missing rows**: Compare recovered row IDs with expected range
3. **Reconstruct missing data**: If you have backups, logs, or can infer the
   missing values, reconstruct them

### When All Else Fails

If the database is completely unrecoverable:

1. **Check for backups**: Look for `.db-journal`, `.db-wal`, or backup files
2. **Check application logs**: The application may have logged the data
3. **Check version control**: If the database was in git, check the history
4. **Contact the data owner**: They may have a backup or can regenerate the data

### WAL and Journal Files

SQLite uses Write-Ahead Logging (WAL) or rollback journals for transactions:

- **WAL mode**: Creates `.db-wal` and `.db-shm` files
- **Rollback journal**: Creates `.db-journal` file

These files may contain uncommitted or recently committed data. If the main
database is corrupted, check these auxiliary files:

```bash
# Check for WAL files
ls -la *.db-wal *.db-shm *.db-journal 2>/dev/null

# Try to recover from WAL
sqlite3 corrupted.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

The WAL file format is documented in the SQLite source code. It contains a
header followed by frames, each of which is a copy of a database page. You
can manually parse the WAL file to recover pages that may be missing or
corrupted in the main database.
