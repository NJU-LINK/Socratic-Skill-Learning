#!/usr/bin/env python3
"""
SQLite Database Carver - Recovers records from corrupted SQLite databases.

This carver implements corruption-tolerant SQLite record recovery by:
1. Parsing the database header to find page size and structure
2. Reading cell pointers from b-tree pages
3. Parsing cells with varint decoding and serial type interpretation
4. Validating payload length consistency
5. Attempting single-bit-flip recovery for corrupted serial types

Usage:
    python3 sqlite_carve.py <input.db> <output.json>
"""

import sys
import struct
import json

# SQLite serial type to byte width mapping
SERIAL_WIDTHS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8, 7: 8, 8: 0, 9: 0}


def varint(data: bytes, offset: int) -> tuple:
    """Parse SQLite varint. Returns (value, next_offset) or (None, offset)."""
    if offset >= len(data):
        return None, offset
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return None, offset
        byte = data[offset + i]
        if i == 8:
            result = (result << 8) | byte
            return result, offset + 9
        else:
            result = (result << 7) | (byte & 0x7f)
            if not (byte & 0x80):
                return result, offset + i + 1
    return result, offset + 9


def serial_type_width(serial_type: int) -> int:
    """Get byte width for a serial type."""
    if serial_type in SERIAL_WIDTHS:
        return SERIAL_WIDTHS[serial_type]
    elif serial_type >= 12 and serial_type % 2 == 0:
        return (serial_type - 12) // 2  # BLOB
    elif serial_type >= 13 and serial_type % 2 == 1:
        return (serial_type - 13) // 2  # TEXT
    return None


def decode_value(serial_type: int, data: bytes) -> object:
    """Decode value based on serial type."""
    if serial_type == 0:
        return None
    elif 1 <= serial_type <= 6:
        return int.from_bytes(data, byteorder='big', signed=True)
    elif serial_type == 7:
        return struct.unpack('>d', data)[0]
    elif serial_type == 8:
        return 0
    elif serial_type == 9:
        return 1
    elif serial_type >= 13 and serial_type % 2 == 1:
        try:
            return data.decode('utf-8')
        except:
            return data.decode('utf-8', errors='replace')
    elif serial_type >= 12 and serial_type % 2 == 0:
        return data
    return None


def try_fix_serial_types(header_len: int, serial_types: list, expected_payload_len: int) -> list:
    """
    Attempt to recover from bit-flipped serial types.
    Tries single-bit flips to find a configuration where
    header_len + sum(serial_widths) == expected_payload_len
    """
    current_width = header_len + sum(serial_type_width(st) or 0 for st in serial_types)
    if current_width == expected_payload_len:
        return serial_types
    
    for i, st in enumerate(serial_types):
        for bit in range(8):
            flipped = st ^ (1 << bit)
            if flipped == st:
                continue
            test_types = list(serial_types)
            test_types[i] = flipped
            test_width = header_len + sum(serial_type_width(t) or 0 for t in test_types)
            if test_width == expected_payload_len:
                return test_types
    return None


def parse_record(data: bytes, offset: int, expected_payload_len: int) -> tuple:
    """
    Parse SQLite record with corruption recovery.
    Format: header_len[varint] | serial_types... | values...
    """
    # Parse header length varint and get position after it
    header_len, pos = varint(data, offset)
    if header_len is None or header_len < 1:
        return None, 0
    
    header_end = offset + header_len
    if header_end > len(data):
        return None, 0
    
    # Parse serial types from header - start at position after header_len varint
    serial_types = []
    while pos < header_end:
        st, new_pos = varint(data, pos)
        if st is None:
            break
        serial_types.append(st)
        pos = new_pos
    
    # Calculate total width
    total_width = header_len
    for st in serial_types:
        w = serial_type_width(st)
        if w is None:
            return None, 0
        total_width += w
    
    # Validate and try recovery if needed
    if expected_payload_len is not None and total_width != expected_payload_len:
        recovered = try_fix_serial_types(header_len, serial_types, expected_payload_len)
        if recovered:
            serial_types = recovered
            total_width = header_len + sum(serial_type_width(t) or 0 for t in serial_types)
        else:
            return None, 0
    
    # Extract values
    values = []
    value_pos = header_end
    for st in serial_types:
        width = serial_type_width(st)
        if value_pos + width > len(data):
            return None, 0
        raw = data[value_pos:value_pos + width]
        val = decode_value(st, raw)
        values.append(val)
        value_pos += width
    
    return values, total_width


def parse_table_leaf_cell(data: bytes, offset: int) -> tuple:
    """
    Parse table leaf b-tree cell.
    Format: payload_len[varint] | rowid[varint] | record
    """
    payload_len, pos = varint(data, offset)
    if payload_len is None:
        return None, None, "Failed to parse payload_len"
    
    rowid, pos = varint(data, pos)
    if rowid is None:
        return None, None, "Failed to parse rowid"
    
    values, consumed = parse_record(data, pos, payload_len)
    if values is None:
        return None, rowid, f"Failed to parse record at offset {pos}"
    
    return values, rowid, None


def extract_cell_pointers(data: bytes, page_offset: int) -> list:
    """Extract cell pointers from a b-tree page header."""
    page_type = data[page_offset]
    if page_type != 0x0d:  # Not a leaf table page
        return []
    
    num_cells = struct.unpack('>H', data[page_offset + 3:page_offset + 5])[0]
    
    pointers = []
    for i in range(num_cells):
        ptr_offset = page_offset + 8 + (i * 2)
        if ptr_offset + 2 > len(data):
            break
        ptr = struct.unpack('>H', data[ptr_offset:ptr_offset + 2])[0]
        pointers.append(ptr)
    
    return pointers


def carve_database(db_path: str, page_num: int = 2) -> list:
    """
    Carve records from a corrupted SQLite database.
    
    Returns list of dicts with rowid, word, value for records that:
    1. Are structurally valid (pass payload length check)
    2. Have recoverable serial types (with bit-flip correction if needed)
    """
    with open(db_path, 'rb') as f:
        data = f.read()
    
    if len(data) < 100:
        return []
    
    # Read page size from header
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    page_offset = (page_num - 1) * page_size
    if page_offset >= len(data):
        return []
    
    pointers = extract_cell_pointers(data, page_offset)
    
    records = []
    seen_rowids = set()
    
    for i, ptr in enumerate(pointers):
        abs_offset = page_offset + ptr
        if abs_offset >= len(data):
            print(f"  Cell {i}: pointer 0x{ptr:04x} -> offset 0x{abs_offset:04x} out of bounds", file=sys.stderr)
            continue
        
        values, rowid, error = parse_table_leaf_cell(data, abs_offset)
        
        if error:
            print(f"  Cell {i}: pointer 0x{ptr:04x} -> offset 0x{abs_offset:04x} ERROR: {error}", file=sys.stderr)
            continue
        
        if len(values) >= 2:
            word = str(values[0]) if values[0] is not None else ""
            val = values[1]
            
            # Skip duplicate rowids (keep first)
            if rowid in seen_rowids:
                print(f"  Cell {i}: pointer 0x{ptr:04x} -> rowid {rowid} DUPLICATE (skipped)", file=sys.stderr)
                continue
            seen_rowids.add(rowid)
            
            print(f"  Cell {i}: pointer 0x{ptr:04x} -> rowid {rowid}, word='{word}', value={val}", file=sys.stderr)
            
            records.append({
                'rowid': rowid,
                'word': word,
                'value': val
            })
    
    records.sort(key=lambda r: r['word'])
    return records


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.db> <output.json>", file=sys.stderr)
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    
    print(f"DEBUG: Carving {db_path}...", file=sys.stderr)
    sys.stderr.flush()
    records = carve_database(db_path)
    print(f"DEBUG: Found {len(records)} structurally valid records", file=sys.stderr)
    sys.stderr.flush()
    
    # Format output
    output = [{'word': r['word'], 'value': r['value']} for r in records]
    
    print(f"DEBUG: Writing {len(output)} records to {output_path}", file=sys.stderr)
    sys.stderr.flush()
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Recovered {len(output)} records to {output_path}")


if __name__ == '__main__':
    main()
