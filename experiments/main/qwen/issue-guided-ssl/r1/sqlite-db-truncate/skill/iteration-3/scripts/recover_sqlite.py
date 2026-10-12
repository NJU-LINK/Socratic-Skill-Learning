#!/usr/bin/env python3
"""
General-purpose SQLite corruption recovery tool.

Recovers rows from damaged SQLite databases by parsing raw page structures,
cell pointer arrays, varints, serial types, and record payloads at the byte
level. Handles: truncation, zeroed regions, random bit flips, damaged page
headers, and fragmented records.

Usage:
    python3 recover_sqlite.py <db_file> <output_json> [--schema COL1:TYPE,COL2:TYPE,...]

If --schema is not provided, the tool attempts to extract it from sqlite_master
or infer it from record patterns.
"""

import struct
import json
import sys
import os
import re
from typing import List, Dict, Optional, Tuple, Any

# ─── SQLite Constants ───────────────────────────────────────────────

SQLITE_HEADER_MAGIC = b'SQLite format 3\x00'
PAGE_TYPE_INDEX_INTERIOR = 0x02
PAGE_TYPE_TABLE_LEAF = 0x0D
PAGE_TYPE_TABLE_INTERIOR = 0x05
PAGE_TYPE_INDEX_LEAF = 0x0A

# ─── Varint Encoding ────────────────────────────────────────────────

def read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    """Read a SQLite varint (up to 9 bytes). Returns (value, new_offset)."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, offset + i
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if not (byte & 0x80):
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset


def encode_varint(value: int) -> bytes:
    """Encode an integer as a SQLite varint."""
    if value < 0:
        # SQLite stores negative values as unsigned 64-bit
        value = value & 0xFFFFFFFFFFFFFFFF
    result = []
    if value <= 0x7F:
        return bytes([value])
    # Work out how many 7-bit groups we need
    temp = value
    groups = []
    while temp > 0:
        groups.append(temp & 0x7F)
        temp >>= 7
    groups.reverse()
    result = []
    for i, g in enumerate(groups):
        if i < len(groups) - 1:
            result.append(g | 0x80)
        else:
            result.append(g)
    return bytes(result)


# ─── Serial Type Handling ────────────────────────────────────────────

def serial_type_size(stype: int) -> int:
    """Return the byte size of data for a given serial type.
    Returns -1 for reserved/invalid types."""
    if stype == 0: return 0    # NULL
    if stype == 1: return 1    # 8-bit signed integer
    if stype == 2: return 2    # 16-bit big-endian signed integer
    if stype == 3: return 3    # 24-bit big-endian signed integer
    if stype == 4: return 4    # 32-bit big-endian signed integer
    if stype == 5: return 6    # 48-bit big-endian signed integer
    if stype == 6: return 8    # 64-bit big-endian signed integer
    if stype == 7: return 8    # IEEE 754 64-bit float
    if stype == 8: return 0    # Integer constant 0
    if stype == 9: return 0    # Integer constant 1
    if stype in (10, 11): return -1  # Reserved
    if stype >= 12 and stype % 2 == 0:
        return (stype - 12) // 2   # Blob
    if stype >= 13 and stype % 2 == 1:
        return (stype - 13) // 2   # Text
    return -1


def decode_value(data: bytes, offset: int, stype: int) -> Any:
    """Decode a value from raw bytes given a serial type."""
    if stype == 0:
        return None
    if stype == 1:
        val = struct.unpack('>b', data[offset:offset+1])[0]
        return val
    if stype == 2:
        return struct.unpack('>h', data[offset:offset+2])[0]
    if stype == 3:
        b = data[offset:offset+3]
        val = (b[0] << 16) | (b[1] << 8) | b[2]
        if val & 0x800000:
            val -= 0x1000000
        return val
    if stype == 4:
        return struct.unpack('>i', data[offset:offset+4])[0]
    if stype == 5:
        b = data[offset:offset+6]
        val = int.from_bytes(b, 'big', signed=True)
        return val
    if stype == 6:
        return struct.unpack('>q', data[offset:offset+8])[0]
    if stype == 7:
        return struct.unpack('>d', data[offset:offset+8])[0]
    if stype == 8:
        return 0
    if stype == 9:
        return 1
    if stype >= 12 and stype % 2 == 0:
        length = (stype - 12) // 2
        return data[offset:offset+length]
    if stype >= 13 and stype % 2 == 1:
        length = (stype - 13) // 2
        raw = data[offset:offset+length]
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('latin-1')
    return None


def is_valid_serial_type(stype: int) -> bool:
    """Check if a serial type is valid (not reserved)."""
    return serial_type_size(stype) >= 0


def try_fix_serial_type(stype: int, remaining_data: int,
                        cols_remaining: int, context: dict = None) -> int:
    """Attempt to fix a corrupted serial type by single-bit flips.
    
    Strategy: try each single-bit flip and check if the resulting type
    has a data size that fits in the remaining payload space.
    Prefer types that produce valid text (UTF-8) if context suggests text column.
    """
    sz = serial_type_size(stype)
    if sz >= 0 and sz <= remaining_data:
        return stype  # Already valid
    
    candidates = []
    for bit in range(8):
        fixed = stype ^ (1 << bit)
        fsz = serial_type_size(fixed)
        if fsz < 0 or fsz > remaining_data:
            continue
        
        # Score the candidate
        score = 0
        
        # Prefer text types if context suggests it
        if context and context.get('expected_text'):
            if fixed >= 13 and fixed % 2 == 1:
                text_len = (fixed - 13) // 2
                if 1 <= text_len <= 500:
                    score += 10
        
        # Prefer integer types for numeric columns
        if context and context.get('expected_numeric'):
            if 1 <= fixed <= 6:
                score += 10
        
        # Prefer types where data size leaves room for remaining columns
        min_remaining = 0  # Each remaining column needs at least 0 bytes (NULL)
        if fsz <= remaining_data - min_remaining:
            score += 1
        
        candidates.append((score, fixed))
    
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    
    return stype  # Return original if no fix found


# ─── Record Parsing ──────────────────────────────────────────────────

def fix_serial_types_recursive(serial_types: List[int], data_available: int) -> Optional[List[int]]:
    """Fix corrupted serial types using recursive backtracking.
    
    Tries all combinations of original values and single-bit flips across
    all columns simultaneously, backtracking when a partial assignment
    can't lead to a valid solution.
    
    Returns the fixed serial types list, or None if no valid assignment found.
    """
    num_cols = len(serial_types)
    
    def backtrack(idx: int, remaining: int, current: List[int]) -> bool:
        if idx == num_cols:
            return remaining == 0
        
        st = serial_types[idx]
        is_last = (idx == num_cols - 1)
        
        # Build candidate list: original first, then single-bit flips
        candidates = [st]
        for bit in range(8):
            candidates.append(st ^ (1 << bit))
        
        for c in candidates:
            sz = serial_type_size(c)
            if sz < 0 or sz > remaining:
                continue
            if is_last:
                if sz == remaining:
                    current[idx] = c
                    return True
            else:
                current[idx] = c
                if backtrack(idx + 1, remaining - sz, current):
                    return True
        
        current[idx] = st  # Reset on failure
        return False
    
    fixed = list(serial_types)
    if backtrack(0, data_available, fixed):
        return fixed
    return None


def parse_record(data: bytes, offset: int, payload_len: int,
                 column_hints: List[dict] = None) -> Optional[List[Tuple[int, Any]]]:
    """Parse a SQLite record payload into (serial_type, value) pairs.
    
    Args:
        data: Full database file bytes
        offset: Start of record payload
        payload_len: Total payload length (header + data)
        column_hints: Optional list of dicts with 'expected_text' or 'expected_numeric'
    
    Returns:
        List of (serial_type, value) tuples, or None if parsing fails.
    """
    if payload_len < 2:
        return None
    
    rec_start = offset
    rec_end = offset + payload_len
    
    # Read header size
    header_size, pos = read_varint(data, offset)
    if header_size < 2 or header_size > payload_len:
        return None
    
    # Read serial types from header
    serial_types = []
    while pos < rec_start + header_size:
        if pos >= len(data):
            return None
        st, pos = read_varint(data, pos)
        serial_types.append(st)
    
    if pos != rec_start + header_size:
        return None
    
    num_cols = len(serial_types)
    data_start = rec_start + header_size
    data_available = payload_len - header_size
    
    # Calculate total data size needed
    total_needed = sum(serial_type_size(st) for st in serial_types)
    
    # If sizes don't match, use recursive backtracking to fix corrupted types
    if total_needed != data_available:
        fixed = fix_serial_types_recursive(serial_types, data_available)
        if fixed is None:
            return None
        serial_types = fixed
    
    # Decode values
    values = []
    pos = data_start
    for st in serial_types:
        sz = serial_type_size(st)
        if pos + sz > len(data):
            return None
        val = decode_value(data, pos, st)
        values.append((st, val))
        pos += sz
    
    return values


# ─── Page Parsing ────────────────────────────────────────────────────

def parse_file_header(data: bytes) -> dict:
    """Parse the 100-byte SQLite file header."""
    if len(data) < 100:
        raise ValueError("File too small for SQLite header")
    
    magic = data[0:16]
    if magic != SQLITE_HEADER_MAGIC:
        raise ValueError(f"Not a SQLite database (magic: {magic!r})")
    
    page_size_raw = struct.unpack('>H', data[16:18])[0]
    page_size = 65536 if page_size_raw == 1 else page_size_raw
    
    total_pages = struct.unpack('>I', data[28:32])[0]
    
    return {
        'page_size': page_size,
        'total_pages': total_pages,
        'file_size': len(data),
    }


def parse_page_header(data: bytes, page_offset: int, page_num: int) -> dict:
    """Parse a B-tree page header.
    
    For page 1, the header starts at offset 100 (after the file header).
    For other pages, it starts at offset 0 within the page.
    """
    if page_num == 1:
        hdr_start = page_offset + 100
    else:
        hdr_start = page_offset
    
    page_type = data[hdr_start]
    
    result = {
        'page_type': page_type,
        'page_num': page_num,
        'header_offset': hdr_start,
    }
    
    if page_type == PAGE_TYPE_TABLE_LEAF:
        # Table leaf: 8-byte header
        first_freeblock = struct.unpack('>H', data[hdr_start+1:hdr_start+3])[0]
        num_cells = struct.unpack('>H', data[hdr_start+3:hdr_start+5])[0]
        cell_content_start = struct.unpack('>H', data[hdr_start+5:hdr_start+7])[0]
        fragmented_bytes = data[hdr_start+7]
        
        result.update({
            'type_name': 'table_leaf',
            'first_freeblock': first_freeblock,
            'num_cells': num_cells,
            'cell_content_start': cell_content_start,
            'fragmented_bytes': fragmented_bytes,
            'header_size': 8,
        })
    
    elif page_type == PAGE_TYPE_TABLE_INTERIOR:
        # Table interior: 12-byte header
        first_freeblock = struct.unpack('>H', data[hdr_start+1:hdr_start+3])[0]
        num_cells = struct.unpack('>H', data[hdr_start+3:hdr_start+5])[0]
        cell_content_start = struct.unpack('>H', data[hdr_start+5:hdr_start+7])[0]
        fragmented_bytes = data[hdr_start+7]
        rightmost_pointer = struct.unpack('>I', data[hdr_start+8:hdr_start+12])[0]
        
        result.update({
            'type_name': 'table_interior',
            'first_freeblock': first_freeblock,
            'num_cells': num_cells,
            'cell_content_start': cell_content_start,
            'fragmented_bytes': fragmented_bytes,
            'rightmost_pointer': rightmost_pointer,
            'header_size': 12,
        })
    
    elif page_type == PAGE_TYPE_INDEX_LEAF:
        first_freeblock = struct.unpack('>H', data[hdr_start+1:hdr_start+3])[0]
        num_cells = struct.unpack('>H', data[hdr_start+3:hdr_start+5])[0]
        cell_content_start = struct.unpack('>H', data[hdr_start+5:hdr_start+7])[0]
        fragmented_bytes = data[hdr_start+7]
        
        result.update({
            'type_name': 'index_leaf',
            'num_cells': num_cells,
            'cell_content_start': cell_content_start,
            'header_size': 8,
        })
    
    elif page_type == PAGE_TYPE_INDEX_INTERIOR:
        first_freeblock = struct.unpack('>H', data[hdr_start+1:hdr_start+3])[0]
        num_cells = struct.unpack('>H', data[hdr_start+3:hdr_start+5])[0]
        cell_content_start = struct.unpack('>H', data[hdr_start+5:hdr_start+7])[0]
        fragmented_bytes = data[hdr_start+7]
        
        result.update({
            'type_name': 'index_interior',
            'num_cells': num_cells,
            'cell_content_start': cell_content_start,
            'header_size': 8,
        })
    
    else:
        result['type_name'] = f'unknown(0x{page_type:02x})'
        result['header_size'] = 0
        result['num_cells'] = 0
    
    return result


def read_cell_pointers(data: bytes, page_offset: int, page_hdr: dict) -> List[int]:
    """Read the cell pointer array from a page."""
    ptr_start = page_hdr['header_offset'] + page_hdr['header_size']
    pointers = []
    for i in range(page_hdr['num_cells']):
        off = ptr_start + 2 * i
        if off + 2 > len(data):
            break
        ptr = struct.unpack('>H', data[off:off+2])[0]
        pointers.append(ptr)
    return pointers


# ─── Schema Extraction ──────────────────────────────────────────────

def extract_schema_from_master(data: bytes, page_size: int) -> Optional[Dict[str, dict]]:
    """Try to extract table schemas from sqlite_master (page 1)."""
    if page_size < 100 + 8:
        return None
    
    page_offset = 0
    hdr = parse_page_header(data, page_offset, 1)
    
    if hdr.get('type_name') != 'table_leaf':
        return None
    
    pointers = read_cell_pointers(data, page_offset, hdr)
    schemas = {}
    
    for ptr in pointers:
        abs_offset = page_offset + ptr
        
        # Check for all-zero cell
        if all(b == 0 for b in data[abs_offset:abs_offset+4]):
            continue
        
        payload_len, pos = read_varint(data, abs_offset)
        rowid, pos = read_varint(data, pos)
        
        if pos + payload_len > len(data):
            continue
        
        record = parse_record(data, pos, payload_len)
        if record is None or len(record) < 5:
            continue
        
        values = [v for _, v in record]
        obj_type = values[0]
        name = values[1]
        tbl_name = values[2]
        rootpage = values[3]
        sql = values[4]
        
        if obj_type == 'table' and isinstance(sql, str):
            schemas[tbl_name] = {
                'sql': sql,
                'rootpage': rootpage,
                'columns': parse_create_table_sql(sql),
            }
    
    return schemas if schemas else None


def parse_create_table_sql(sql: str) -> List[dict]:
    """Parse column definitions from a CREATE TABLE statement."""
    # Extract the part between parentheses
    match = re.search(r'\((.*)\)', sql, re.DOTALL)
    if not match:
        return []
    
    cols_str = match.group(1)
    columns = []
    
    for col_def in cols_str.split(','):
        col_def = col_def.strip()
        if not col_def:
            continue
        parts = col_def.split()
        if len(parts) >= 2:
            col_name = parts[0]
            col_type = parts[1].upper()
            columns.append({'name': col_name, 'type': col_type})
        elif len(parts) == 1:
            columns.append({'name': parts[0], 'type': 'TEXT'})
    
    return columns


def infer_schema_from_records(records: List[List[Tuple[int, Any]]]) -> List[dict]:
    """Infer column schema from a collection of parsed records."""
    if not records:
        return []
    
    num_cols = len(records[0])
    columns = []
    
    for col_idx in range(num_cols):
        types_seen = set()
        for rec in records:
            if col_idx < len(rec):
                stype, val = rec[col_idx]
                types_seen.add(stype)
        
        # Determine likely column type
        has_text = any(t >= 13 and t % 2 == 1 for t in types_seen)
        has_float = any(t == 7 for t in types_seen)
        has_int = any(1 <= t <= 6 for t in types_seen)
        
        if has_text:
            columns.append({'name': f'col{col_idx}', 'type': 'TEXT'})
        elif has_float:
            columns.append({'name': f'col{col_idx}', 'type': 'REAL'})
        elif has_int:
            columns.append({'name': f'col{col_idx}', 'type': 'INTEGER'})
        else:
            columns.append({'name': f'col{col_idx}', 'type': 'BLOB'})
    
    return columns


# ─── Cell Parsing ────────────────────────────────────────────────────

def parse_table_leaf_cell(data: bytes, page_offset: int, cell_ptr: int,
                          page_size: int) -> Optional[dict]:
    """Parse a single table leaf cell.
    
    Returns dict with 'rowid', 'payload_len', 'record', 'overflow_page' or None.
    """
    abs_offset = page_offset + cell_ptr
    
    # Check for all-zero region
    preview_len = min(8, len(data) - abs_offset)
    if preview_len < 2 or all(b == 0 for b in data[abs_offset:abs_offset+preview_len]):
        return None
    
    payload_len, pos = read_varint(data, abs_offset)
    rowid, pos = read_varint(data, pos)
    
    # Sanity checks
    if payload_len <= 0 or payload_len > page_size * 4:
        return None
    if rowid < 0:
        return None
    
    page_end = page_offset + page_size
    
    # Calculate usable space on this page for payload
    usable_space = page_end - pos
    
    # Check for overflow (payload too large for single page)
    # SQLite formula: U = page_size - reserved - (page_num==1 ? 100 : 0)
    # X = U - 35 for table leaf
    # If payload_len > X, overflow occurs
    # For simplicity, check if payload extends beyond page
    if pos + payload_len <= page_end:
        # All payload on this page
        return {
            'rowid': rowid,
            'payload_len': payload_len,
            'payload_offset': pos,
            'overflow_page': None,
            'local_payload_len': payload_len,
        }
    else:
        # Overflow: local payload is truncated, rest on overflow pages
        local_len = usable_space
        # The last 4 bytes of local payload area contain the first overflow page number
        if local_len >= 4:
            overflow_ptr_offset = pos + local_len - 4
            # Actually, for table leaf cells, the overflow pointer is at the end
            # of the local payload, and local payload includes it
            overflow_page = struct.unpack('>I', data[pos + local_len - 4:pos + local_len])[0] if overflow_ptr_offset + 4 <= len(data) else None
            return {
                'rowid': rowid,
                'payload_len': payload_len,
                'payload_offset': pos,
                'overflow_page': overflow_page,
                'local_payload_len': local_len - 4,  # exclude overflow pointer
            }
        return None


def parse_table_interior_cell(data: bytes, page_offset: int, cell_ptr: int) -> Optional[dict]:
    """Parse a table interior cell (left child pointer + key)."""
    abs_offset = page_offset + cell_ptr
    
    if abs_offset + 4 >= len(data):
        return None
    
    left_child = struct.unpack('>I', data[abs_offset:abs_offset+4])[0]
    key, _ = read_varint(data, abs_offset + 4)
    
    return {
        'left_child': left_child,
        'key': key,
    }


# ─── Overflow Page Handling ─────────────────────────────────────────

def read_overflow_payload(data: bytes, first_overflow_page: int,
                          page_size: int, total_payload_len: int,
                          local_payload: bytes) -> Optional[bytes]:
    """Read a payload that spans overflow pages."""
    if first_overflow_page is None or first_overflow_page == 0:
        return local_payload
    
    result = bytearray(local_payload)
    current_page = first_overflow_page
    remaining = total_payload_len - len(local_payload)
    
    while remaining > 0 and current_page > 0:
        page_offset = (current_page - 1) * page_size
        if page_offset + page_size > len(data):
            break
        
        # First 4 bytes of overflow page: next overflow page number
        next_page = struct.unpack('>I', data[page_offset:page_offset+4])[0]
        
        # Remaining bytes are payload data
        chunk_size = min(page_size - 4, remaining)
        chunk = data[page_offset+4:page_offset+4+chunk_size]
        result.extend(chunk)
        remaining -= len(chunk)
        current_page = next_page
    
    return bytes(result) if remaining == 0 else None


# ─── Raw Scan Recovery ──────────────────────────────────────────────

def scan_for_records(data: bytes, page_size: int, min_text_len: int = 3) -> List[dict]:
    """Scan raw bytes for record-like patterns when page structure is damaged.
    
    Looks for sequences that match: small header varint + plausible serial types
    + valid text data.
    """
    found = []
    
    # Scan for text patterns like "testword" or other recognizable strings
    i = 0
    while i < len(data) - 10:
        # Look for potential record headers
        # A record header starts with header_size (small varint, 2-20)
        # followed by serial types
        
        byte = data[i]
        if byte < 2 or byte > 30:
            i += 1
            continue
        
        header_size = byte
        # Check if we have enough bytes for the header
        if i + header_size >= len(data):
            i += 1
            continue
        
        # Try to parse serial types
        pos = i + 1
        serial_types = []
        valid = True
        while pos < i + header_size:
            st, new_pos = read_varint(data, pos)
            if not is_valid_serial_type(st):
                valid = False
                break
            serial_types.append(st)
            pos = new_pos
        
        if not valid or not serial_types:
            i += 1
            continue
        
        # Check if data sizes make sense
        data_start = i + header_size
        total_data = sum(serial_type_size(st) for st in serial_types)
        
        if data_start + total_data > len(data):
            i += 1
            continue
        
        # Check if text columns decode as valid UTF-8
        has_text = False
        pos = data_start
        values = []
        all_valid = True
        for st in serial_types:
            sz = serial_type_size(st)
            if st >= 13 and st % 2 == 1:
                text_len = (st - 13) // 2
                if text_len < min_text_len:
                    all_valid = False
                    break
                try:
                    text = data[pos:pos+sz].decode('utf-8')
                    if not text.isprintable():
                        all_valid = False
                        break
                    has_text = True
                    values.append(text)
                except UnicodeDecodeError:
                    all_valid = False
                    break
            else:
                val = decode_value(data, pos, st)
                values.append(val)
            pos += sz
        
        if all_valid and has_text:
            found.append({
                'offset': i,
                'serial_types': serial_types,
                'values': values,
                'total_size': header_size + total_data,
            })
            i += header_size + total_data  # Skip past this record
        else:
            i += 1
    
    return found


# ─── Fragment Reassembly ────────────────────────────────────────────

def try_reassemble_fragments(data: bytes, page_size: int, 
                              known_records: List[dict]) -> List[dict]:
    """Try to reassemble split fragments from zeroed/corrupted regions.
    
    This handles cases where a record was split across a corrupted boundary.
    """
    # For now, this is a placeholder for more sophisticated fragment recovery
    # In practice, fragments can be detected by:
    # 1. Finding partial record headers at page boundaries
    # 2. Matching partial text strings with known patterns
    # 3. Using cell pointer gaps to identify missing content
    return []


# ─── Main Recovery Engine ───────────────────────────────────────────

def try_identify_corrupted_leaf_page(data: bytes, page_offset: int, page_size: int, page_num: int) -> Optional[dict]:
    """Try to identify a page as a table leaf even if the header is corrupted.
    
    Uses structural heuristics:
    1. Check if there's a valid cell pointer array (pointers within page bounds)
    2. Check if cells pointed to contain valid record data
    3. Assume 8-byte header (standard for table leaf)
    
    Returns a synthetic page header dict if identified, None otherwise.
    """
    # Skip page 1 (has 100-byte file header, different structure)
    if page_num == 1:
        return None
    
    # Assume 8-byte header for table leaf
    header_size = 8
    ptr_start = page_offset + header_size
    
    # Try different cell counts (1 to 100) and find the best match
    best_result = None
    best_valid_cells = 0
    
    for num_cells in range(1, 101):
        ptr_end = ptr_start + 2 * num_cells
        if ptr_end > page_offset + page_size:
            break
        
        # Read cell pointers
        pointers = []
        valid_pointers = True
        # Cell pointers are page-relative; valid range is from after pointer array to page end
        min_ptr = header_size + 2 * num_cells
        max_ptr = page_size - 1
        for i in range(num_cells):
            off = ptr_start + 2 * i
            ptr = struct.unpack('>H', data[off:off+2])[0]
            # Check if pointer is within page bounds (page-relative)
            if ptr < min_ptr or ptr > max_ptr:
                valid_pointers = False
                break
            pointers.append(ptr)
        
        if not valid_pointers:
            continue
        
        # Check how many cells contain valid record data
        valid_cells = 0
        for ptr in pointers:
            abs_offset = page_offset + ptr
            # Try to parse as a cell
            cell = parse_table_leaf_cell(data, page_offset, ptr, page_size)
            if cell is not None:
                # Try to parse the record
                record = parse_record(data, cell['payload_offset'], cell['payload_len'])
                if record is not None and len(record) >= 1:
                    valid_cells += 1
        
        # Keep the result with the most valid cells
        if valid_cells > best_valid_cells:
            best_valid_cells = valid_cells
            cell_content_start = min(pointers) if pointers else 0
            best_result = {
                'page_type': PAGE_TYPE_TABLE_LEAF,
                'page_num': page_num,
                'header_offset': page_offset,
                'type_name': 'table_leaf',
                'first_freeblock': 0,
                'num_cells': num_cells,
                'cell_content_start': cell_content_start,
                'fragmented_bytes': 0,
                'header_size': 8,
                '_heuristic': True,  # Mark as heuristic identification
            }
    
    # Only return if we found at least one valid cell
    if best_result and best_valid_cells > 0:
        return best_result
    
    return None


def recover_database(db_path: str, output_path: str, 
                     schema_hint: str = None) -> List[dict]:
    """Main recovery function.
    
    Args:
        db_path: Path to the corrupted SQLite database file
        output_path: Path to write the recovered JSON
        schema_hint: Optional "col1:type1,col2:type2,..." schema string
    
    Returns:
        List of recovered records as dicts
    """
    data = open(db_path, 'rb').read()
    
    # Parse file header
    try:
        file_hdr = parse_file_header(data)
    except ValueError as e:
        print(f"Warning: {e}. Attempting raw scan recovery.", file=sys.stderr)
        file_hdr = None
    
    if file_hdr is None:
        # File header is corrupted; try raw scan
        print("File header corrupted. Using raw byte scanning.", file=sys.stderr)
        fragments = scan_for_records(data, 4096)  # Assume common page size
        records = []
        for frag in fragments:
            if len(frag['values']) >= 2:
                records.append({
                    'col0': frag['values'][0],
                    'col1': frag['values'][1] if len(frag['values']) > 1 else None,
                })
        write_json_output(records, output_path)
        return records
    
    page_size = file_hdr['page_size']
    total_pages = file_hdr['total_pages']
    
    print(f"Database: {page_size} bytes/page, {total_pages} pages", file=sys.stderr)
    
    # Try to extract schema from sqlite_master
    schemas = extract_schema_from_master(data, page_size)
    column_names = None
    column_hints = None
    
    if schemas:
        # Use the first table's schema (most common case)
        # For multi-table databases, we'd need to track schemas per table
        for tbl_name, tbl_info in schemas.items():
            print(f"Found table '{tbl_name}': {tbl_info['sql']}", file=sys.stderr)
            cols = tbl_info.get('columns', [])
            if cols:
                column_names = [c['name'] for c in cols]
                column_hints = []
                for c in cols:
                    t = c['type'].upper()
                    if t in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB'):
                        column_hints.append({'expected_text': True})
                    elif t in ('REAL', 'FLOAT', 'DOUBLE', 'NUMERIC'):
                        column_hints.append({'expected_numeric': True, 'expected_float': True})
                    elif t in ('INTEGER', 'INT', 'BIGINT', 'SMALLINT'):
                        column_hints.append({'expected_numeric': True})
                    else:
                        column_hints.append({})
            break  # Use first table only for now
    
    # Parse schema hint if provided
    if schema_hint:
        column_names = []
        column_hints = []
        for col_spec in schema_hint.split(','):
            parts = col_spec.strip().split(':')
            name = parts[0]
            ctype = parts[1].upper() if len(parts) > 1 else 'TEXT'
            column_names.append(name)
            if ctype in ('TEXT', 'VARCHAR'):
                column_hints.append({'expected_text': True})
            elif ctype in ('REAL', 'FLOAT'):
                column_hints.append({'expected_numeric': True, 'expected_float': True})
            else:
                column_hints.append({'expected_numeric': True})
    
    # Collect all records from table leaf pages
    all_records = []
    raw_parsed_records = []
    pages_processed = 0
    pages_with_data = 0
    
    for page_num in range(1, total_pages + 1):
        page_offset = (page_num - 1) * page_size
        page_data = data[page_offset:page_offset + page_size]
        
        if len(page_data) < 8:
            continue
        
        pages_processed += 1
        hdr = parse_page_header(data, page_offset, page_num)
        
        # If page type is unknown, try heuristic identification
        if hdr.get('type_name', '').startswith('unknown'):
            heuristic_hdr = try_identify_corrupted_leaf_page(data, page_offset, page_size, page_num)
            if heuristic_hdr:
                print(f"Page {page_num}: identified as table leaf via heuristic (corrupted header)", 
                      file=sys.stderr)
                hdr = heuristic_hdr
        
        if hdr.get('type_name') == 'table_leaf':
            # Skip page 1 (sqlite_master) for user data
            if page_num == 1:
                continue
            
            pointers = read_cell_pointers(data, page_offset, hdr)
            is_heuristic = hdr.get('_heuristic', False)
            print(f"Page {page_num}: table leaf{', heuristic' if is_heuristic else ''}, "
                  f"{hdr['num_cells']} cells, {len(pointers)} pointers", file=sys.stderr)
            
            cells_parsed = 0
            cells_with_records = 0
            
            for idx, ptr in enumerate(pointers):
                cell = parse_table_leaf_cell(data, page_offset, ptr, page_size)
                if cell is None:
                    continue
                
                cells_parsed += 1
                
                # Get full payload (handle overflow)
                if cell['overflow_page']:
                    local_payload = data[cell['payload_offset']:
                                        cell['payload_offset'] + cell['local_payload_len']]
                    full_payload = read_overflow_payload(
                        data, cell['overflow_page'], page_size,
                        cell['payload_len'], local_payload
                    )
                    if full_payload is None:
                        continue
                    record = parse_record(full_payload, 0, len(full_payload), column_hints)
                else:
                    record = parse_record(data, cell['payload_offset'],
                                         cell['payload_len'], column_hints)
                
                if record is None:
                    continue
                
                cells_with_records += 1
                raw_parsed_records.append(record)
                
                # Build record dict
                values = [v for _, v in record]
                if column_names and len(values) == len(column_names):
                    rec_dict = dict(zip(column_names, values))
                else:
                    # Use generic column names
                    rec_dict = {f'col{i}': v for i, v in enumerate(values)}
                
                rec_dict['_rowid'] = cell['rowid']
                all_records.append(rec_dict)
            
            if cells_with_records > 0:
                pages_with_data += 1
            
            print(f"  Cells: {cells_parsed} parsed, {cells_with_records} with valid records", 
                  file=sys.stderr)
        
        elif hdr.get('type_name') == 'table_interior':
            # Follow the B-tree to child pages
            pointers = read_cell_pointers(data, page_offset, hdr)
            # Interior cells contain (left_child_page, key) pairs
            # The rightmost child is in the page header
            child_pages = []
            for ptr in pointers:
                cell = parse_table_interior_cell(data, page_offset, ptr)
                if cell:
                    child_pages.append(cell['left_child'])
            if hdr.get('rightmost_pointer'):
                child_pages.append(hdr['rightmost_pointer'])
            
            # Process child pages (they should already be in our page loop)
            print(f"Page {page_num}: table interior, children: {child_pages}", 
                  file=sys.stderr)
    
    print(f"\nSummary: {pages_processed} pages processed, {pages_with_data} pages with data", 
          file=sys.stderr)
    
    # If no records found via structured parsing, try raw scan
    if not all_records:
        print("No records found via structured parsing. Trying raw scan...", 
              file=sys.stderr)
        fragments = scan_for_records(data, page_size)
        for frag in fragments:
            values = frag['values']
            if column_names and len(values) == len(column_names):
                rec_dict = dict(zip(column_names, values))
            else:
                rec_dict = {f'col{i}': v for i, v in enumerate(values)}
            all_records.append(rec_dict)
    
    # Remove internal metadata
    for rec in all_records:
        rec.pop('_rowid', None)
    
    # Clean up float values that are actually integers
    for rec in all_records:
        for key, val in rec.items():
            if isinstance(val, float) and val == int(val) and abs(val) < 1e15:
                rec[key] = int(val)
    
    # Write output
    write_json_output(all_records, output_path)
    
    print(f"Recovered {len(all_records)} records", file=sys.stderr)
    return all_records


def write_json_output(records: List[dict], output_path: str):
    """Write recovered records to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(records, f, indent=2, default=str)


# ─── CLI Entry Point ────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_file> <output_json> [--schema col1:type1,col2:type2]",
              file=sys.stderr)
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    schema_hint = None
    
    if '--schema' in sys.argv:
        idx = sys.argv.index('--schema')
        if idx + 1 < len(sys.argv):
            schema_hint = sys.argv[idx + 1]
    
    records = recover_database(db_path, output_path, schema_hint)
    print(json.dumps(records, indent=2, default=str))
