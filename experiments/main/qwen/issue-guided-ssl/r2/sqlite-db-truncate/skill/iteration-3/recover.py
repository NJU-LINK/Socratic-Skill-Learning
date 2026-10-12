#!/usr/bin/env python3
"""
SQLite Corrupted Database Recovery Script

Recovers records from corrupted SQLite databases by:
1. Extracting schema from sqlite_master (usually recoverable)
2. Parsing page structure and cell pointers when possible
3. Falling back to raw content scanning when page structures are damaged
4. Handling corrupted serial types by trying common alternatives
5. Decoding both integer and float values correctly
6. Schema-aware filtering to handle multiple tables and varying schemas
"""
import struct
import json
import re
import sys

def read_varint(data, offset):
    """Read SQLite varint. Returns (value, bytes_consumed)."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, i + 1
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if not (byte & 0x80):
                return result, i + 1
        else:
            result = (result << 8) | byte
            return result, 9
    return result, 9

def decode_with_serial_types(record_bytes, header_size, serial_types):
    """Decode record with given serial types. Returns list of (serial_type, value) or None."""
    columns = []
    data_offset = header_size
    for st in serial_types:
        if st == 0:
            columns.append((st, None))
        elif 1 <= st <= 6:
            sizes = {1:1, 2:2, 3:3, 4:4, 5:6, 6:8}
            n = sizes[st]
            if data_offset + n > len(record_bytes):
                return None
            val = int.from_bytes(record_bytes[data_offset:data_offset+n], 'big', signed=True)
            columns.append((st, val))
            data_offset += n
        elif st == 7:
            if data_offset + 8 > len(record_bytes):
                return None
            val = struct.unpack('>d', record_bytes[data_offset:data_offset+8])[0]
            columns.append((st, val))
            data_offset += 8
        elif st in (8, 9):
            columns.append((st, st - 8))
        elif st >= 12:
            if st % 2 == 0:
                n = (st - 12) // 2
                if data_offset + n > len(record_bytes):
                    return None
                columns.append((st, record_bytes[data_offset:data_offset+n]))
            else:
                n = (st - 13) // 2
                if data_offset + n > len(record_bytes):
                    return None
                raw = record_bytes[data_offset:data_offset+n]
                try:
                    text = raw.decode('utf-8', errors='strict')
                    if not all(c.isprintable() or c in '\n\r\t' for c in text):
                        return None
                    columns.append((st, text))
                except:
                    return None
            data_offset += n
        else:
            return None
    return columns

def try_decode_record(record_bytes, fix_corruption=False):
    """
    Decode a SQLite record. Returns list of (serial_type, value) tuples.
    If fix_corruption is True, tries to fix corrupted serial types.
    """
    if len(record_bytes) < 2:
        return None
    
    header_size, consumed = read_varint(record_bytes, 0)
    if header_size > len(record_bytes) or header_size < 2:
        return None
    
    offset = consumed
    serial_types = []
    while offset < header_size:
        st, c = read_varint(record_bytes, offset)
        serial_types.append(st)
        offset += c
    
    # Try to decode with original serial types
    columns = decode_with_serial_types(record_bytes, header_size, serial_types)
    if columns is not None:
        return columns
    
    # If that fails and we're fixing corruption, try common alternatives
    if fix_corruption and len(serial_types) >= 2:
        for i in range(len(serial_types)):
            original_st = serial_types[i]
            
            # Try common TEXT serial types (odd values >= 13)
            for alt_st in [0x21, 0x23, 0x25, 0x27, 0x29, 0x2b, 0x2d, 0x2f]:
                if alt_st != original_st:
                    alt_types = serial_types.copy()
                    alt_types[i] = alt_st
                    columns = decode_with_serial_types(record_bytes, header_size, alt_types)
                    if columns is not None:
                        has_text = any(isinstance(c[1], str) and len(c[1]) > 0 for c in columns)
                        if has_text:
                            return columns
            
            # Try common integer serial types
            for alt_st in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06]:
                if alt_st != original_st:
                    alt_types = serial_types.copy()
                    alt_types[i] = alt_st
                    columns = decode_with_serial_types(record_bytes, header_size, alt_types)
                    if columns is not None:
                        return columns
            
            # Try float serial type
            if original_st != 0x07:
                alt_types = serial_types.copy()
                alt_types[i] = 0x07
                columns = decode_with_serial_types(record_bytes, header_size, alt_types)
                if columns is not None:
                    return columns
    
    return None

def is_schema_record(cols):
    """Check if a record looks like a sqlite_master schema record."""
    if len(cols) != 5:
        return False
    
    col_types = [c[0] for c in cols]
    text_count = sum(1 for ct in col_types if ct >= 13 and ct % 2 == 1)
    
    if text_count < 3:
        return False
    
    # Check if first column is a schema object type
    first_val = cols[0][1]
    if isinstance(first_val, str) and first_val in ['table', 'index', 'view', 'trigger']:
        return True
    
    return False

def extract_schema(data, page_size):
    """
    Extract schema information from sqlite_master table.
    Returns list of (table_name, create_sql) tuples.
    """
    schema = []
    
    if len(data) < page_size:
        return schema
    
    page_data = data[0:page_size]
    hdr_offset = 100
    
    if len(page_data) < hdr_offset + 8:
        return schema
    
    page_type = page_data[hdr_offset]
    
    if page_type == 0x0D:
        cell_count = int.from_bytes(page_data[hdr_offset+3:hdr_offset+5], 'big')
        ptr_start = hdr_offset + 8
        
        for i in range(min(cell_count, 500)):
            ptr_off = ptr_start + i * 2
            if ptr_off + 2 > len(page_data):
                break
            cell_off = int.from_bytes(page_data[ptr_off:ptr_off+2], 'big')
            if cell_off >= len(page_data):
                continue
            
            try:
                payload_len, c1 = read_varint(page_data, cell_off)
                rowid, c2 = read_varint(page_data, cell_off + c1)
                rec_start = cell_off + c1 + c2
                rec_bytes = page_data[rec_start:rec_start + payload_len]
                
                if len(rec_bytes) < 3:
                    continue
                
                cols = try_decode_record(rec_bytes, fix_corruption=False)
                if not cols:
                    continue
                
                if is_schema_record(cols):
                    values = [c[1] for c in cols]
                    text_values = [v for v in values if isinstance(v, str)]
                    if len(text_values) >= 3:
                        table_type = text_values[0]
                        table_name = text_values[1]
                        create_sql = text_values[-1]
                        
                        if table_type == 'table' and create_sql.startswith('CREATE TABLE'):
                            schema.append((table_name, create_sql))
            except:
                pass
    
    return schema

def recover_all_records(data, page_size):
    """
    Recover all valid records from all pages.
    Returns list of (page_num, rowid, cols) tuples.
    No cross-page dedup — different tables share rowid space.
    """
    all_records = []
    
    for page_num in range(len(data) // page_size):
        page_start = page_num * page_size
        page_data = data[page_start:page_start + page_size]
        hdr_offset = 100 if page_num == 0 else 0
        
        if len(page_data) < hdr_offset + 8:
            continue
        
        page_type = page_data[hdr_offset]
        
        # Per-page seen set (a single leaf page won't have dup rowids)
        seen_on_page = set()
        
        # Strategy 1: Cell pointer parsing for leaf table pages
        if page_type == 0x0D:
            cell_count = int.from_bytes(page_data[hdr_offset+3:hdr_offset+5], 'big')
            ptr_start = hdr_offset + 8
            
            for i in range(min(cell_count, 500)):
                ptr_off = ptr_start + i * 2
                if ptr_off + 2 > len(page_data):
                    break
                cell_off = int.from_bytes(page_data[ptr_off:ptr_off+2], 'big')
                if cell_off >= len(page_data):
                    continue
                
                try:
                    payload_len, c1 = read_varint(page_data, cell_off)
                    rowid, c2 = read_varint(page_data, cell_off + c1)
                    rec_start = cell_off + c1 + c2
                    rec_bytes = page_data[rec_start:rec_start + payload_len]
                    
                    if len(rec_bytes) < 3:
                        continue
                    
                    if rowid in seen_on_page:
                        continue
                    seen_on_page.add(rowid)
                    
                    cols = try_decode_record(rec_bytes, fix_corruption=True)
                    if cols:
                        all_records.append((page_num, rowid, cols))
                except:
                    pass
        
        # Strategy 2: Raw content scan (fallback)
        scan_start = 100 if page_num == 0 else 0
        for off in range(scan_start, len(page_data) - 10):
            if page_data[off] & 0x80:
                continue
            payload_len = page_data[off]
            if payload_len < 5 or payload_len > 127:
                continue
            if off + 1 + payload_len > len(page_data):
                continue
            
            if page_data[off + 1] & 0x80:
                continue
            rowid = page_data[off + 1]
            
            rec_start = off + 2
            rec = page_data[rec_start:rec_start + payload_len]
            if len(rec) < 3:
                continue
            
            header_size = rec[0]
            if header_size < 2 or header_size > payload_len:
                continue
            
            if rowid in seen_on_page:
                continue
            
            try:
                cols = try_decode_record(rec, fix_corruption=True)
                if cols:
                    all_records.append((page_num, rowid, cols))
            except:
                continue
    
    return all_records

def recover_from_corrupted_db(filepath, record_filter=None):
    """
    Recover records from a corrupted SQLite database.
    
    Args:
        filepath: Path to the corrupted database file
        record_filter: Optional function that takes decoded columns and returns True if record should be included
    
    Returns:
        Tuple of (list of recovered records, list of schema tuples)
    """
    with open(filepath, 'rb') as f:
        data = f.read()
    
    # Get page size from header (bytes 16-17, big-endian)
    page_size = int.from_bytes(data[16:18], 'big')
    if page_size == 1:
        page_size = 65536
    
    # Extract schema if possible
    schema = extract_schema(data, page_size)
    
    # Recover all records (list of tuples, no cross-page dedup)
    all_records = recover_all_records(data, page_size)
    
    # Filter and format records
    result = []
    
    for page_num, rowid, cols in all_records:
        # Skip schema records
        if is_schema_record(cols):
            continue
        
        # Apply custom filter if provided
        if record_filter and not record_filter(cols):
            continue
        
        # Convert to dictionary format
        record = {}
        for i, (serial_type, val) in enumerate(cols):
            if val is None:
                record[f'col{i}'] = None
            elif isinstance(val, bytes):
                record[f'col{i}'] = val.hex()
            elif isinstance(val, float):
                if val == int(val):
                    record[f'col{i}'] = int(val)
                else:
                    record[f'col{i}'] = val
            else:
                record[f'col{i}'] = val
        
        result.append(record)
    
    return result, schema

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: recover.py <input.db> <output.json>")
        sys.exit(1)
    
    input_db = sys.argv[1]
    output_json = sys.argv[2]
    
    result, schema = recover_from_corrupted_db(input_db)
    
    with open(output_json, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Extracted schema: {len(schema)} tables")
    for table_name, create_sql in schema:
        print(f"  - {table_name}: {create_sql[:80]}...")
    
    print(f"\nRecovered {len(result)} records")
    if result:
        print(f"Sample record: {json.dumps(result[0], indent=2)}")
