#!/usr/bin/env python3
"""
Generalized SQLite database recovery script.

Recovers rows from corrupted SQLite databases by parsing raw binary structures
when standard sqlite3 queries fail. Handles various corruption mechanisms:
truncation, zeroed regions, bit-flips, damaged headers, and fragments.

Usage:
    python3 recover.py <input_db> <output_json> [--schema-hints COL1:TYPE,COL2:TYPE]
    
Examples:
    python3 recover.py /app/trunc.db /app/recover.json
    python3 recover.py damaged.db recovered.json --schema-hints word:TEXT,value:REAL
"""

import struct
import json
import sys
import re
import argparse
from typing import List, Dict, Any, Optional, Tuple


def read_varint(data: bytes, offset: int) -> Tuple[Optional[int], int]:
    """
    Read a SQLite varint starting at offset.
    
    Returns (value, bytes_consumed).
    Value is None if we ran past end of data.
    """
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return None, i + 1
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


def is_valid_serial_type(st: int) -> bool:
    """Check if a serial type value is valid per SQLite spec."""
    if st in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        return True
    if st >= 12 and st % 2 == 0:  # BLOB
        return True
    if st >= 13 and st % 2 == 1:  # TEXT
        return True
    return False


def serial_type_data_size(st: int) -> int:
    """Return the data size in bytes for a given serial type."""
    sizes = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8, 7: 8, 8: 0, 9: 0}
    if st in sizes:
        return sizes[st]
    if st >= 12 and st % 2 == 0:  # BLOB
        return (st - 12) // 2
    if st >= 13 and st % 2 == 1:  # TEXT
        return (st - 13) // 2
    return -1  # Invalid


def try_fix_serial_type(st: int, data: bytes, data_offset: int, remaining_payload: int) -> Optional[int]:
    """
    Try to fix a corrupted serial type by single-bit-flip correction.
    
    A serial type may be structurally valid (e.g. 0x61 = TEXT(42)) but
    contextually invalid because the claimed data size exceeds the remaining
    payload. In such cases, try flipping individual bits to find a type that
    both fits the payload and produces sensible data.
    
    Returns the corrected serial type if a valid fix is found, else None.
    """
    candidates = []
    for bit in range(8):
        candidate = st ^ (1 << bit)
        if not is_valid_serial_type(candidate):
            continue
        needed = serial_type_data_size(candidate)
        if needed < 0:
            continue
        if data_offset + needed > len(data):
            continue
        if needed > remaining_payload:
            continue
        # Additional validation: if it's TEXT, check if the bytes are printable
        if candidate >= 13 and candidate % 2 == 1:
            text_len = (candidate - 13) // 2
            text_bytes = data[data_offset:data_offset + text_len]
            try:
                text = text_bytes.decode('utf-8')
                if text.isprintable() and len(text) > 0:
                    candidates.append((candidate, text_len))
            except:
                pass
        else:
            candidates.append((candidate, needed))
    
    if not candidates:
        return None
    # Prefer the candidate whose data size fits best within remaining payload
    candidates.sort(key=lambda x: abs(x[1] - remaining_payload))
    return candidates[0][0]


def extract_value(data: bytes, offset: int, serial_type: int) -> Tuple[Any, int]:
    """
    Extract a value from data at offset based on serial type.
    
    Returns (value, bytes_consumed).
    """
    if serial_type == 0:  # NULL
        return None, 0
    elif serial_type == 1:  # int8
        return struct.unpack('>b', data[offset:offset+1])[0], 1
    elif serial_type == 2:  # int16
        return struct.unpack('>h', data[offset:offset+2])[0], 2
    elif serial_type == 3:  # int24
        raw = data[offset:offset+3]
        val = int.from_bytes(raw, 'big', signed=True)
        return val, 3
    elif serial_type == 4:  # int32
        return struct.unpack('>i', data[offset:offset+4])[0], 4
    elif serial_type == 5:  # int48
        raw = data[offset:offset+6]
        val = int.from_bytes(raw, 'big', signed=True)
        return val, 6
    elif serial_type == 6:  # int64
        return struct.unpack('>q', data[offset:offset+8])[0], 8
    elif serial_type == 7:  # float64
        return struct.unpack('>d', data[offset:offset+8])[0], 8
    elif serial_type == 8:  # integer constant 0
        return 0, 0
    elif serial_type == 9:  # integer constant 1
        return 1, 0
    elif serial_type >= 12 and serial_type % 2 == 0:  # BLOB
        blob_len = (serial_type - 12) // 2
        return data[offset:offset+blob_len], blob_len
    elif serial_type >= 13 and serial_type % 2 == 1:  # TEXT
        text_len = (serial_type - 13) // 2
        try:
            val = data[offset:offset+text_len].decode('utf-8')
        except:
            val = data[offset:offset+text_len].decode('latin-1')
        return val, text_len
    else:
        return None, -1


def parse_record(data: bytes, payload_start: int, payload_len: int,
                 corrupt_recovery: bool = True) -> Optional[List[Any]]:
    """
    Parse a SQLite record payload.
    
    Args:
        data: full file data
        payload_start: offset where payload begins
        payload_len: total payload length
        corrupt_recovery: whether to attempt corruption recovery
    
    Returns:
        List of column values, or None if parsing fails
    """
    pos = payload_start
    payload_end = payload_start + payload_len
    
    # Read header size
    header_size, consumed = read_varint(data, pos)
    if header_size is None or header_size < 3:
        return None
    if pos + header_size > payload_end:
        return None
    
    # Read serial types
    serial_types = []
    type_pos = pos + consumed
    header_end = pos + header_size
    while type_pos < header_end:
        st, c = read_varint(data, type_pos)
        if st is None:
            return None
        serial_types.append(st)
        type_pos += c
    
    # Extract values
    data_pos = header_end
    values = []
    for i, st in enumerate(serial_types):
        # Validate serial type and check if data fits
        needed = serial_type_data_size(st)
        needs_fix = False
        
        if not is_valid_serial_type(st):
            needs_fix = True
        elif needed < 0:
            return None
        elif data_pos + needed > payload_end:
            needs_fix = True
        elif data_pos + needed > len(data):
            needs_fix = True
        
        if needs_fix:
            if corrupt_recovery:
                remaining = payload_end - data_pos
                fixed = try_fix_serial_type(st, data, data_pos, remaining)
                if fixed is not None:
                    st = fixed
                    needed = serial_type_data_size(st)
                    serial_types[i] = st  # Update for later reference
                else:
                    return None
            else:
                return None
        
        val, actual_consumed = extract_value(data, data_pos, st)
        if actual_consumed < 0:
            return None
        values.append(val)
        data_pos += actual_consumed
    
    # Check if all payload bytes were consumed
    # If data_pos < payload_end, the last serial type may have been corrupted to be too small
    if data_pos < payload_end and corrupt_recovery and serial_types:
        remaining = payload_end - data_pos
        last_idx = len(serial_types) - 1
        last_st = serial_types[last_idx]
        
        # Try bit-flip corrections on the last serial type that would increase its size
        if last_st >= 13 and last_st % 2 == 1:  # TEXT type
            last_data_start = data_pos - serial_type_data_size(last_st)
            for bit in range(8):
                candidate = last_st ^ (1 << bit)
                if candidate >= 13 and candidate % 2 == 1:
                    new_len = (candidate - 13) // 2
                    old_len = serial_type_data_size(last_st)
                    # Check if this correction would consume exactly the right amount
                    if last_data_start + new_len == payload_end:
                        # Re-extract the last value with corrected length
                        try:
                            corrected_text = data[last_data_start:last_data_start+new_len].decode('utf-8')
                            if corrected_text.isprintable():
                                values[last_idx] = corrected_text
                                data_pos = payload_end
                                break
                        except:
                            pass
    
    return values


def extract_schema_from_master(data: bytes, page_size: int) -> Dict[str, List[str]]:
    """
    Try to extract table schemas from the sqlite_master table on page 0.
    
    The sqlite_master table (rowid=1) contains CREATE TABLE SQL statements.
    We parse these to extract column names for each user table.
    
    Returns: dict mapping table_name -> [col1, col2, ...]
    """
    schemas = {}
    
    # Page 0 B-tree header is at offset 100
    btree_off = 100
    if btree_off >= len(data):
        return schemas
    
    page_type = data[btree_off]
    if page_type != 0x0D:  # Not a leaf table page
        return schemas
    
    num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
    ptr_array_off = btree_off + 8
    
    for cell_idx in range(num_cells):
        ptr_off = ptr_array_off + 2 * cell_idx
        if ptr_off + 2 > len(data):
            break
        
        ptr = struct.unpack('>H', data[ptr_off:ptr_off+2])[0]
        cell_abs = ptr  # Page 0, so offset = ptr directly
        
        if cell_abs >= len(data):
            continue
        
        # Read payload length
        payload_len, vc = read_varint(data, cell_abs)
        if payload_len is None or payload_len <= 0:
            continue
        
        # Read rowid
        rowid, vc2 = read_varint(data, cell_abs + vc)
        if rowid is None:
            continue
        
        # Parse record
        payload_start = cell_abs + vc + vc2
        if payload_start + payload_len > len(data):
            continue
        
        record = parse_record(data, payload_start, payload_len, corrupt_recovery=True)
        if record is None or len(record) < 5:
            continue
        
        # sqlite_master columns: type, name, tbl_name, rootpage, sql
        rec_type = record[0]  # 'table', 'index', etc.
        rec_name = record[1]  # object name
        tbl_name = record[2]  # table name
        rootpage = record[3]  # root page number
        sql = record[4]       # CREATE TABLE SQL
        
        if isinstance(rec_type, str) and rec_type == 'table' and isinstance(sql, str):
            # Parse column names from CREATE TABLE SQL
            # Pattern: CREATE TABLE name (col1 TYPE1, col2 TYPE2, ...)
            match = re.search(r'\(([^)]+)\)', sql)
            if match:
                cols_str = match.group(1)
                cols = []
                for col_def in cols_str.split(','):
                    col_def = col_def.strip()
                    parts = col_def.split()
                    if parts:
                        cols.append(parts[0])
                if cols:
                    schemas[tbl_name] = cols
    
    return schemas


def get_interior_child_pages(data: bytes, page_idx: int, page_size: int) -> List[int]:
    """
    For an interior table B-tree page (type 0x05), extract child page numbers.
    
    Returns list of child page indices (0-based).
    """
    page_off = page_idx * page_size
    btree_off = page_off  # Interior pages don't have the 100-byte file header offset
    
    if btree_off >= len(data):
        return []
    
    page_type = data[btree_off]
    if page_type != 0x05:
        return []
    
    if btree_off + 12 > len(data):
        return []
    
    num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
    # Right-most pointer at offset +8 (4 bytes)
    right_ptr = struct.unpack('>I', data[btree_off+8:btree_off+12])[0]
    
    children = []
    ptr_array_off = btree_off + 12  # Interior header is 12 bytes
    
    for cell_idx in range(num_cells):
        ptr_off = ptr_array_off + 2 * cell_idx
        if ptr_off + 2 > len(data):
            break
        
        cell_ptr = struct.unpack('>H', data[ptr_off:ptr_off+2])[0]
        cell_abs = page_off + cell_ptr
        
        # Interior cell: payload_len(varint) + child_page(4 bytes) + rowid(varint)
        # We need the child page number
        pl, vc = read_varint(data, cell_abs)
        if pl is None:
            continue
        
        if cell_abs + vc + 4 > len(data):
            continue
        
        child_page = struct.unpack('>I', data[cell_abs+vc:cell_abs+vc+4])[0]
        children.append(child_page - 1)  # Convert to 0-based index
    
    # Add right-most pointer
    if right_ptr > 0:
        children.append(right_ptr - 1)  # Convert to 0-based index
    
    return children


def find_all_leaf_pages(data: bytes, page_size: int) -> List[int]:
    """
    Find all leaf table B-tree pages by traversing the B-tree structure.
    
    Starts from page 0 (which is both the schema table and root) and follows
    interior page pointers to discover all leaf pages.
    """
    num_pages = len(data) // page_size
    leaf_pages = []
    
    # Check page 0
    btree_off = 100  # Page 0 has 100-byte file header
    if btree_off < len(data):
        page_type = data[btree_off]
        if page_type == 0x0D:
            leaf_pages.append(0)
        elif page_type == 0x05:
            # Interior page - need to handle differently
            pass
    
    # Check all other pages
    for page_idx in range(1, num_pages):
        page_off = page_idx * page_size
        btree_off = page_off
        
        if btree_off >= len(data):
            break
        
        page_type = data[btree_off]
        if page_type == 0x0D:
            leaf_pages.append(page_idx)
        elif page_type == 0x05:
            # Follow child pointers
            children = get_interior_child_pages(data, page_idx, page_size)
            for child_idx in children:
                if 0 <= child_idx < num_pages and child_idx not in leaf_pages:
                    child_off = child_idx * page_size
                    if child_off < len(data):
                        child_type = data[child_off]
                        if child_type == 0x0D:
                            leaf_pages.append(child_idx)
    
    return leaf_pages


def parse_page_cells(data: bytes, page_idx: int, page_size: int,
                     skip_schema: bool = False
                     ) -> List[Tuple[int, List[Any]]]:
    """
    Parse all cells from a leaf table B-tree page.
    
    Returns list of (rowid, values) tuples.
    """
    page_off = page_idx * page_size
    btree_off = page_off + (100 if page_idx == 0 else 0)
    
    if btree_off >= len(data):
        return []
    
    page_type = data[btree_off]
    
    results = []
    
    if page_type == 0x0D:  # Leaf table B-tree
        if btree_off + 8 > len(data):
            return []
        
        num_cells = struct.unpack('>H', data[btree_off+3:btree_off+5])[0]
        
        ptr_array_off = btree_off + 8
        
        for cell_idx in range(num_cells):
            ptr_off = ptr_array_off + 2 * cell_idx
            if ptr_off + 2 > len(data):
                break
            
            ptr = struct.unpack('>H', data[ptr_off:ptr_off+2])[0]
            cell_abs = page_off + ptr
            
            if cell_abs >= len(data):
                continue
            
            # Read payload length
            payload_len, vc = read_varint(data, cell_abs)
            if payload_len is None or payload_len <= 0:
                continue
            
            # Read rowid
            rowid, vc2 = read_varint(data, cell_abs + vc)
            if rowid is None:
                continue
            
            # Parse record
            payload_start = cell_abs + vc + vc2
            if payload_start + payload_len > len(data):
                continue
            
            record = parse_record(data, payload_start, payload_len)
            if record is not None:
                # Skip sqlite_schema entries if requested
                if skip_schema and page_idx == 0:
                    if len(record) >= 1 and isinstance(record[0], str):
                        if record[0] in ('table', 'index', 'view', 'trigger'):
                            continue
                results.append((rowid, record))
    
    return results


def brute_force_scan(data: bytes, page_size: int,
                     text_patterns: Optional[List[bytes]] = None,
                     expected_num_cols: Optional[int] = None
                     ) -> List[Tuple[int, List[Any]]]:
    """
    Brute-force scan the entire file for recoverable records.
    
    Strategy: scan forward through the file looking for valid record headers.
    A record header starts with a header_size varint, followed by serial type
    varints. We validate by checking that:
    1. The header size is reasonable (3-50 bytes)
    2. All serial types are valid
    3. The total data size implied by serial types matches a plausible payload
    4. TEXT columns contain printable characters
    
    Also searches for known text patterns and tries to reconstruct records around them.
    """
    results = []
    seen_records = set()  # Dedup by (offset, first_text_value)
    
    # Part 1: Forward scan for record headers
    # Look for patterns: [header_size] [serial_type_1] ... where serial_type_1 is TEXT
    for offset in range(len(data) - 10):
        # Skip zeroed regions quickly
        if data[offset] == 0:
            continue
        
        # Try reading header_size varint
        hs, hc = read_varint(data, offset)
        if hs is None or hs < 3 or hs > 50:
            continue
        
        # Read serial types
        serial_types = []
        tp = offset + hc
        header_end = offset + hs
        valid = True
        
        while tp < header_end:
            if tp >= len(data):
                valid = False
                break
            st, c = read_varint(data, tp)
            if st is None:
                valid = False
                break
            if not is_valid_serial_type(st):
                valid = False
                break
            serial_types.append(st)
            tp += c
        
        if not valid or len(serial_types) == 0:
            continue
        
        # Calculate total data size
        total_data = 0
        for st in serial_types:
            sz = serial_type_data_size(st)
            if sz < 0:
                valid = False
                break
            total_data += sz
        
        if not valid:
            continue
        
        payload_len = hs + total_data
        if payload_len < 5 or payload_len > 10000:
            continue
        
        # Check that we have enough data
        if offset + payload_len > len(data):
            continue
        
        # Validate: at least one TEXT column should contain printable text
        data_pos = header_end
        has_printable_text = False
        values = []
        
        for st in serial_types:
            sz = serial_type_data_size(st)
            if st >= 13 and st % 2 == 1:  # TEXT
                text_bytes = data[data_pos:data_pos+sz]
                try:
                    text = text_bytes.decode('utf-8')
                    if text.isprintable() and len(text) > 0:
                        has_printable_text = True
                        values.append(text)
                    else:
                        valid = False
                        break
                except:
                    valid = False
                    break
            else:
                val, _ = extract_value(data, data_pos, st)
                values.append(val)
            data_pos += sz
        
        if not valid or not has_printable_text:
            continue
        
        # Filter by expected column count if provided
        if expected_num_cols is not None and len(serial_types) != expected_num_cols:
            continue
        
        # Filter out sqlite_master records
        if len(values) >= 1 and isinstance(values[0], str):
            if values[0] in ('table', 'index', 'view', 'trigger'):
                continue
        
        # Dedup
        key = (offset, values[0] if values else None)
        if key in seen_records:
            continue
        seen_records.add(key)
        
        # Try to find rowid by looking backward for payload_len + rowid
        # This is optional - we'll use offset as a pseudo-rowid if not found
        rowid = offset  # Default: use offset as identifier
        
        # Look backward: cell format is payload_len(varint) rowid(varint) payload
        for back in range(1, 10):
            pre_start = offset - back
            if pre_start < 0:
                break
            
            pl, plc = read_varint(data, pre_start)
            if pl is None or pl != payload_len:
                continue
            
            rid, ridc = read_varint(data, pre_start + plc)
            if rid is None:
                continue
            
            if pre_start + plc + ridc == offset:
                rowid = rid
                break
        
        results.append((rowid, values))
    
    # Part 2: Pattern-based scanning
    if text_patterns:
        for pattern in text_patterns:
            pos = 0
            while True:
                idx = data.find(pattern, pos)
                if idx == -1:
                    break
                
                # Try to find a record header before this text
                for back in range(3, 30):
                    hdr_start = idx - back
                    if hdr_start < 0:
                        break
                    
                    hs, hc = read_varint(data, hdr_start)
                    if hs is None or hs < 3 or hs > 30:
                        continue
                    
                    # Check if serial types parse correctly
                    serial_types = []
                    tp = hdr_start + hc
                    header_end = hdr_start + hs
                    valid = True
                    
                    while tp < header_end:
                        st, c = read_varint(data, tp)
                        if st is None or not is_valid_serial_type(st):
                            valid = False
                            break
                        serial_types.append(st)
                        tp += c
                    
                    if not valid:
                        continue
                    
                    # Calculate data offset where text should be
                    data_pos = header_end
                    text_found = False
                    values = []
                    
                    for st in serial_types:
                        sz = serial_type_data_size(st)
                        if data_pos + sz > len(data):
                            valid = False
                            break
                        if st >= 13 and st % 2 == 1:
                            if data_pos == idx:
                                text_found = True
                            try:
                                text = data[data_pos:data_pos+sz].decode('utf-8')
                                values.append(text)
                            except:
                                values.append(data[data_pos:data_pos+sz].decode('latin-1'))
                        else:
                            val, _ = extract_value(data, data_pos, st)
                            values.append(val)
                        data_pos += sz
                    
                    if valid and text_found and len(values) >= 2:
                        key = (hdr_start, values[0])
                        if key not in seen_records:
                            seen_records.add(key)
                            results.append((hdr_start, values))
                        break
                
                pos = idx + 1
    
    return results


def recover_database(input_path: str, output_path: str,
                     schema_hints: Optional[List[Tuple[str, str]]] = None,
                     text_patterns: Optional[List[bytes]] = None):
    """
    Main recovery function.
    
    Args:
        input_path: path to corrupted SQLite database
        output_path: path to write recovered JSON
        schema_hints: optional list of (column_name, type) tuples
        text_patterns: optional list of byte patterns to search for
    """
    with open(input_path, 'rb') as f:
        data = f.read()
    
    if len(data) < 100:
        print(f"Error: file too small ({len(data)} bytes)")
        return
    
    # Verify SQLite magic
    magic = data[:16]
    if not magic.startswith(b'SQLite format 3'):
        print(f"Warning: file does not start with SQLite magic")
    
    # Read page size
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 0 or page_size > 65536:
        print(f"Error: invalid page size {page_size}")
        return
    
    num_pages = len(data) // page_size
    print(f"Database: {len(data)} bytes, page_size={page_size}, pages={num_pages}")
    
    # Phase 1: Extract schema from sqlite_master if possible
    col_names = None
    if schema_hints:
        col_names = [name for name, _ in schema_hints]
    else:
        # Try to extract from sqlite_master
        schemas = extract_schema_from_master(data, page_size)
        if schemas:
            # Use the first non-internal table
            for tbl_name, cols in schemas.items():
                if not tbl_name.startswith('sqlite_'):
                    col_names = cols
                    print(f"Extracted schema for '{tbl_name}': {cols}")
                    break
    
    # Phase 2: Find all leaf pages (including via interior page traversal)
    leaf_pages = find_all_leaf_pages(data, page_size)
    print(f"Found {len(leaf_pages)} leaf pages: {leaf_pages}")
    
    # Phase 3: Header-guided recovery from leaf pages
    all_records = {}  # rowid -> values (dedup by rowid)
    schema_rowids = set()
    
    # First pass: collect schema table rowids from page 0
    if 0 in leaf_pages:
        schema_cells = parse_page_cells(data, 0, page_size, skip_schema=False)
        for rowid, values in schema_cells:
            if len(values) >= 1 and isinstance(values[0], str):
                if values[0] in ('table', 'index', 'view', 'trigger'):
                    schema_rowids.add(rowid)
    
    # Second pass: recover data from all leaf pages
    for page_idx in leaf_pages:
        cells = parse_page_cells(data, page_idx, page_size, skip_schema=True)
        for rowid, values in cells:
            if rowid not in all_records:
                all_records[rowid] = values
    
    print(f"Header-guided recovery: {len(all_records)} records")
    
    # Phase 4: Brute-force recovery for missed records
    expected_cols = len(col_names) if col_names else None
    bf_records = brute_force_scan(data, page_size, text_patterns, expected_cols)
    bf_added = 0
    for rowid, values in bf_records:
        # Check if this rowid already exists
        if rowid not in all_records:
            all_records[rowid] = values
            bf_added += 1
    
    print(f"Brute-force recovery: {bf_added} additional records")
    
    # Phase 5: Format output
    if col_names is None:
        # Fall back to generic names
        if all_records:
            first = next(iter(all_records.values()))
            col_names = [f"col{i}" for i in range(len(first))]
        else:
            col_names = []
    
    # Build output list
    output = []
    for rowid in sorted(all_records.keys()):
        values = all_records[rowid]
        record = {}
        for i, val in enumerate(values):
            if i < len(col_names):
                key = col_names[i]
            else:
                key = f"col{i}"
            
            # Format value appropriately
            if isinstance(val, float):
                # Check if it's a whole number
                if val == int(val) and abs(val) < 2**53:
                    record[key] = int(val)
                else:
                    record[key] = val
            else:
                record[key] = val
        output.append(record)
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Recovered {len(output)} records -> {output_path}")
    return output


def main():
    parser = argparse.ArgumentParser(description='Recover rows from corrupted SQLite database')
    parser.add_argument('input_db', help='Path to corrupted SQLite database')
    parser.add_argument('output_json', help='Path to write recovered JSON')
    parser.add_argument('--schema-hints', help='Column schema hints: COL1:TYPE,COL2:TYPE',
                       default=None)
    parser.add_argument('--text-patterns', help='Comma-separated text patterns to search for',
                       default=None)
    
    args = parser.parse_args()
    
    # Parse schema hints
    schema_hints = None
    if args.schema_hints:
        schema_hints = []
        for hint in args.schema_hints.split(','):
            parts = hint.strip().split(':')
            if len(parts) == 2:
                schema_hints.append((parts[0], parts[1]))
    
    # Parse text patterns
    text_patterns = None
    if args.text_patterns:
        text_patterns = [p.encode('utf-8') for p in args.text_patterns.split(',')]
    
    recover_database(args.input_db, args.output_json, schema_hints, text_patterns)


if __name__ == '__main__':
    main()
