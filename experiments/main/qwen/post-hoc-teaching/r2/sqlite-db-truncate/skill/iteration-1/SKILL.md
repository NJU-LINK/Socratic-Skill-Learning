---
name: sqlite-db-truncate
description: Recover rows from corrupted SQLite databases by parsing raw page structures, record headers, and serial types when standard queries fail. Handles bit flips, zeroed regions, truncated data, and damaged page structures.
---

# SQLite Database Recovery Skill

## Overview

This skill recovers data from corrupted SQLite databases when standard SQL queries fail with "database disk image is malformed" errors. The recovery process combines SQLite format knowledge with raw binary parsing to extract as many valid records as possible.

## When to Use

- SQLite database file exists but queries fail with corruption errors
- File size is correct but internal structures are damaged
- Need to recover data from databases with bit flips, zeroed regions, or damaged page structures

## Recovery Strategy

### Phase 1: Initial Assessment

1. **Check file header** (first 100 bytes):
   - Verify SQLite magic string: "SQLite format 3\000"
   - Extract page size (bytes 16-17, big-endian)
   - Extract number of pages (bytes 28-31, big-endian)
   - If header is intact, proceed to Phase 2

2. **Try standard queries**:
   ```bash
   sqlite3 database.db ".schema"
   sqlite3 database.db "SELECT * FROM table_name;"
   ```
   - If successful, export results directly to JSON
   - If "database disk image is malformed", proceed to Phase 2

### Phase 2: Schema Recovery

1. **Parse page 1 B-tree structure** (B-tree header starts at offset 100):
   - Offset 100: page type (0x0d = leaf table b-tree for sqlite_master)
   - Offset 101-102: first freeblock offset (0x0000 if none)
   - Offset 103-104: number of cells (big-endian)
   - Offset 105-106: cell content area start offset
   - Offset 107: fragmented free bytes
   - Offset 108+: cell pointer array (2 bytes each)

2. **Decode sqlite_master cells**:
   - Each cell contains: payload_size (varint), rowid (varint), header_size (varint), serial_types, data
   - Record header format: header_size byte + serial type varints
   - sqlite_master columns: type, name, tbl_name, rootpage, sql
   - Extract CREATE TABLE statement to determine column types and count
   - **Critical**: Extract rootpage (column 3) to map each table to its data pages
   - **Handle corruption**: Schema cells can also have corrupted serial types. If decode fails, try to reconstruct the expected pattern:
     - For sqlite_master: type (TEXT), name (TEXT), tbl_name (TEXT), rootpage (INTEGER), sql (TEXT)
     - Calculate expected serial types based on data_size and known column patterns
     - Example: "table" (5 chars) → 0x17, "test" (4 chars) → 0x15, small integer → 0x01

3. **Build rootpage mapping**:
   ```python
   table_rootpages = {}  # page_number → table_name
   for tname, (sql, rootpage) in schema_info.items():
       table_rootpages[rootpage] = tname
   ```
   This mapping is essential for multi-table databases. When scanning data pages, use the rootpage to determine which table owns each page.

4. **Parse CREATE TABLE for column names**:
   ```python
   import re
   def parse_create_table(sql):
       m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
       if not m:
           return None, []
       table_name = m.group(1)
       col_defs = m.group(2).split(',')
       columns = [cd.strip().split()[0] for cd in col_defs if cd.strip()]
       return table_name, columns
   ```
   Use these column names when building JSON output instead of hard-coding field names.

5. **Identify data pages**:
   - Page 1 contains sqlite_master (schema)
   - For each table, rootpage points to the start of its B-tree
   - For small tables, rootpage is a leaf page (type 0x0d)
   - For large tables, rootpage may be an interior node (type 0x05) requiring traversal

### Phase 3: Data Recovery

1. **Parse data page B-tree structure**:
   - For page 1: B-tree header starts at offset 100 (after 100-byte file header)
   - For pages 2+: B-tree header starts at offset 0
   - Offset 0 (or 100): page type (0x0d = leaf table b-tree, 0x05 = interior table b-tree)
   - Offset 1-2: first freeblock
   - Offset 3-4: number of cells
   - Offset 5-6: cell content area start
   - Offset 7: fragmented free bytes
   - **For leaf pages (0x0d)**: Offset 8+ contains cell pointer array
   - **For interior pages (0x05)**: Offset 8-11 contains right-most child pointer (4 bytes), then offset 12+ contains cell pointer array

2. **B-tree traversal for large tables**:
   When a table has many rows, SQLite organizes data in a B-tree with interior nodes. To find all leaf pages:
   ```python
   def find_leaf_pages(data, page_size, root_page_num):
       leaf_pages = []
       stack = [root_page_num]
       visited = set()
       
       while stack:
           pg_num = stack.pop()
           if pg_num in visited or pg_num < 1:
               continue
           visited.add(pg_num)
           
           offset = (pg_num - 1) * page_size
           page = data[offset:offset + page_size]
           bt_off = 100 if pg_num == 1 else 0
           page_type = page[bt_off]
           
           if page_type == 0x0d:  # Leaf
               leaf_pages.append(pg_num)
           elif page_type == 0x05:  # Interior
               # Right-most child at offset 8-11
               right_child = struct.unpack('>I', page[bt_off+8:bt_off+12])[0]
               stack.append(right_child)
               
               # Cell pointers at offset 12+
               num_cells = struct.unpack('>H', page[bt_off+3:bt_off+5])[0]
               for i in range(num_cells):
                   ptr_off = bt_off + 12 + 2*i
                   cell_ptr = struct.unpack('>H', page[ptr_off:ptr_off+2])[0]
                   # Interior cell: left child page (4 bytes) + rowid (varint)
                   child_page = struct.unpack('>I', page[cell_ptr:cell_ptr+4])[0]
                   stack.append(child_page)
       
       return leaf_pages
   ```
   
   **Interior page cell structure** (type 0x05):
   - Left child page number (4 bytes, big-endian)
   - Key/rowid (varint) - the largest rowid in the left subtree
   
   This is different from leaf cells which contain the actual data.

3. **Decode each leaf cell**:
   ```
   Cell structure:
   - payload_size (varint): total bytes in payload
   - rowid (varint): row identifier
   - header_size (varint): size of record header including this field
   - serial_types: one varint per column
   - data: column values encoded according to serial types
   ```

3. **Serial type decoding**:
   - 0: NULL (0 bytes)
   - 1: 8-bit signed integer (1 byte)
   - 2: 16-bit signed integer (2 bytes)
   - 3: 24-bit signed integer (3 bytes)
   - 4: 32-bit signed integer (4 bytes)
   - 5: 48-bit signed integer (6 bytes)
   - 6: 64-bit signed integer (8 bytes)
   - 7: 64-bit IEEE float (8 bytes)
   - 8: constant 0 (0 bytes)
   - 9: constant 1 (0 bytes)
   - 10-11: reserved
   - N≥13, odd: text, length = (N-13)/2 bytes
   - N≥12, even: blob, length = (N-12)/2 bytes

4. **Calculate data size**:
   ```
   data_size = payload_size - header_size
   ```
   The header_size field includes itself, so the actual header occupies header_size bytes, and data occupies the rest.

5. **Handle overflow pages for large records**:
   When a record's payload exceeds the local capacity, SQLite stores the excess on overflow pages. The threshold is:
   ```
   U = page_size
   X = U - 12  (usable space per page)
   M = ((X - 12) * 32 / 255) - 23  (overflow threshold)
   ```
   For a 4096-byte page, M ≈ 487 bytes.
   
   If `payload_size > M`, the cell contains:
   1. The first portion of the payload (enough to fill the cell)
   2. A 4-byte big-endian pointer to the first overflow page (after the local payload)
   3. Each overflow page: 4-byte pointer to next overflow page + data (rest of page)
   
   To reconstruct the full payload:
   ```python
   def read_overflow_payload(page, data, page_size, data_start, local_size, overflow_ptr):
       payload = page[data_start:data_start + local_size]
       pg_num = overflow_ptr
       while pg_num > 0:
           pg_offset = (pg_num - 1) * page_size
           overflow_page = data[pg_offset:pg_offset + page_size]
           next_ptr = struct.unpack('>I', overflow_page[0:4])[0]
           payload += overflow_page[4:]
           pg_num = next_ptr
       return payload
   ```
   Then decode the full payload using serial types as usual.

### Phase 4: Corruption Handling

When serial types are corrupted (implied data size ≠ actual data size):

1. **Pattern analysis**:
   - Collect serial type patterns from all cells in the page
   - Find the most common pattern using frequency analysis
   - This pattern likely represents the correct column types

2. **Fix corrupted cells**:
   - For cells with mismatched serial types, try the most common pattern
   - If data_size matches with the common pattern, use it to decode
   - Validate decoded values (e.g., text should be readable, numbers should be reasonable)

3. **Fallback strategies**:
   - If no common pattern exists, try common type combinations:
     - TEXT + INTEGER
     - TEXT + REAL
     - Multiple TEXT columns
   - Use heuristics: text columns often contain readable strings
   - For numeric columns, check if decoded values are in reasonable ranges

### Phase 5: Output Generation

1. **Map columns to JSON fields using schema**:
   - Use the column names parsed from CREATE TABLE (Phase 2, step 4)
   - Map decoded values to these column names in order
   ```python
   for rowid, values in rows:
       obj = {}
       for i, col_name in enumerate(columns):
           obj[col_name] = values[i] if i < len(values) else None
       json_results.append(obj)
   ```
   - The task instruction's output format determines the final JSON field names
   - When the task specifies `{"word": ..., "value": ...}`, match that to the schema columns
   - When the task doesn't specify, use the schema column names directly

2. **Handle data types**:
   - Integers: output as JSON numbers (no quotes)
   - Floats: output as JSON numbers with decimal point
   - Text: output as JSON strings (with quotes)
   - NULL: output as JSON null or omit field

3. **Sort and format**:
   - Sort by primary key or first column
   - Use consistent JSON formatting
   - Write to specified output file

## Implementation Template

```python
import struct
import json
import re
from collections import Counter

def read_varint(buf, offset):
    """Read SQLite varint (1-9 bytes)"""
    result = 0
    for i in range(9):
        byte = buf[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80:
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset

def serial_type_size(st):
    """Return byte count for a serial type"""
    if st == 0: return 0
    elif st == 1: return 1
    elif st == 2: return 2
    elif st == 3: return 3
    elif st == 4: return 4
    elif st == 5: return 6
    elif st == 6: return 8
    elif st == 7: return 8
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2
    return -1

def decode_value(buf, offset, st):
    """Decode a value according to serial type"""
    if st == 0: return None, 0
    elif st == 1: return struct.unpack('>b', buf[offset:offset+1])[0], 1
    elif st == 2: return struct.unpack('>h', buf[offset:offset+2])[0], 2
    elif st == 3: return int.from_bytes(buf[offset:offset+3], 'big', signed=True), 3
    elif st == 4: return struct.unpack('>i', buf[offset:offset+4])[0], 4
    elif st == 5: return int.from_bytes(buf[offset:offset+6], 'big', signed=True), 6
    elif st == 6: return struct.unpack('>q', buf[offset:offset+8])[0], 8
    elif st == 7: return struct.unpack('>d', buf[offset:offset+8])[0], 8
    elif st >= 13 and st % 2 == 1:
        length = (st - 13) // 2
        return buf[offset:offset+length].decode('utf-8', errors='replace'), length
    elif st >= 12 and st % 2 == 0:
        length = (st - 12) // 2
        return buf[offset:offset+length], length
    return None, -1

def parse_create_table(sql):
    """Extract column names from CREATE TABLE statement"""
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, []
    table_name = m.group(1)
    col_defs = m.group(2).split(',')
    columns = [cd.strip().split()[0] for cd in col_defs if cd.strip()]
    return table_name, columns

def find_leaf_pages(data, page_size, root_page_num):
    """BFS through B-tree to find all leaf pages"""
    leaf_pages = []
    stack = [root_page_num]
    visited = set()
    
    while stack:
        pg_num = stack.pop()
        if pg_num in visited or pg_num < 1:
            continue
        visited.add(pg_num)
        
        offset = (pg_num - 1) * page_size
        page = data[offset:offset + page_size]
        bt_off = 100 if pg_num == 1 else 0
        page_type = page[bt_off]
        
        if page_type == 0x0d:  # Leaf
            leaf_pages.append(pg_num)
        elif page_type == 0x05:  # Interior
            right_child = struct.unpack('>I', page[bt_off+8:bt_off+12])[0]
            stack.append(right_child)
            num_cells = struct.unpack('>H', page[bt_off+3:bt_off+5])[0]
            for i in range(num_cells):
                ptr_off = bt_off + 12 + 2*i
                cell_ptr = struct.unpack('>H', page[ptr_off:ptr_off+2])[0]
                child_page = struct.unpack('>I', page[cell_ptr:cell_ptr+4])[0]
                stack.append(child_page)
    
    return leaf_pages

def recover_sqlite(db_path, output_path):
    """Main recovery function"""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    page_size = struct.unpack('>H', data[16:18])[0]
    num_pages = struct.unpack('>I', data[28:32])[0]
    
    # Parse schema and build rootpage mapping
    page1 = data[0:page_size]
    table_rootpages = {}  # rootpage → table_name
    table_columns = {}    # table_name → [col1, col2, ...]
    
    # ... parse sqlite_master cells ...
    # For each table: table_rootpages[rootpage] = tbl_name
    #                table_columns[tbl_name] = parsed columns
    
    # Parse data pages using rootpage mapping
    all_results = {}
    for page_num in range(1, num_pages + 1):
        table_name = table_rootpages.get(page_num, None)
        if table_name is None:
            continue
        
        # Find all leaf pages for this table
        leaf_pages = find_leaf_pages(data, page_size, page_num)
        
        table_results = []
        for leaf_pg_num in leaf_pages:
            page = data[(leaf_pg_num-1)*page_size:leaf_pg_num*page_size]
            # ... parse cells, find common pattern, decode ...
            # ... append (rowid, values) to table_results ...
        
        all_results[table_name] = table_results
    
    # Convert to JSON using schema column names
    json_results = []
    for table_name, rows in all_results.items():
        cols = table_columns.get(table_name, [])
        for rowid, values in rows:
            obj = {}
            for i, col in enumerate(cols):
                obj[col] = values[i] if i < len(values) else None
            json_results.append(obj)
    
    with open(output_path, 'w') as f:
        json.dump(json_results, f, indent=2)

# Usage
recover_sqlite('/app/trunc.db', '/app/recover.json')
```

## Key Insights

1. **Header is often intact**: Even when data is corrupted, the SQLite header (first 100 bytes) is usually readable, giving us page size and structure information.

2. **Serial type corruption is common**: Bit flips often affect serial type bytes but leave the actual data intact. Use pattern analysis to recover the correct types.

3. **Data size is the key constraint**: `payload_size - header_size` gives the exact number of data bytes. Serial types must sum to this size.

4. **Context helps recovery**: Cells in the same table typically have the same serial type pattern. Use the most common pattern to fix corrupted cells.

5. **Validate decoded values**: Text should be readable UTF-8, numbers should be in reasonable ranges. Use these checks to confirm correct decoding.

## Common Corruption Patterns

- **Bit flips in serial types**: Serial type byte has wrong value but data is intact. Fix by using common pattern.
- **Zeroed regions**: Parts of the file are all zeros. Skip cells in these regions.
- **Truncated pages**: Page is cut short. Recover what's available.
- **Damaged cell pointers**: Cell pointer array is corrupted. Scan page for valid cell structures.

## Testing

After recovery, verify:
1. All expected rows are present (check row count)
2. Text values are readable strings
3. Numeric values are in reasonable ranges
4. JSON format is valid and matches expected schema
