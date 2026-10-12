#!/usr/bin/env python3
"""
SQLite Database Recovery Tool
Recovers rows from corrupted SQLite files by parsing binary format directly.

Handles:
- Bit-flip corruption (schema-guided repair of serial types)
- Zeroed regions (skip invalid cells)
- Truncated files (process available pages)
- Damaged page structures (scan for valid leaf pages)
- Overflow pages (reassembly of large records)
- Multiple tables (schema-guided b-tree traversal)
- Various serial types (NULL, integers, floats, text, blobs)

Usage:
    python3 recover_sqlite.py <input.db> <output.json> [col1,col2,...]

If column_names are not provided, attempts to extract from sqlite_master.
Column names can also be specified as comma-separated: "word,value"
"""
import struct
import json
import sys
import re
import os


def read_varint(buf, offset):
    """Read SQLite varint (1-9 bytes, big-endian variable-length integer)."""
    result = 0
    for i in range(9):
        if offset + i >= len(buf):
            return result, offset + i
        byte = buf[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80:
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset + 9


def serial_type_size(st):
    """Get byte size for a SQLite serial type code."""
    if st == 0: return 0    # NULL
    elif st == 1: return 1  # 8-bit signed int
    elif st == 2: return 2  # 16-bit signed int
    elif st == 3: return 3  # 24-bit signed int
    elif st == 4: return 4  # 32-bit signed int
    elif st == 5: return 6  # 48-bit signed int
    elif st == 6: return 8  # 64-bit signed int
    elif st == 7: return 8  # 64-bit IEEE 754 float
    elif st == 8: return 0  # Constant 0
    elif st == 9: return 0  # Constant 1
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2  # BLOB
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2  # TEXT
    else: return -1  # Reserved/invalid


def type_affinity(col_type_str):
    """Map SQL type string to expected serial type category."""
    if not col_type_str:
        return 'any'
    t = col_type_str.upper()
    if 'INT' in t:
        return 'integer'   # serial types 1-6, also 0 (NULL)
    elif 'REAL' in t or 'FLOAT' in t or 'DOUBLE' in t:
        return 'numeric'   # serial types 1-7, also 0
    elif 'TEXT' in t or 'CHAR' in t or 'CLOB' in t:
        return 'text'       # serial types 0, or odd >= 13
    elif 'BLOB' in t:
        return 'blob'       # serial types 0, or even >= 12
    return 'any'


def is_compatible(serial_type, affinity):
    """Check if a serial type is compatible with expected column affinity."""
    if affinity == 'any':
        return True
    if serial_type == 0:
        return True  # NULL is always valid
    if affinity == 'integer':
        return 1 <= serial_type <= 6
    if affinity == 'numeric':
        return 1 <= serial_type <= 7
    if affinity == 'text':
        return serial_type >= 13 and serial_type % 2 == 1
    if affinity == 'blob':
        return serial_type >= 12 and serial_type % 2 == 0
    return True


def try_fix_serial_types(serial_types, header_size, payload_len, expected_types=None):
    """
    Try to repair corrupted serial types via single-bit flips.
    Uses schema information to disambiguate when multiple corrections are valid.
    
    Args:
        serial_types: List of serial type codes from the record header
        header_size: Size of the record header in bytes
        payload_len: Expected total payload length
        expected_types: Optional list of SQL type strings for each column
    
    Returns:
        Fixed serial types if repair succeeds, None otherwise.
    """
    total = sum(serial_type_size(st) for st in serial_types)
    if header_size + total == payload_len:
        return serial_types  # Already valid

    # Compute affinities from schema
    affinities = []
    if expected_types:
        affinities = [type_affinity(t) for t in expected_types]
    
    # Collect all possible single-bit corrections
    candidates = []
    
    for i, st in enumerate(serial_types):
        for bit in range(8):
            corrected = st ^ (1 << bit)
            if serial_type_size(corrected) >= 0:
                new_types = serial_types.copy()
                new_types[i] = corrected
                new_total = sum(serial_type_size(s) for s in new_types)
                if header_size + new_total == payload_len:
                    # Score this correction
                    score = 0
                    
                    # Schema compatibility bonus (strong signal)
                    if affinities and i < len(affinities):
                        if is_compatible(corrected, affinities[i]):
                            score += 10
                    
                    # Fallback heuristic when no schema
                    if not affinities:
                        if corrected >= 13 and corrected % 2 == 1:  # TEXT
                            score += 2
                        elif corrected >= 12 and corrected % 2 == 0:  # BLOB
                            score += 1
                    
                    candidates.append((score, new_types))
    
    if candidates:
        # Return the candidate with highest score
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Try multi-bit corrections (2 bits) if single-bit didn't work
    for i, st in enumerate(serial_types):
        for bit1 in range(8):
            for bit2 in range(bit1 + 1, 8):
                corrected = st ^ (1 << bit1) ^ (1 << bit2)
                if serial_type_size(corrected) >= 0:
                    new_types = serial_types.copy()
                    new_types[i] = corrected
                    new_total = sum(serial_type_size(s) for s in new_types)
                    if header_size + new_total == payload_len:
                        # Check schema compatibility
                        if affinities and i < len(affinities):
                            if is_compatible(corrected, affinities[i]):
                                return new_types
                        else:
                            return new_types

    return None  # Cannot repair


def decode_value(buf, offset, st):
    """Decode a value according to its serial type."""
    if offset + serial_type_size(st) > len(buf):
        return None
    if st == 0:
        return None
    elif st == 1:
        return struct.unpack('>b', buf[offset:offset+1])[0]
    elif st == 2:
        return struct.unpack('>h', buf[offset:offset+2])[0]
    elif st == 3:
        return int.from_bytes(buf[offset:offset+3], 'big', signed=True)
    elif st == 4:
        return struct.unpack('>i', buf[offset:offset+4])[0]
    elif st == 5:
        return int.from_bytes(buf[offset:offset+6], 'big', signed=True)
    elif st == 6:
        return struct.unpack('>q', buf[offset:offset+8])[0]
    elif st == 7:
        return struct.unpack('>d', buf[offset:offset+8])[0]
    elif st == 8:
        return 0
    elif st == 9:
        return 1
    elif st >= 12 and st % 2 == 0:
        blen = (st - 12) // 2
        return buf[offset:offset+blen]
    elif st >= 13 and st % 2 == 1:
        tlen = (st - 13) // 2
        try:
            return buf[offset:offset+tlen].decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            return None
    return None


def read_overflow_chain(data, page_size, first_overflow_page, remaining_bytes):
    """
    Follow overflow page chain to recover remaining payload bytes.
    
    Args:
        data: Full database file contents
        page_size: Size of each page
        first_overflow_page: Page number of first overflow page
        remaining_bytes: Number of bytes to read from overflow chain
    
    Returns:
        Bytes from the overflow chain
    """
    result = bytearray()
    page_num = first_overflow_page
    bytes_left = remaining_bytes
    
    while page_num > 0 and bytes_left > 0:
        page_offset = (page_num - 1) * page_size  # Pages are 1-indexed
        if page_offset >= len(data):
            break  # Page doesn't exist (truncation)
        
        next_page = struct.unpack('>I', data[page_offset:page_offset+4])[0]
        available = page_size - 4  # First 4 bytes are the next-page pointer
        chunk = min(bytes_left, available)
        result.extend(data[page_offset+4:page_offset+4+chunk])
        bytes_left -= chunk
        page_num = next_page
    
    return bytes(result)


def calculate_local_payload_limit(page_size, reserved_space=0):
    """
    Calculate the local payload limit for table b-tree leaf cells.
    
    If payload_len > X, the record uses overflow pages.
    X = min(U - 35, (U - 12) * 64/255 - 23)
    where U = page_size - reserved_space
    """
    U = page_size - reserved_space
    X = min(U - 35, int((U - 12) * 64 / 255) - 23)
    return max(X, 0)


def parse_btree_leaf_page(page_data, full_data, page_size, page_num, is_first_page=False, 
                          expected_types=None, reserved_space=0):
    """
    Parse a b-tree leaf table page and extract (rowid, values) cells.
    Handles overflow pages for large records.
    
    Args:
        page_data: Data for this page only
        full_data: Full database file contents (for overflow chain following)
        page_size: Size of each page
        page_num: Page number (1-indexed)
        is_first_page: True if this is page 1 (has 100-byte file header)
        expected_types: Optional list of SQL type strings for schema-guided repair
        reserved_space: Reserved space per page (from header byte 20)
    
    Returns:
        List of (rowid, [values]) tuples
    """
    header_offset = 100 if is_first_page else 0
    
    if len(page_data) < header_offset + 8:
        return []
    
    flag = page_data[header_offset]
    if flag != 0x0d:  # Not a leaf table b-tree page
        return []
    
    h = header_offset
    num_cells = struct.unpack('>H', page_data[h+3:h+5])[0]
    cell_content_start = struct.unpack('>H', page_data[h+5:h+7])[0]
    
    # Sanity check on num_cells
    if num_cells > 10000:  # Unreasonable number of cells
        return []
    
    # Read and validate cell pointers
    ptrs = []
    ptr_area_end = h + 8 + num_cells * 2
    for i in range(num_cells):
        off = h + 8 + i * 2
        if off + 2 > len(page_data):
            break
        ptr = struct.unpack('>H', page_data[off:off+2])[0]
        
        # Validate pointer
        if ptr < ptr_area_end:
            continue  # Pointer overlaps with header/pointer array
        if ptr >= len(page_data):
            continue  # Pointer beyond page
        
        ptrs.append(ptr)
    
    # Calculate overflow threshold
    X = calculate_local_payload_limit(page_size, reserved_space)
    
    cells = []
    for ptr in ptrs:
        try:
            # Parse cell: payload_length, rowid, payload
            payload_len, pos = read_varint(page_data, ptr)
            if payload_len <= 0 or payload_len > 1000000:  # Sanity check
                continue
            
            rowid, pos = read_varint(page_data, pos)
            payload_start = pos
            
            # Check if payload uses overflow pages
            if payload_len > X:
                # Overflow: local payload is first X bytes
                if payload_start + X > len(page_data):
                    continue  # Truncated
                
                local_payload = page_data[payload_start:payload_start + X]
                # Last 4 bytes of local payload are the first overflow page number
                overflow_page_num = struct.unpack('>I', local_payload[-4:])[0]
                local_data = local_payload[:-4]
                
                # Read overflow chain
                remaining = payload_len - len(local_data)
                overflow_data = read_overflow_chain(full_data, page_size, 
                                                    overflow_page_num, remaining)
                
                # Reassemble full payload
                full_payload = local_data + overflow_data
                
                if len(full_payload) < payload_len:
                    continue  # Incomplete overflow chain
            else:
                # No overflow
                if payload_start + payload_len > len(page_data):
                    continue  # Truncated
                full_payload = page_data[payload_start:payload_start + payload_len]
            
            # Check for all-zero payload (zeroed corruption)
            if all(b == 0 for b in full_payload):
                continue
            
            # Parse record header
            header_size, hpos = read_varint(full_payload, 0)
            if header_size < 1 or header_size > payload_len:
                continue
            
            serial_types = []
            while hpos < header_size:
                st, hpos = read_varint(full_payload, hpos)
                serial_types.append(st)
            
            if not serial_types:
                continue
            
            # Try to fix corrupted serial types (with schema guidance)
            fixed_types = try_fix_serial_types(serial_types, header_size, 
                                               payload_len, expected_types)
            if fixed_types is None:
                continue  # Cannot repair
            
            # Decode values
            data_pos = header_size
            values = []
            valid = True
            for st in fixed_types:
                sz = serial_type_size(st)
                if sz < 0 or data_pos + sz > len(full_payload):
                    valid = False
                    break
                val = decode_value(full_payload, data_pos, st)
                if val is None and st != 0:
                    valid = False
                    break
                values.append(val)
                data_pos += sz
            
            if valid and values:
                cells.append((rowid, values))
        except (IndexError, struct.error):
            continue
    
    return cells


def parse_btree_interior_page(page_data, full_data, page_size, page_num, is_first_page=False):
    """
    Parse an interior table b-tree page and return child page numbers.
    
    Interior page cell format:
    - 4 bytes: left child page number (big-endian uint32)
    - varint: rowid
    
    The rightmost child is stored separately in the header.
    """
    header_offset = 100 if is_first_page else 0
    
    if len(page_data) < header_offset + 12:
        return []
    
    flag = page_data[header_offset]
    if flag != 0x05:  # Not an interior table b-tree page
        return []
    
    h = header_offset
    num_cells = struct.unpack('>H', page_data[h+3:h+5])[0]
    rightmost_child = struct.unpack('>I', page_data[h+8:h+12])[0]
    
    child_pages = []
    
    # Read cell pointers
    ptrs = []
    for i in range(num_cells):
        off = h + 12 + i * 2
        if off + 2 > len(page_data):
            break
        ptr = struct.unpack('>H', page_data[off:off+2])[0]
        ptrs.append(ptr)
    
    # Parse cells to get child page numbers
    for ptr in ptrs:
        if ptr >= len(page_data) - 4:
            continue
        child_page = struct.unpack('>I', page_data[ptr:ptr+4])[0]
        if child_page > 0:
            child_pages.append(child_page)
    
    # Add rightmost child
    if rightmost_child > 0:
        child_pages.append(rightmost_child)
    
    return child_pages


def parse_create_table(sql):
    """Parse CREATE TABLE statement to extract column names and types."""
    m = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\)',
                  sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    
    table_name = m.group(1)
    cols_str = m.group(2)
    columns = []
    col_types = []
    
    for col_def in cols_str.split(','):
        col_def = col_def.strip()
        if not col_def:
            continue
        # Skip constraints
        if re.match(r'(PRIMARY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)', col_def, re.IGNORECASE):
            continue
        parts = col_def.split()
        if parts:
            col_name = parts[0].strip('"').strip("'").strip('`')
            col_type = parts[1].upper() if len(parts) > 1 else 'TEXT'
            columns.append(col_name)
            col_types.append(col_type)
    
    return {'table_name': table_name, 'columns': columns, 'col_types': col_types}


def scan_for_sql_strings(data):
    """Scan raw data for CREATE TABLE statements (fallback schema recovery)."""
    schemas = []
    for m in re.finditer(rb'CREATE\s+TABLE\s+\w+\s*\([^)]+\)', data, re.IGNORECASE):
        try:
            sql = m.group(0).decode('utf-8')
            schema = parse_create_table(sql)
            if schema:
                schemas.append(schema)
        except (UnicodeDecodeError, ValueError):
            continue
    return schemas


def traverse_btree(full_data, page_size, root_page, reserved_space, expected_types=None):
    """
    Traverse a b-tree starting from root_page and recover all records.
    Handles both leaf and interior pages.
    
    Args:
        full_data: Full database file contents
        page_size: Size of each page
        root_page: Root page number (1-indexed)
        reserved_space: Reserved space per page
        expected_types: Optional list of SQL type strings for schema-guided repair
    
    Returns:
        List of (rowid, [values]) tuples
    """
    all_records = []
    pages_to_visit = [root_page]
    visited = set()
    
    while pages_to_visit:
        page_num = pages_to_visit.pop(0)
        if page_num in visited or page_num < 1:
            continue
        visited.add(page_num)
        
        page_offset = (page_num - 1) * page_size
        if page_offset >= len(full_data):
            continue
        
        page_data = full_data[page_offset:page_offset + page_size]
        if len(page_data) < 8:
            continue
        
        is_first_page = (page_num == 1)
        header_offset = 100 if is_first_page else 0
        
        if len(page_data) < header_offset + 8:
            continue
        
        flag = page_data[header_offset]
        
        if flag == 0x0d:
            # Leaf table page - extract records
            cells = parse_btree_leaf_page(page_data, full_data, page_size, page_num,
                                         is_first_page, expected_types, reserved_space)
            all_records.extend(cells)
        
        elif flag == 0x05:
            # Interior table page - get child pages
            child_pages = parse_btree_interior_page(page_data, full_data, page_size,
                                                   page_num, is_first_page)
            pages_to_visit.extend(child_pages)
    
    return all_records


def recover_sqlite(db_path, output_path, column_names=None):
    """
    Main recovery function.
    
    Args:
        db_path: Path to corrupted SQLite database
        output_path: Path for JSON output
        column_names: Optional list of column names (if known from task)
    """
    with open(db_path, 'rb') as f:
        data = f.read()
    
    if len(data) < 100:
        print("Error: File too small to be a SQLite database")
        return []
    
    # Verify magic
    magic = data[0:16]
    if magic != b'SQLite format 3\x00':
        print("Warning: Not a standard SQLite database, attempting raw recovery...")
    
    # Parse header
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    reserved_space = data[20] if len(data) > 20 else 0
    db_size_pages = struct.unpack('>I', data[28:32])[0]
    actual_pages = len(data) // page_size
    
    print(f"Page size: {page_size}, Reserved: {reserved_space}")
    print(f"Expected pages: {db_size_pages}, Actual pages: {actual_pages}")
    
    # Parse sqlite_master to get all table schemas
    tables = {}  # table_name -> schema
    rootpages = {}  # table_name -> root_page
    
    if actual_pages >= 1:
        page1 = data[0:min(page_size, len(data))]
        cells = parse_btree_leaf_page(page1, data, page_size, 1, is_first_page=True,
                                     reserved_space=reserved_space)
        for rowid, values in cells:
            if len(values) >= 5 and values[0] == 'table':
                sql = values[4]
                if isinstance(sql, str):
                    schema = parse_create_table(sql)
                    if schema:
                        table_name = schema['table_name']
                        tables[table_name] = schema
                        rootpages[table_name] = values[3]  # rootpage column
                        print(f"Found table: {table_name} at rootpage {values[3]}")
    
    # Fallback: scan for SQL strings
    if not tables:
        schemas = scan_for_sql_strings(data)
        if schemas:
            for schema in schemas:
                tables[schema['table_name']] = schema
                print(f"Found table via scan: {schema['table_name']}")
    
    # Determine column names
    if column_names:
        col_names = column_names
        col_types = None
    elif tables:
        # Use first table's schema
        first_table = list(tables.values())[0]
        col_names = first_table['columns']
        col_types = first_table['col_types']
    else:
        col_names = None
        col_types = None
    
    # Recover records from each table
    all_records = []  # List of (rowid, values, table_name, schema)
    seen = set()
    
    if tables and rootpages:
        # Traverse each table's b-tree
        for table_name, schema in tables.items():
            root_page = rootpages.get(table_name, 2)  # Default to page 2
            expected_types = schema['col_types']
            
            print(f"Recovering table: {table_name} from rootpage {root_page}")
            records = traverse_btree(data, page_size, root_page, reserved_space, expected_types)
            
            for rowid, values in records:
                key = (rowid, tuple(str(v) for v in values))
                if key not in seen:
                    seen.add(key)
                    all_records.append((rowid, values, table_name, schema))
    else:
        # Fallback: scan all pages
        for page_num in range(1, actual_pages + 1):
            page_offset = (page_num - 1) * page_size
            page_data = data[page_offset:page_offset + page_size]
            
            is_first = (page_num == 1)
            cells = parse_btree_leaf_page(page_data, data, page_size, page_num,
                                         is_first_page=is_first, reserved_space=reserved_space)
            
            for rowid, values in cells:
                # Skip sqlite_master records
                if is_first and len(values) >= 5 and values[0] in ('table', 'index', 'view', 'trigger'):
                    continue
                
                key = (rowid, tuple(str(v) for v in values))
                if key not in seen:
                    seen.add(key)
                    all_records.append((rowid, values, None, None))
    
    # Sort by rowid
    all_records.sort(key=lambda x: x[0])
    
    # Convert to JSON format
    results = []
    for rowid, values, table_name, schema in all_records:
        # Use the schema for this specific table
        if schema and len(values) == len(schema['columns']):
            row = {}
            for i, col in enumerate(schema['columns']):
                val = values[i]
                # Convert bytes to string if needed
                if isinstance(val, bytes):
                    try:
                        val = val.decode('utf-8')
                    except:
                        val = val.hex()
                row[col] = val
            results.append(row)
        elif col_names and len(values) == len(col_names):
            # Fallback to provided column names
            row = {}
            for i, col in enumerate(col_names):
                val = values[i]
                if isinstance(val, bytes):
                    try:
                        val = val.decode('utf-8')
                    except:
                        val = val.hex()
                row[col] = val
            results.append(row)
        else:
            # No schema, output raw values
            row = {"rowid": rowid, "values": values}
            results.append(row)
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Recovered {len(results)} rows to {output_path}")
    return results


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: recover_sqlite.py <input.db> <output.json> [col1,col2,...]")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    col_names = None
    
    if len(sys.argv) > 3:
        col_arg = sys.argv[3]
        col_names = [c.strip() for c in col_arg.split(',')]
    
    recover_sqlite(db_path, output_path, col_names)
