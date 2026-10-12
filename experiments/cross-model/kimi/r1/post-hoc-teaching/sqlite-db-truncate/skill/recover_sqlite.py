#!/usr/bin/env python3
"""
SQLite Database Recovery Tool
Recovers data from corrupted SQLite databases using payload-length validation
with ranked repair candidates and schema-aware classification.
"""

import struct
import json
import sys
import re


def decode_varint(data, offset):
    """Decode SQLite varint. Big-endian, 7 bits per byte, 9th byte uses 8 bits."""
    result = 0
    for i in range(8):
        if offset + i >= len(data):
            return result, i
        byte = data[offset + i]
        result = (result << 7) | (byte & 0x7f)
        if (byte & 0x80) == 0:
            return result, i + 1
    if offset + 8 < len(data):
        byte = data[offset + 8]
        result = (result << 8) | byte
        return result, 9
    return result, 8


def serial_type_size(serial_type):
    """Return data size for a serial type."""
    if serial_type == 0: return 0
    elif serial_type == 1: return 1
    elif serial_type == 2: return 2
    elif serial_type == 3: return 3
    elif serial_type == 4: return 4
    elif serial_type == 5: return 6
    elif serial_type == 6: return 8
    elif serial_type == 7: return 8
    elif serial_type == 8: return 0
    elif serial_type == 9: return 0
    elif serial_type >= 12 and serial_type % 2 == 0:
        return (serial_type - 12) // 2
    elif serial_type >= 13 and serial_type % 2 == 1:
        return (serial_type - 13) // 2
    else: return None


def parse_value(data, pos, serial_type, encoding='utf-8'):
    """Parse a single value based on serial type."""
    if serial_type == 0:
        return None, 0
    elif serial_type == 1:
        val = int.from_bytes(data[pos:pos+1], 'big', signed=True)
        return val, 1
    elif serial_type == 2:
        val = int.from_bytes(data[pos:pos+2], 'big', signed=True)
        return val, 2
    elif serial_type == 3:
        val = int.from_bytes(data[pos:pos+3], 'big', signed=True)
        return val, 3
    elif serial_type == 4:
        val = int.from_bytes(data[pos:pos+4], 'big', signed=True)
        return val, 4
    elif serial_type == 5:
        val = int.from_bytes(data[pos:pos+6], 'big', signed=True)
        return val, 6
    elif serial_type == 6:
        val = int.from_bytes(data[pos:pos+8], 'big', signed=True)
        return val, 8
    elif serial_type == 7:
        val = struct.unpack('>d', data[pos:pos+8])[0]
        return val, 8
    elif serial_type == 8:
        return 0, 0
    elif serial_type == 9:
        return 1, 0
    elif serial_type >= 12 and serial_type % 2 == 0:
        size = (serial_type - 12) // 2
        return data[pos:pos+size].hex(), size
    elif serial_type >= 13 and serial_type % 2 == 1:
        size = (serial_type - 13) // 2
        try:
            text = data[pos:pos+size].decode(encoding, errors='replace')
        except:
            text = data[pos:pos+size].hex()
        return text, size
    else:
        return None, 0


def is_valid_utf8(s):
    """Check if string is valid UTF-8 (no replacement chars)."""
    if not isinstance(s, str):
        return False
    return '\ufffd' not in s


def is_printable(s):
    """Check if string is mostly printable ASCII."""
    if not isinstance(s, str):
        return False
    if len(s) == 0:
        return False
    printable = sum(1 for c in s if 32 <= ord(c) < 127 or c in '\t\n\r')
    return printable / len(s) > 0.8


def looks_like_identifier(s):
    """Check if string looks like SQL identifier."""
    if not isinstance(s, str):
        return False
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', s))


def score_repair(serial_types, values):
    """
    Score a repair candidate. Higher = more plausible.
    """
    score = 0
    
    for st, val in zip(serial_types, values):
        # TEXT scoring
        if st >= 13 and st % 2 == 1:  # TEXT
            if not isinstance(val, str):
                return -1000
            if not is_valid_utf8(val):
                return -1000
            if is_printable(val):
                score += 50
            if looks_like_identifier(val):
                score += 30
        
        # Integer scoring
        elif st in (1, 2, 3, 4, 5, 6):
            if not isinstance(val, int):
                return -1000
            if 0 <= val <= 1000000:
                score += 20
            elif -2**31 <= val <= 2**31:
                score += 10
        
        # FLOAT scoring
        elif st == 7:
            if not isinstance(val, float):
                return -1000
            if -1e10 <= val <= 1e10:
                score += 15
        
        # Zero/One scoring
        elif st in (8, 9):
            score += 5
    
    # Prefer reasonable column counts
    if 2 <= len(serial_types) <= 10:
        score += 20
    score -= len(serial_types) * 2
    
    return score


def generate_repairs(data, offset, payload_len):
    """
    Generate single-bit-flip repairs that balance payload-length equation.
    Returns list of (serial_types, values, score), sorted by score.
    """
    header_size, header_size_len = decode_varint(data, offset)
    if header_size < 1 or header_size > payload_len:
        return []
    
    header_bytes = data[offset:offset+header_size]
    candidates = []
    
    # Try flipping each bit in serial type bytes
    for i in range(header_size_len, header_size):
        for bit in range(8):
            repaired = bytearray(header_bytes)
            repaired[i] ^= (1 << bit)
            
            # Parse serial types
            serial_types = []
            pos = header_size_len
            valid = True
            
            while pos < header_size:
                try:
                    st, st_len = decode_varint(bytes(repaired), pos)
                    if st_len == 0:
                        valid = False
                        break
                    serial_types.append(st)
                    pos += st_len
                except:
                    valid = False
                    break
            
            if not valid:
                continue
            
            # Check payload-length equation
            total = header_size
            for st in serial_types:
                size = serial_type_size(st)
                if size is None:
                    valid = False
                    break
                total += size
            
            if not valid or total != payload_len:
                continue
            
            # Parse values and score
            try:
                pos = offset + header_size
                values = []
                for st in serial_types:
                    val, size = parse_value(data, pos, st)
                    values.append(val)
                    pos += size
                
                score = score_repair(serial_types, values)
                if score > -500:
                    candidates.append((serial_types, values, score))
            except:
                continue
    
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates


def parse_payload(data, offset, payload_len, encoding='utf-8', try_repair=True):
    """
    Parse payload with validation and ranked repair.
    Returns (values, was_repaired) or (None, False).
    """
    if offset + payload_len > len(data):
        return None, False
    
    header_size, header_size_len = decode_varint(data, offset)
    if header_size < 1 or header_size > payload_len:
        if not try_repair:
            return None, False
        repairs = generate_repairs(data, offset, payload_len)
        if repairs:
            return repairs[0][1], True
        return None, False
    
    # Parse serial types
    serial_types = []
    pos = offset + header_size_len
    header_end = offset + header_size
    
    while pos < header_end and pos < len(data):
        st, st_len = decode_varint(data, pos)
        serial_types.append(st)
        pos += st_len
    
    # Validate payload-length equation
    total_size = header_size
    for st in serial_types:
        size = serial_type_size(st)
        if size is None:
            if not try_repair:
                return None, False
            repairs = generate_repairs(data, offset, payload_len)
            if repairs:
                return repairs[0][1], True
            return None, False
        total_size += size
    
    if total_size != payload_len:
        if not try_repair:
            return None, False
        repairs = generate_repairs(data, offset, payload_len)
        if repairs:
            return repairs[0][1], True
        return None, False
    
    # Parse values
    pos = offset + header_size
    values = []
    for st in serial_types:
        val, size = parse_value(data, pos, st, encoding)
        values.append(val)
        pos += size
    
    return values, False


def parse_page_size(data):
    """Parse page size with validation."""
    try:
        page_size = struct.unpack('>H', data[16:18])[0]
        if page_size == 1:
            page_size = 65536
        if page_size in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
            return page_size
    except:
        pass
    
    file_size = len(data)
    for size in [4096, 1024, 2048, 512]:
        if file_size % size == 0:
            return size
    return 4096


def parse_page(data, page_num, page_size, encoding='utf-8'):
    """Parse a single page and extract cells."""
    page_offset = page_num * page_size
    if page_offset >= len(data):
        return []
    
    btree_offset = page_offset + (100 if page_num == 0 else 0)
    if btree_offset >= len(data):
        return []
    
    if data[btree_offset] != 0x0d:
        return []
    
    try:
        cell_count = struct.unpack('>H', data[btree_offset+3:btree_offset+5])[0]
        max_cells = (page_size - 8) // 2
        cell_count = min(cell_count, max_cells)
    except:
        return []
    
    records = []
    for i in range(cell_count):
        try:
            ptr_offset = btree_offset + 8 + 2 * i
            if ptr_offset + 2 > len(data):
                break
            
            cell_ptr = struct.unpack('>H', data[ptr_offset:ptr_offset+2])[0]
            cell_offset = page_offset + cell_ptr
            
            if cell_offset >= len(data):
                continue
            
            payload_len, plen_size = decode_varint(data, cell_offset)
            if payload_len < 1 or payload_len > 10000:
                continue
            
            rowid, rid_size = decode_varint(data, cell_offset + plen_size)
            if rowid < 0 or rowid > 10**12:
                continue
            
            payload_offset = cell_offset + plen_size + rid_size
            values, was_repaired = parse_payload(data, payload_offset, payload_len, encoding)
            
            if values:
                records.append({
                    'cell_offset': cell_offset,
                    'page_num': page_num,
                    'rowid': rowid,
                    'values': values,
                    'num_columns': len(values),
                    'was_repaired': was_repaired
                })
        except:
            continue
    
    return records


def carve_records(data, page_size, encoding='utf-8'):
    """
    Carve records from raw bytes when page structures are damaged.
    NOTE: Carving does NOT use repair - too risky without cell pointer.
    """
    records = []
    
    for offset in range(len(data) - 20):
        try:
            payload_len, plen_size = decode_varint(data, offset)
            if payload_len < 2 or payload_len > min(1000, page_size):
                continue
            
            rowid_offset = offset + plen_size
            if rowid_offset >= len(data):
                continue
            
            rowid, rid_size = decode_varint(data, rowid_offset)
            if rowid < 0 or rowid > 10**9:
                continue
            
            payload_offset = rowid_offset + rid_size
            if payload_offset + payload_len > len(data):
                continue
            
            # STRICT validation for carved - no repair
            values, was_repaired = parse_payload(data, payload_offset, payload_len, encoding, try_repair=False)
            
            if values and len(values) >= 1:
                records.append({
                    'cell_offset': offset,
                    'page_num': None,
                    'rowid': rowid,
                    'values': values,
                    'num_columns': len(values),
                    'was_repaired': was_repaired
                })
        except:
            continue
    
    return records


def infer_column_type(value):
    """Infer SQL type from Python value."""
    if value is None: return 'NULL'
    elif isinstance(value, str): return 'TEXT'
    elif isinstance(value, float): return 'REAL'
    elif isinstance(value, int): return 'INTEGER'
    return 'UNKNOWN'


def get_signature(record):
    """Get structural signature of a record."""
    values = record.get('values', [])
    return (len(values), tuple(infer_column_type(v) for v in values))


def classify_records(records):
    """Classify records by structural signature."""
    groups = {}
    for record in records:
        sig = get_signature(record)
        if sig not in groups:
            groups[sig] = []
        groups[sig].append(record)
    return groups


def recover_sqlite_data(db_path, output_path=None, column_map=None, encoding=None):
    """
    Recover data from corrupted SQLite database.
    
    Args:
        db_path: Path to SQLite file
        output_path: Optional output JSON path
        column_map: Dict mapping column index to output key
        encoding: Text encoding (auto-detected if None)
    
    Returns:
        List of recovered records (dicts if column_map, else value lists)
    """
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Parse header
    page_size = parse_page_size(data)
    try:
        num_pages_header = struct.unpack('>I', data[28:32])[0]
    except:
        num_pages_header = 0
    num_pages = max(num_pages_header, len(data) // page_size)
    
    # Detect encoding
    if encoding is None:
        try:
            encoding_code = struct.unpack('>I', data[56:60])[0]
            if encoding_code == 1:
                encoding = 'utf-8'
            elif encoding_code == 2:
                encoding = 'utf-16-le'
            elif encoding_code == 3:
                encoding = 'utf-16-be'
            else:
                encoding = 'utf-8'
        except:
            encoding = 'utf-8'
    
    # Phase 1: Structured parsing
    structured_records = []
    for page_num in range(num_pages):
        records = parse_page(data, page_num, page_size, encoding)
        structured_records.extend(records)
    
    # Phase 2: Carving (no repair)
    carved_records = carve_records(data, page_size, encoding)
    
    # Phase 3: Merge and dedup
    seen_offsets = set()
    all_records = []
    for record in structured_records + carved_records:
        offset = record.get('cell_offset')
        if offset not in seen_offsets:
            seen_offsets.add(offset)
            all_records.append(record)
    
    # Phase 4: Filter - keep user tables
    # Exclude sqlite_master (5 cols, TEXT/TEXT/TEXT/INTEGER/TEXT pattern)
    user_records = []
    for record in all_records:
        sig = get_signature(record)
        col_count = sig[0]
        
        # Keep 2-10 columns
        if 2 <= col_count <= 10:
            # Skip sqlite_master pattern
            is_sqlite_master = (
                col_count == 5 and 
                len(sig[1]) >= 3 and 
                sig[1][0:3] == ('TEXT', 'TEXT', 'TEXT')
            )
            if not is_sqlite_master:
                user_records.append(record)
    
    if user_records:
        records = user_records
    else:
        records = all_records
    
    # Phase 5: Apply column mapping
    results = []
    for record in records:
        values = record.get('values', [])
        if column_map:
            mapped = {}
            for idx, key in column_map.items():
                if idx < len(values):
                    val = values[idx]
                    if isinstance(val, str):
                        val = val.strip()
                    mapped[key] = val
            results.append(mapped)
        else:
            results.append(values)
    
    # Save if output path provided
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(results, f)
    
    return results


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_file> <output_json> [column_map_json]")
        example_map = '{"0":"word","1":"value"}'
        print(f'Example: {sys.argv[0]} trunc.db out.json {example_map}')
        sys.exit(1)
    
    column_map = None
    if len(sys.argv) >= 4:
        column_map = {int(k): v for k, v in json.loads(sys.argv[3]).items()}
    
    results = recover_sqlite_data(sys.argv[1], sys.argv[2], column_map)
    print(f"Recovered {len(results)} records")
