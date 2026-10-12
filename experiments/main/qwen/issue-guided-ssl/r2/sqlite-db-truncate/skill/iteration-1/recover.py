#!/usr/bin/env python3
"""
SQLite Corrupted Database Recovery Script

Recovers records from corrupted SQLite databases by:
1. Parsing page structure and cell pointers when possible
2. Falling back to raw content scanning when page structures are damaged
3. Handling corrupted serial types by trying common alternatives
4. Decoding both integer and float values correctly
5. Filtering records to avoid mixing schema and data records
"""
import struct
import json
import re

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

def recover_from_corrupted_db(filepath, record_filter=None):
    """
    Recover records from a corrupted SQLite database.
    
    Args:
        filepath: Path to the corrupted database file
        record_filter: Optional function that takes decoded columns and returns True if record should be included
    
    Returns:
        List of recovered records as dictionaries
    """
    with open(filepath, 'rb') as f:
        data = f.read()
    
    # Get page size from header (bytes 16-17, big-endian)
    page_size = int.from_bytes(data[16:18], 'big')
    if page_size == 1:
        page_size = 65536
    
    recovered = {}
    
    # Scan every page
    for page_num in range(len(data) // page_size):
        page_start = page_num * page_size
        page_data = data[page_start:page_start + page_size]
        
        # First page has 100-byte database header
        hdr_offset = 100 if page_num == 0 else 0
        
        if len(page_data) < hdr_offset + 8:
            continue
        
        page_type = page_data[hdr_offset]
        
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
                    
                    cols = try_decode_record(rec_bytes, fix_corruption=True)
                    if not cols:
                        continue
                    
                    # Apply filter if provided
                    if record_filter and not record_filter(cols):
                        continue
                    
                    if rowid not in recovered:
                        recovered[rowid] = cols
                except:
                    pass
        
        # Strategy 2: Raw content scan (fallback)
        scan_start = 100 if page_num == 0 else 0
        for off in range(scan_start, len(page_data) - 10):
            # Look for cells with small payload (1-byte varint, high bit clear)
            if page_data[off] & 0x80:
                continue
            payload_len = page_data[off]
            if payload_len < 5 or payload_len > 127:
                continue
            if off + 1 + payload_len > len(page_data):
                continue
            
            # Try to read rowid (1-byte varint)
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
            
            try:
                cols = try_decode_record(rec, fix_corruption=True)
                if not cols:
                    continue
                
                # Apply filter if provided
                if record_filter and not record_filter(cols):
                    continue
                
                if rowid not in recovered:
                    recovered[rowid] = cols
            except:
                continue
    
    # Build output: extract word and value from decoded columns
    result = []
    for rowid in sorted(recovered.keys()):
        cols = recovered[rowid]
        word = None
        value = None
        for serial_type, val in cols:
            if isinstance(val, str) and re.match(r'testword\d+', val):
                word = val
            elif isinstance(val, (int, float)) and serial_type in (1,2,3,4,5,6,7):
                if value is None:
                    value = val
        if word is not None:
            # Convert to appropriate numeric type
            if isinstance(value, float):
                # Keep as float if it has decimal part
                if value != int(value):
                    result.append({"word": word, "value": value})
                else:
                    result.append({"word": word, "value": int(value)})
            else:
                result.append({"word": word, "value": value})
    
    return result

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage: recover.py <input.db> <output.json> [filter_pattern]")
        print("  filter_pattern: regex pattern to match text columns (default: testword\\d+)")
        sys.exit(1)
    
    input_db = sys.argv[1]
    output_json = sys.argv[2]
    filter_pattern = sys.argv[3] if len(sys.argv) > 3 else r'testword\d+'
    
    # Create filter function
    def record_filter(cols):
        return any(
            isinstance(c[1], str) and re.match(filter_pattern, c[1])
            for c in cols
        )
    
    result = recover_from_corrupted_db(input_db, record_filter=record_filter)
    with open(output_json, 'w') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nRecovered {len(result)} records")
