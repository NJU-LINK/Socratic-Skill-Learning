#!/usr/bin/env python3
"""
SQLite Database Recovery Script
Recovers rows from corrupted SQLite database files by parsing raw page structures.
Handles bit-flip corruption, zeroed regions, and damaged headers.
"""
import struct
import json
import re
import sys
from typing import List, Dict, Any, Optional, Tuple


def read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    """
    Read a SQLite varint (1-9 bytes).
    Returns (value, bytes_consumed).
    """
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, i
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, i + 1
        else:
            # 9th byte uses all 8 bits
            result = (result << 8) | byte
            return result, 9
    return result, 9


def serial_type_size(serial_type: int) -> int:
    """Return the byte size for a given serial type."""
    if serial_type == 0:
        return 0  # NULL
    elif serial_type == 1:
        return 1  # 8-bit signed integer
    elif serial_type == 2:
        return 2  # 16-bit signed integer
    elif serial_type == 3:
        return 3  # 24-bit signed integer
    elif serial_type == 4:
        return 4  # 32-bit signed integer
    elif serial_type == 5:
        return 6  # 48-bit signed integer
    elif serial_type == 6:
        return 8  # 64-bit signed integer
    elif serial_type == 7:
        return 8  # IEEE-754 float
    elif serial_type == 8:
        return 0  # Integer constant 0
    elif serial_type == 9:
        return 0  # Integer constant 1
    elif serial_type >= 12:
        if serial_type % 2 == 0:
            return (serial_type - 12) // 2  # BLOB
        else:
            return (serial_type - 13) // 2  # TEXT
    return 0


def decode_value(serial_type: int, data: bytes, offset: int) -> Any:
    """Decode a value given its serial type and data buffer."""
    if serial_type == 0:
        return None
    elif serial_type == 1:
        return struct.unpack('>b', data[offset:offset+1])[0]
    elif serial_type == 2:
        return struct.unpack('>h', data[offset:offset+2])[0]
    elif serial_type == 3:
        b = data[offset:offset+3]
        val = (b[0] << 16) | (b[1] << 8) | b[2]
        if val & 0x800000:
            val -= 0x1000000
        return val
    elif serial_type == 4:
        return struct.unpack('>i', data[offset:offset+4])[0]
    elif serial_type == 5:
        b = data[offset:offset+6]
        return int.from_bytes(b, 'big', signed=True)
    elif serial_type == 6:
        return struct.unpack('>q', data[offset:offset+8])[0]
    elif serial_type == 7:
        return struct.unpack('>d', data[offset:offset+8])[0]
    elif serial_type == 8:
        return 0
    elif serial_type == 9:
        return 1
    elif serial_type >= 12:
        if serial_type % 2 == 0:
            length = (serial_type - 12) // 2
            return data[offset:offset+length]
        else:
            length = (serial_type - 13) // 2
            return data[offset:offset+length].decode('utf-8', errors='replace')
    return None


def parse_cell(data: bytes, cell_offset: int, known_schema: Optional[List[int]] = None) -> Optional[Dict]:
    """
    Parse a single cell with corruption-tolerant fallback.
    Returns dict with rowid, columns, serial_types, payload_size, corrupted flag.
    """
    off = cell_offset
    
    # Payload size (varint)
    payload_size, n = read_varint(data, off)
    off += n
    
    # Rowid (varint)
    rowid, n = read_varint(data, off)
    off += n
    
    # Record payload starts here
    record_start = off
    
    # Header size (varint, includes itself)
    header_size, n = read_varint(data, off)
    off += n
    
    # Read serial types from header
    serial_types = []
    hdr_end = record_start + header_size
    while off < hdr_end:
        st, n = read_varint(data, off)
        serial_types.append(st)
        off += n
    
    # Data area starts after header
    data_off = hdr_end
    
    # Sanity check: does the declared serial type layout fit within the payload?
    expected_data_size = sum(serial_type_size(st) for st in serial_types)
    actual_data_size = payload_size - header_size
    
    if expected_data_size != actual_data_size or expected_data_size < 0:
        # CORRUPTION: serial types don't match payload size
        # Use payload_size as ground truth - read exactly actual_data_size bytes
        print(f"  CORRUPTION at cell rowid={rowid}: serial types imply {expected_data_size} data bytes, "
              f"but payload has {actual_data_size} data bytes. Using payload size as ground truth.", file=sys.stderr)
        
        raw_data = data[data_off:data_off + actual_data_size]
        
        # If we have a known schema, use it to determine column layout
        if known_schema and len(known_schema) == 2:
            # For 2-column schema: figure out text length and value length
            # Try different value sizes: 1 byte (int), 8 bytes (float)
            for val_size in [1, 8]:
                text_size = actual_data_size - val_size
                if text_size > 0 and text_size <= 1000:  # reasonable text length
                    text_bytes = raw_data[:text_size]
                    val_bytes = raw_data[text_size:]
                    
                    # Check if text looks reasonable (printable ASCII)
                    try:
                        text_val = text_bytes.decode('utf-8')
                        if all(32 <= ord(c) < 127 for c in text_val):
                            # Decode value
                            if val_size == 1:
                                value = struct.unpack('>b', val_bytes)[0]
                            else:  # val_size == 8
                                value = struct.unpack('>d', val_bytes)[0]
                            
                            print(f"  Recovered with val_size={val_size}: text={text_val!r}, value={value}", file=sys.stderr)
                            return {
                                'rowid': rowid,
                                'payload_size': payload_size,
                                'serial_types': known_schema,
                                'columns': [text_val, value],
                                'corrupted': True
                            }
                    except:
                        pass
        
        # Fallback: pattern scan
        text_match = re.search(rb'[\x20-\x7e]{3,}', raw_data)
        if text_match:
            text_val = text_match.group().decode('ascii', errors='replace')
            text_end = text_match.end()
            remaining = raw_data[text_end:]
            if len(remaining) >= 8:
                val = struct.unpack('>d', remaining[:8])[0]
            elif len(remaining) >= 1:
                val = remaining[0]
            else:
                val = None
            return {
                'rowid': rowid,
                'payload_size': payload_size,
                'serial_types': serial_types,
                'columns': [text_val, val],
                'corrupted': True
            }
    
    # Normal path: serial types are consistent with payload size
    columns = []
    data_off = hdr_end
    for st in serial_types:
        try:
            val = decode_value(st, data, data_off)
            columns.append(val)
            data_off += serial_type_size(st)
        except Exception as e:
            print(f"  Warning: failed to decode serial type 0x{st:02x} at offset 0x{data_off:04x}: {e}", file=sys.stderr)
            columns.append(None)
            data_off += serial_type_size(st)
    
    return {
        'rowid': rowid,
        'payload_size': payload_size,
        'serial_types': serial_types,
        'columns': columns,
        'corrupted': False
    }


def parse_leaf_table_page(data: bytes, page_offset: int, page_size: int) -> List[Dict]:
    """Parse cells from a leaf table B-tree page."""
    page = data[page_offset:page_offset + page_size]
    page_type = page[0]
    
    if page_type != 0x0D:  # Only leaf table pages
        return []
    
    num_cells = struct.unpack('>H', page[3:5])[0]
    
    cells = []
    for i in range(num_cells):
        ptr_offset = 8 + 2 * i
        if ptr_offset + 2 > len(page):
            break
        cell_ptr = struct.unpack('>H', page[ptr_offset:ptr_offset+2])[0]
        
        try:
            cell = parse_cell(data, page_offset + cell_ptr)
            if cell is not None:
                cells.append(cell)
        except Exception as e:
            print(f"  Warning: failed to parse cell at offset 0x{page_offset + cell_ptr:04x}: {e}", file=sys.stderr)
    
    return cells


def recover_database(db_path: str) -> List[Dict]:
    """Main recovery function."""
    data = open(db_path, 'rb').read()
    
    # Read page size from header (bytes 16-17)
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    
    total_pages = len(data) // page_size
    print(f"Page size: {page_size}, Total pages: {total_pages}", file=sys.stderr)
    
    # Try to recover schema from page 1 (sqlite_master)
    schema_text = None
    schema_match = re.search(rb'CREATE TABLE\s+\w+\s*\([^)]+\)', data[:page_size])
    if schema_match:
        schema_text = schema_match.group().decode('utf-8', errors='replace')
        print(f"Schema found: {schema_text}", file=sys.stderr)
    
    # Parse all pages for leaf table cells
    all_rows = []
    known_schema = None
    
    for page_num in range(total_pages):
        page_offset = page_num * page_size
        page_type = data[page_offset]
        
        if page_type == 0x0D:  # Leaf table page
            print(f"Page {page_num+1}: leaf table page", file=sys.stderr)
            cells = parse_leaf_table_page(data, page_offset, page_size)
            
            # Learn schema from first intact cell
            for cell in cells:
                if not cell.get('corrupted') and known_schema is None:
                    known_schema = cell['serial_types']
                    print(f"  Learned schema: {[hex(s) for s in known_schema]}", file=sys.stderr)
            
            # Re-parse corrupted cells with known schema
            if known_schema:
                for i, cell in enumerate(cells):
                    if cell.get('corrupted'):
                        try:
                            # Get the cell pointer
                            ptr = struct.unpack('>H', data[page_offset+8+2*i:page_offset+10+2*i])[0]
                            fixed = parse_cell(data, page_offset + ptr, known_schema)
                            cells[i] = fixed
                        except Exception as e:
                            print(f"  Warning: failed to re-parse corrupted cell: {e}", file=sys.stderr)
            
            for cell in cells:
                all_rows.append(cell)
                print(f"  rowid={cell['rowid']}, serial_types={[hex(s) for s in cell['serial_types']]}, "
                      f"values={cell['columns']}, corrupted={cell.get('corrupted', False)}", file=sys.stderr)
    
    return all_rows


def format_output(rows: List[Dict]) -> List[Dict]:
    """Format recovered rows into the required JSON output."""
    results = []
    for row in rows:
        cols = row['columns']
        if len(cols) >= 2:
            word = cols[0]
            value = cols[1]
            
            # Convert float to int if it's a whole number
            if isinstance(value, float) and value == int(value):
                value = int(value)
            
            results.append({"word": str(word), "value": value})
    
    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python recover.py <database_path> [output_json_path]", file=sys.stderr)
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'
    
    rows = recover_database(db_path)
    output = format_output(rows)
    
    # Sort by word for consistent output
    output.sort(key=lambda x: x['word'])
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nRecovered {len(output)} rows to {output_path}", file=sys.stderr)
