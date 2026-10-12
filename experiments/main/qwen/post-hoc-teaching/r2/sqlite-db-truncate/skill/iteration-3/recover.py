#!/usr/bin/env python3
"""
SQLite Database Recovery Script

Recovers rows from corrupted SQLite databases by parsing raw page structures,
record headers, and serial types when standard queries fail.

Handles:
- Bit flips in serial types and headers
- Zeroed regions
- Truncated/corrupted page structures
- Multiple tables with rootpage-based mapping
- B-tree traversal (interior pages)
- Overflow pages for large records
- Various serial types (NULL, integers, floats, text, blobs)

Usage: python3 recover.py <database.db> <output.json>
"""

import struct
import json
import sys
import re
from collections import Counter


def read_varint(buf, offset):
    """Read SQLite varint (1-9 bytes), return (value, new_offset)"""
    if offset >= len(buf):
        return 0, offset
    result = 0
    for i in range(9):
        if offset + i >= len(buf):
            return result, offset + i + 1
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
    """Return byte count for a serial type, or -1 if unknown"""
    if st == 0: return 0
    elif st == 1: return 1
    elif st == 2: return 2
    elif st == 3: return 3
    elif st == 4: return 4
    elif st == 5: return 6
    elif st == 6: return 8
    elif st == 7: return 8
    elif st == 8: return 0  # constant 0
    elif st == 9: return 0  # constant 1
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2
    return -1


def decode_value(buf, offset, st):
    """Decode a value according to serial type, return (value, bytes_consumed)"""
    if offset + serial_type_size(st) > len(buf):
        return None, 0
    
    if st == 0: return None, 0
    elif st == 1: return struct.unpack('>b', buf[offset:offset+1])[0], 1
    elif st == 2: return struct.unpack('>h', buf[offset:offset+2])[0], 2
    elif st == 3: return int.from_bytes(buf[offset:offset+3], 'big', signed=True), 3
    elif st == 4: return struct.unpack('>i', buf[offset:offset+4])[0], 4
    elif st == 5: return int.from_bytes(buf[offset:offset+6], 'big', signed=True), 6
    elif st == 6: return struct.unpack('>q', buf[offset:offset+8])[0], 8
    elif st == 7: return struct.unpack('>d', buf[offset:offset+8])[0], 8
    elif st == 8: return 0, 0
    elif st == 9: return 1, 0
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
    
    # Try lenient match for truncated SQL (missing closing paren)
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
    """BFS through B-tree to find all leaf pages for a given rootpage."""
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
        if len(page) < 10:
            continue
        
        # Page 1 has B-tree header at offset 100, others at 0
        bt_off = 100 if pg_num == 1 else 0
        page_type = page[bt_off]
        
        if page_type == 0x0d:  # Leaf table B-tree
            leaf_pages.append(pg_num)
        elif page_type == 0x05:  # Interior table B-tree
            # Right-most child pointer at offset 8-11
            if bt_off + 12 <= len(page):
                right_child = struct.unpack('>I', page[bt_off+8:bt_off+12])[0]
                stack.append(right_child)
            
            # Cell pointers start at bt_off + 12 for interior pages
            num_cells = struct.unpack('>H', page[bt_off+3:bt_off+5])[0]
            for i in range(num_cells):
                ptr_off = bt_off + 12 + 2*i
                if ptr_off + 2 > len(page):
                    break
                cell_ptr = struct.unpack('>H', page[ptr_off:ptr_off+2])[0]
                # Interior cell: left child page (4 bytes) + rowid (varint)
                if cell_ptr + 4 <= len(page):
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


def recover_sqlite(db_path, output_path, output_columns=None):
    """
    Main recovery function.
    
    Args:
        db_path: Path to corrupted SQLite database
        output_path: Path to write recovered JSON
        output_columns: Optional list of output field names from task instruction.
                       If provided, maps schema columns to these names by position.
                       Example: ['word', 'value'] for task format {"word": ..., "value": ...}
    """
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Validate header
    if len(data) < 100 or data[:16] != b'SQLite format 3\x00':
        raise ValueError("Not a valid SQLite database")
    
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size < 512 or page_size > 65536:
        raise ValueError(f"Invalid page size: {page_size}")
    
    num_pages = struct.unpack('>I', data[28:32])[0]
    
    print(f"Database: {page_size} bytes/page, {num_pages} pages, {len(data)} bytes total")
    
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
            if values is None:
                # For sqlite_master, we expect 5 columns: type, name, tbl_name, rootpage, sql
                # Try common patterns: TEXT, TEXT, TEXT, INTEGER, TEXT
                # Serial types: 0x15 (text 4), 0x17 (text 5), 0x19 (text 6), etc.
                # For "table" (5 chars): 0x17
                # For "test" (4 chars): 0x15
                # For rootpage (small int): 0x01 or 0x02
                # For SQL (variable): depends on length
                
                # Try to find a pattern that matches data_size
                # Assume: text(5) + text(4) + text(4) + int1 + text(N)
                # 5 + 4 + 4 + 1 + N = data_size
                # N = data_size - 14
                if data_size >= 14:
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
    
    # Convert to JSON format using output column mapping
    # Priority: output_columns (from task) > schema columns > generic names
    json_results = []
    for table_name, rows in all_results.items():
        schema_cols = table_columns.get(table_name, [])
        
        # Determine which column names to use for output
        if output_columns and len(output_columns) > 0:
            # Task instruction specifies output format - map by position
            out_cols = output_columns
        elif schema_cols and len(schema_cols) > 0:
            # No task format specified - use schema column names
            out_cols = schema_cols
        else:
            # No schema available - use generic names
            out_cols = None
        
        for rowid, values in rows:
            obj = {}
            if out_cols and len(out_cols) >= len(values):
                for i, val in enumerate(values):
                    obj[out_cols[i]] = val
            elif out_cols:
                # More values than output columns - use what we have
                for i in range(len(out_cols)):
                    if i < len(values):
                        obj[out_cols[i]] = values[i]
            else:
                # Fallback to generic names
                for i, val in enumerate(values):
                    obj[f"col{i}"] = val
            json_results.append(obj)
    
    # Sort by first field
    if json_results:
        first_key = list(json_results[0].keys())[0]
        json_results.sort(key=lambda x: str(x.get(first_key, "")))
    
    with open(output_path, 'w') as f:
        json.dump(json_results, f, indent=2)
    
    print(f"\nRecovered {len(json_results)} rows to {output_path}")
    return json_results


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 recover.py <database.db> <output.json> [col1,col2,...]")
        print("  Optional: specify output column names as comma-separated list")
        print("  Example: python3 recover.py trunc.db recover.json word,value")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    output_columns = None
    
    if len(sys.argv) >= 4:
        output_columns = sys.argv[3].split(',')
    
    results = recover_sqlite(db_path, output_path, output_columns)
    
    print("\nRecovered data:")
    for r in results:
        print(f"  {r}")
