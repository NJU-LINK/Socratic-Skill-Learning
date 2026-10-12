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
       # Try exact match first
       m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
       if m:
           table_name = m.group(1)
           col_defs = m.group(2).split(',')
           columns = [cd.strip().split()[0] for cd in col_defs if cd.strip()]
           return table_name, columns
       
       # Handle truncated SQL (missing closing paren) - common with corrupted serial types
       m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)', sql, re.IGNORECASE | re.DOTALL)
       if m:
           table_name = m.group(1)
           col_defs = m.group(2).split(',')
           columns = []
           for cd in col_defs:
               parts = cd.strip().split()
               if parts and parts[0].isidentifier():
                   columns.append(parts[0])
           return table_name, columns
       
       return None, []
   ```
   Use these column names when building JSON output instead of hard-coding field names.

5. **Identify data pages**:
   - Page 1 contains sqlite_master (schema)
   - For each table, rootpage points to the start of its B-tree
   - For small tables, rootpage is a leaf page (type 0x0d)
   - For large tables, rootpage may be an interior node (type 0x05) requiring traversal

6. **Schema inference fallback** (when sqlite_master is unreadable):
   If the schema page is too corrupted to parse, infer the schema from data patterns:
   ```python
   def infer_schema_from_data(data_pages, page_size):
       """Infer column count and types from data cell patterns"""
       # Collect serial type patterns from multiple cells
       patterns = []
       for page in data_pages:
           # Parse cells and collect serial_types
           # ...
           patterns.append(tuple(serial_types))
       
       # Find most common pattern
       from collections import Counter
       most_common = Counter(patterns).most_common(1)[0][0]
       
       # Infer column types from serial types
       columns = []
       for i, st in enumerate(most_common):
           if st == 0:
               columns.append(f"col{i}")  # NULL
           elif 1 <= st <= 6:
               columns.append(f"col{i}")  # INTEGER
           elif st == 7:
               columns.append(f"col{i}")  # REAL
           elif st >= 13 and st % 2 == 1:
               columns.append(f"col{i}")  # TEXT
           elif st >= 12 and st % 2 == 0:
               columns.append(f"col{i}")  # BLOB
       
       return columns
   ```
   
   **Heuristics for column naming**:
   - If task instruction specifies output format (e.g., `{"word": ..., "value": ...}`), use those names
   - If first column contains text patterns like identifiers/keys, name it "id", "key", or "name"
   - If second column contains numbers, name it "value", "count", or "amount"
   - Otherwise use generic names: col0, col1, col2, ...

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

1. **Determine output field names**:
   The task instruction's output format is the ultimate guide for JSON field names. Follow this priority:
   
   a. **Task instruction specifies format** (e.g., `{"word": ..., "value": ...}`):
      - Map schema columns to these names by position
      - First schema column → first task field, etc.
      - Example: schema has (word TEXT, value REAL), task says {"word": ..., "value": ...}
      - Result: {"word": decoded_text, "value": decoded_number}
   
   b. **Task doesn't specify format, schema available**:
      - Use schema column names directly
      - Example: schema has (id INTEGER, name TEXT, score REAL)
      - Result: {"id": 1, "name": "test", "score": 99.5}
   
   c. **No schema available (inferred)**:
      - Use generic names: col0, col1, col2, ...
      - Or use heuristics based on data patterns (see Phase 2, step 6)
   
   ```python
   # Example: task says {"word": ..., "value": ...}
   # Schema columns: ['word', 'value']
   # Mapping: direct match
   
   # Example: task says {"word": ..., "value": ...}
   # Schema columns: ['name', 'score']
   # Mapping: name → word, score → value (by position)
   
   # Example: task doesn't specify
   # Schema columns: ['id', 'name', 'score']
   # Result: use schema names directly
   ```

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
    """Extract column names from CREATE TABLE statement. Handles truncated SQL."""
    # Try exact match first
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if m:
        table_name = m.group(1)
        col_defs = m.group(2).split(',')
        columns = [cd.strip().split()[0] for cd in col_defs if cd.strip()]
        return table_name, columns
    
    # Handle truncated SQL (missing closing paren)
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)', sql, re.IGNORECASE | re.DOTALL)
    if m:
        table_name = m.group(1)
        col_defs = m.group(2).split(',')
        columns = []
        for cd in col_defs:
            parts = cd.strip().split()
            if parts and parts[0].isidentifier():
                columns.append(parts[0])
        return table_name, columns
    
    return None, []

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

def parse_btree_page(page, bt_offset=0):
    """Parse a B-tree page header, return (page_type, num_cells, cell_ptrs)"""
    if bt_offset >= len(page):
        return None, 0, []
    
    page_type = page[bt_offset]
    if page_type not in (0x02, 0x05, 0x0a, 0x0d):
        return None, 0, []
    
    if bt_offset + 8 > len(page):
        return page_type, 0, []
    
    num_cells = struct.unpack('>H', page[bt_offset+3:bt_offset+5])[0]
    
    # For leaf pages, cell pointers start at bt_offset + 8
    # For interior pages, cell pointers start at bt_offset + 12 (after right-most child)
    ptr_start = bt_offset + 8 if page_type in (0x0d, 0x0a) else bt_offset + 12
    
    cell_ptrs = []
    for i in range(num_cells):
        ptr_offset = ptr_start + 2*i
        if ptr_offset + 2 > len(page):
            break
        ptr = struct.unpack('>H', page[ptr_offset:ptr_offset+2])[0]
        cell_ptrs.append(ptr)
    
    return page_type, num_cells, cell_ptrs

def parse_cell(page, ptr):
    """Parse a single leaf cell, return (payload_size, rowid, serial_types, data_start, data_size) or None"""
    if ptr >= len(page):
        return None
    
    try:
        pos = ptr
        payload_size, pos = read_varint(page, pos)
        if payload_size <= 0 or payload_size > len(page):
            return None
        
        rowid, pos = read_varint(page, pos)
        if pos >= len(page):
            return None
        
        header_size = page[pos]
        if header_size <= 0 or header_size > payload_size:
            return None
        
        header_start = pos
        pos += 1
        
        serial_end = header_start + header_size
        if serial_end > len(page):
            return None
        
        serial_types = []
        spos = header_start + 1
        while spos < serial_end:
            st, spos = read_varint(page, spos)
            serial_types.append(st)
        
        data_start = serial_end
        data_size = payload_size - header_size
        
        if data_start + data_size > len(page):
            return None
        
        return payload_size, rowid, serial_types, data_start, data_size
    except Exception:
        return None

def decode_cell_values(page, serial_types, data_start, data_size):
    """Decode cell values using given serial types. Returns list of values or None."""
    total_implied = sum(serial_type_size(st) for st in serial_types)
    if total_implied != data_size:
        return None
    
    values = []
    dpos = data_start
    for st in serial_types:
        val, sz = decode_value(page, dpos, st)
        if sz < 0:
            return None
        values.append(val)
        dpos += sz
    return values

def recover_sqlite(db_path, output_path):
    """Main recovery function"""
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Validate header
    if len(data) < 100 or data[:16] != b'SQLite format 3\x00':
        raise ValueError("Not a valid SQLite database")
    
    page_size = struct.unpack('>H', data[16:18])[0]
    num_pages = struct.unpack('>I', data[28:32])[0]
    
    print(f"Database: {page_size} bytes/page, {num_pages} pages")
    
    # Parse schema from page 1
    page1 = data[0:page_size]
    schema_info = {}  # table_name -> (sql, rootpage)
    table_columns = {}  # table_name -> [col1, col2, ...]
    table_rootpages = {}  # rootpage -> table_name
    
    bt_offset = 100  # Page 1 B-tree header starts after 100-byte file header
    page_type, num_cells, cell_ptrs = parse_btree_page(page1, bt_offset)
    
    if page_type == 0x0d:
        print(f"Page 1 (sqlite_master): {num_cells} cells")
        for ptr in cell_ptrs:
            cell = parse_cell(page1, ptr)
            if cell is None:
                continue
            payload_size, rowid, serial_types, data_start, data_size = cell
            
            # Try to decode with actual serial types
            values = decode_cell_values(page1, serial_types, data_start, data_size)
            
            # If that fails, try to fix corrupted serial types
            if values is None and data_size >= 14:
                # For sqlite_master: TEXT, TEXT, TEXT, INTEGER, TEXT
                # Assume: text(5) + text(4) + text(4) + int1 + text(N)
                # 5 + 4 + 4 + 1 + N = data_size, so N = data_size - 14
                n = data_size - 14
                fixed_serial_types = [0x17, 0x15, 0x15, 0x01, 13 + 2*n]
                values = decode_cell_values(page1, fixed_serial_types, data_start, data_size)
                if values:
                    print(f"  Fixed schema cell with pattern: {[hex(s) for s in fixed_serial_types]}")
            
            if values and len(values) >= 5:
                tbl_type = values[0]
                tbl_name = values[1]
                rootpage = values[3]
                sql = values[4]
                if tbl_type == 'table':
                    schema_info[tbl_name] = (sql, rootpage)
                    table_rootpages[rootpage] = tbl_name
                    print(f"  Table '{tbl_name}' (rootpage={rootpage}): {sql}")
                    
                    # Parse column names from SQL
                    parsed_name, cols = parse_create_table(sql)
                    if cols:
                        table_columns[tbl_name] = cols
                        print(f"    Columns: {cols}")
    
    # Parse all data pages
    all_results = {}  # table_name -> list of (rowid, values)
    
    for page_num in range(1, num_pages + 1):
        # Check if this page is a rootpage for a table
        table_name = table_rootpages.get(page_num, None)
        if table_name is None:
            continue
        
        print(f"\nTable '{table_name}' (rootpage={page_num}):")
        
        # Find all leaf pages for this table (handles B-tree traversal)
        leaf_pages = find_leaf_pages(data, page_size, page_num)
        print(f"  Found {len(leaf_pages)} leaf page(s): {leaf_pages}")
        
        table_results = []
        
        for leaf_pg_num in leaf_pages:
            offset = (leaf_pg_num - 1) * page_size
            page = data[offset:offset + page_size]
            
            if len(page) < 10:
                continue
            
            bt_offset = 100 if leaf_pg_num == 1 else 0
            page_type, num_cells, cell_ptrs = parse_btree_page(page, bt_offset)
            
            if page_type != 0x0d:
                continue
            
            print(f"  Page {leaf_pg_num}: {num_cells} cells")
            
            # Parse all cells
            cell_data = []
            for ptr in cell_ptrs:
                cell = parse_cell(page, ptr)
                if cell is None:
                    continue
                payload_size, rowid, serial_types, data_start, data_size = cell
                cell_data.append({
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'data_start': data_start,
                    'data_size': data_size
                })
            
            if not cell_data:
                continue
            
            # Find most common serial type pattern
            patterns = [tuple(cd['serial_types']) for cd in cell_data]
            pattern_counts = Counter(patterns)
            most_common = pattern_counts.most_common(1)[0][0]
            print(f"    Most common pattern: {[hex(s) for s in most_common]}")
            
            # Decode cells
            for cd in cell_data:
                values = decode_cell_values(page, cd['serial_types'], cd['data_start'], cd['data_size'])
                
                if values is None:
                    # Try most common pattern
                    if sum(serial_type_size(st) for st in most_common) == cd['data_size']:
                        values = decode_cell_values(page, most_common, cd['data_start'], cd['data_size'])
                        if values:
                            print(f"    Fixed cell rowid={cd['rowid']}: {values}")
                
                if values:
                    table_results.append((cd['rowid'], values))
        
        all_results[table_name] = table_results
    
    # Convert to JSON format using schema column names
    json_results = []
    for table_name, rows in all_results.items():
        cols = table_columns.get(table_name, [])
        
        for rowid, values in rows:
            if cols and len(cols) == len(values):
                obj = {}
                for i, col in enumerate(cols):
                    obj[col] = values[i]
                json_results.append(obj)
            elif len(values) >= 2:
                # Fallback: use task instruction format or generic names
                json_results.append({"col0": values[0], "col1": values[1]})
            elif len(values) == 1:
                json_results.append({"col0": values[0]})
    
    # Sort by first field
    if json_results:
        first_key = list(json_results[0].keys())[0]
        json_results.sort(key=lambda x: str(x.get(first_key, "")))
    
    with open(output_path, 'w') as f:
        json.dump(json_results, f, indent=2)
    
    print(f"\nRecovered {len(json_results)} rows to {output_path}")
    return json_results

# Usage
recover_sqlite('/app/trunc.db', '/app/recover.json')
```

## Key Insights

1. **Header is often intact**: Even when data is corrupted, the SQLite header (first 100 bytes) is usually readable, giving us page size and structure information.

2. **Serial type corruption is common**: Bit flips often affect serial type bytes but leave the actual data intact. Use pattern analysis to recover the correct types.

3. **Data size is the key constraint**: `data_size = payload_size - header_size` gives the exact number of data bytes. Serial types must sum to this size. This is the most reliable way to validate a decode.

4. **Context helps recovery**: Cells in the same table typically have the same serial type pattern. Use the most common pattern to fix corrupted cells.

5. **Validate decoded values**: Text should be readable UTF-8, numbers should be in reasonable ranges. Use these checks to confirm correct decoding.

6. **Task instruction is authoritative**: The task instruction's output format determines the final JSON field names, not the schema. Schema tells you the database structure; task tells you what to output.

7. **Schema inference is a fallback**: When sqlite_master is unreadable, infer schema from data patterns. Use the most common serial type pattern across cells to determine column count and types.

8. **Overflow pages for large records**: Records exceeding ~487 bytes (for 4096-byte pages) use overflow pages. Follow the overflow chain to reconstruct the full payload before decoding.

9. **Interior B-tree pages**: Large tables use interior pages (type 0x05) to organize data. Traverse from rootpage to find all leaf pages containing actual data.

10. **Corruption can affect any layer**: Bit flips can damage the file header, schema page, data page headers, cell pointers, serial types, or actual data. Each layer requires different recovery strategies.

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
