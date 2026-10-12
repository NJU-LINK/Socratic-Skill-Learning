#!/usr/bin/env python3
"""
General-purpose SQLite database recovery tool.

Recovers rows from corrupted SQLite databases by:
1. Parsing the file header and b-tree page structures
2. Using payload_size as an integrity checksum for each cell
3. Attempting single-bit-flip corrections on corrupted serial type bytes
4. Falling back to raw text/fragment scanning when cell headers are damaged
5. Reconstructing records from discovered fragments

Usage:
    python recover_sqlite.py <input.db> <output.json> [--schema COL1:TYPE1,COL2:TYPE2,...]

The output JSON is a list of dicts with column names as keys.
"""

import struct
import json
import sys
import os
import math
import re
from typing import Optional, List, Tuple, Dict, Any

# ─── Varint ───────────────────────────────────────────────────────────────

def read_varint(buf: bytes, offset: int) -> Tuple[int, int]:
    """Read a SQLite varint. Returns (value, bytes_consumed)."""
    result = 0
    for i in range(9):
        if offset + i >= len(buf):
            return result, i
        byte = buf[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | byte
            return result, i + 1
    return result, 9


def encode_varint(value: int) -> bytes:
    """Encode an integer as a SQLite varint."""
    if value < 0:
        value = value & 0xFFFFFFFFFFFFFFFF
    result = []
    if value <= 0x7f:
        return bytes([value])
    # For values up to 2^56
    temp = value
    parts = []
    while temp > 0x7f:
        parts.append(temp & 0x7f)
        temp >>= 7
    # Build from most significant
    parts.reverse()
    result = []
    for i, p in enumerate(parts):
        if i < len(parts) - 1:
            result.append(p | 0x80)
        else:
            result.append(p)
    return bytes(result)


# ─── Serial Types ─────────────────────────────────────────────────────────

def serial_type_size(st: int) -> int:
    """Return the data size in bytes for a serial type, or -1 if invalid."""
    if st == 0: return 0
    if st == 1: return 1
    if st == 2: return 2
    if st == 3: return 3
    if st == 4: return 4
    if st == 5: return 6
    if st == 6: return 8
    if st == 7: return 8
    if st == 8: return 0
    if st == 9: return 0
    if st >= 12 and st % 2 == 0: return (st - 12) // 2
    if st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1  # invalid


def decode_value(buf: bytes, offset: int, st: int) -> Any:
    """Decode a value from buf at offset given serial type st."""
    sz = serial_type_size(st)
    if sz < 0:
        return None
    if offset + sz > len(buf):
        return None
    if st == 0: return None
    if st == 1: return int.from_bytes(buf[offset:offset+1], 'big', signed=True)
    if st == 2: return int.from_bytes(buf[offset:offset+2], 'big', signed=True)
    if st == 3: return int.from_bytes(buf[offset:offset+3], 'big', signed=True)
    if st == 4: return struct.unpack('>i', buf[offset:offset+4])[0]
    if st == 5: return int.from_bytes(buf[offset:offset+6], 'big', signed=True)
    if st == 6: return struct.unpack('>q', buf[offset:offset+8])[0]
    if st == 7: return struct.unpack('>d', buf[offset:offset+8])[0]
    if st == 8: return 0
    if st == 9: return 1
    if st >= 12 and st % 2 == 0:
        return buf[offset:offset+sz]
    if st >= 13 and st % 2 == 1:
        return buf[offset:offset+sz].decode('utf-8', errors='replace')
    return None


def value_to_json(val: Any) -> Any:
    """Convert a decoded value to JSON-serializable form."""
    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='replace')
    if isinstance(val, float):
        # If it's an integer value stored as float, keep as float
        # unless the schema says INTEGER
        return val
    if isinstance(val, int):
        return val
    return val


# ─── Record Parsing ───────────────────────────────────────────────────────

def parse_record_header(buf: bytes, offset: int, header_size: int) -> List[int]:
    """Parse serial types from a record header."""
    serial_types = []
    off = offset
    header_end = offset + header_size
    while off < header_end:
        st, consumed = read_varint(buf, off)
        serial_types.append(st)
        off += consumed
    return serial_types


def try_parse_record(page_buf: bytes, rec_offset: int, payload_size: int) -> Optional[Tuple[List[int], List[Any]]]:
    """
    Try to parse a record at the given offset.
    Returns (serial_types, values) or None if the record is inconsistent.
    Uses payload_size as integrity checksum.
    """
    if rec_offset < 0 or rec_offset >= len(page_buf):
        return None
    
    off = rec_offset
    header_size, consumed = read_varint(page_buf, off)
    off += consumed
    
    if header_size < 1:
        return None
    if rec_offset + header_size > rec_offset + payload_size:
        return None
    
    # header_size includes the header_size varint itself, so pass remaining size
    serial_types = parse_record_header(page_buf, off, header_size - consumed)
    
    # Check: total data size must equal payload_size
    total_data = header_size
    for st in serial_types:
        sz = serial_type_size(st)
        if sz < 0:
            return None
        total_data += sz
    
    if total_data != payload_size:
        return None
    
    # Decode values
    val_off = rec_offset + header_size
    values = []
    for st in serial_types:
        val = decode_value(page_buf, val_off, st)
        values.append(val)
        val_off += serial_type_size(st)
    
    return (serial_types, values)


def try_fix_record_bitflip(page_buf: bytes, rec_offset: int, payload_size: int,
                            num_columns: Optional[int] = None) -> Optional[Tuple[List[int], List[Any]]]:
    """
    When payload_size checksum fails, try single-bit-flip corrections on
    the record header. This includes:
    1. The header_size byte(s) themselves
    2. The serial type bytes
    
    This is the principled recovery technique: the declared payload_size
    is the strongest integrity signal. If any byte in the record header
    is corrupted by bit flips, we can find the correct value by searching
    for a single-bit correction that makes the total size match.
    """
    # FIRST: Try flipping bits in the header_size byte(s)
    # The header_size varint can be 1-9 bytes, but usually 1 byte
    for hs_byte_offset in range(min(2, len(page_buf) - rec_offset)):
        hs_off = rec_offset + hs_byte_offset
        orig_byte = page_buf[hs_off]
        for bit in range(8):
            fixed_byte = orig_byte ^ (1 << bit)
            tmp = bytearray(page_buf)
            tmp[hs_off] = fixed_byte
            result = try_parse_record(bytes(tmp), rec_offset, payload_size)
            if result is not None:
                serial_types, values = result
                # Sanity check: text values should be printable
                looks_ok = True
                for v in values:
                    if isinstance(v, str):
                        if not all(c.isprintable() or c in '\t\n\r' for c in v):
                            looks_ok = False
                            break
                if looks_ok:
                    return result
    
    # SECOND: Try flipping bits in serial type bytes
    off = rec_offset
    header_size, consumed = read_varint(page_buf, off)
    header_start = off + consumed
    header_end = rec_offset + header_size
    
    if header_size < 1 or header_end > len(page_buf):
        return None
    
    # Read raw serial types
    raw_types = parse_record_header(page_buf, header_start, header_size - consumed)
    
    if num_columns is not None and len(raw_types) != num_columns:
        return None
    
    # Try flipping each bit in each serial type byte region
    # We need to know where each serial type varint starts
    st_offsets = []
    scan_off = header_start
    for _ in raw_types:
        st_offsets.append(scan_off)
        _, consumed2 = read_varint(page_buf, scan_off)
        scan_off += consumed2
    
    for col_idx in range(len(raw_types)):
        st_off = st_offsets[col_idx]
        orig_byte = page_buf[st_off]
        for bit in range(8):
            fixed_byte = orig_byte ^ (1 << bit)
            # Create a modified buffer
            tmp = bytearray(page_buf)
            tmp[st_off] = fixed_byte
            result = try_parse_record(bytes(tmp), rec_offset, payload_size)
            if result is not None:
                serial_types, values = result
                # Sanity check: text values should be printable
                looks_ok = True
                for v in values:
                    if isinstance(v, str):
                        if not all(c.isprintable() or c in '\t\n\r' for c in v):
                            looks_ok = False
                            break
                if looks_ok:
                    return result
    
    return None


def try_fix_record_multi_bitflip(page_buf: bytes, rec_offset: int, payload_size: int,
                                  num_columns: Optional[int] = None, max_flips: int = 2) -> Optional[Tuple[List[int], List[Any]]]:
    """
    Try multi-bit-flip corrections (up to max_flips bits total).
    More expensive but handles cases where multiple bits are corrupted.
    """
    # First try single-bit
    result = try_fix_record_bitflip(page_buf, rec_offset, payload_size, num_columns)
    if result:
        return result
    
    off = rec_offset
    header_size, consumed = read_varint(page_buf, off)
    header_start = off + consumed
    header_end = rec_offset + header_size
    
    if header_size < 1 or header_end > len(page_buf):
        return None
    
    raw_types = parse_record_header(page_buf, header_start, header_size - consumed)
    st_offsets = []
    scan_off = header_start
    for _ in raw_types:
        st_offsets.append(scan_off)
        _, consumed2 = read_varint(page_buf, scan_off)
        scan_off += consumed2
    
    # Try two-bit flips
    if max_flips >= 2:
        for col1 in range(len(raw_types)):
            for bit1 in range(8):
                for col2 in range(len(raw_types)):
                    for bit2 in range(8):
                        if col1 == col2 and bit2 <= bit1:
                            continue
                        tmp = bytearray(page_buf)
                        tmp[st_offsets[col1]] ^= (1 << bit1)
                        tmp[st_offsets[col2]] ^= (1 << bit2)
                        result = try_parse_record(bytes(tmp), rec_offset, payload_size)
                        if result is not None:
                            return result
    
    return None


def infer_serial_type_for_size(size: int, prefer_text: bool = True) -> int:
    """Given a required data size, infer the most likely serial type."""
    if size == 0:
        return 0  # NULL
    if size == 1:
        return 1  # int8
    if size == 2:
        return 2  # int16
    if size == 3:
        return 3  # int24
    if size == 4:
        return 4  # int32
    if size == 6:
        return 5  # int48
    if size == 8:
        # Could be int64 or float64; default to float64 if prefer_text
        return 7  # float64
    # For text/blob: size = (N-13)/2 for text, (N-12)/2 for blob
    if prefer_text:
        return 13 + 2 * size  # text
    else:
        return 12 + 2 * size  # blob


# ─── Schema Recovery ──────────────────────────────────────────────────────

def parse_sqlite_master(page_buf: bytes, page_offset: int, num_pages: int = 0) -> List[Dict]:
    """Parse the sqlite_master table from page 1."""
    btree_off = 0 if page_offset > 0 else 100  # page 1 has 100-byte file header
    
    if btree_off >= len(page_buf):
        return []
    
    page_type = page_buf[btree_off]
    if page_type != 13:  # not a leaf table page
        return []
    
    num_cells = struct.unpack('>H', page_buf[btree_off+3:btree_off+5])[0]
    
    entries = []
    for i in range(num_cells):
        ptr = struct.unpack('>H', page_buf[btree_off+8+2*i:btree_off+10+2*i])[0]
        
        off = ptr
        payload_size, consumed = read_varint(page_buf, off)
        off += consumed
        rowid, consumed = read_varint(page_buf, off)
        off += consumed
        
        result = try_parse_record(page_buf, off, payload_size)
        if result is None:
            result = try_fix_record_bitflip(page_buf, off, payload_size)
        
        if result:
            serial_types, values = result
            if len(values) >= 5:
                entry = {
                    'type': values[0],
                    'name': values[1],
                    'tbl_name': values[2],
                    'rootpage': values[3],
                    'sql': values[4]
                }
                # Validate the entry
                if entry['type'] not in ('table', 'index', 'view', 'trigger'):
                    continue  # wrong type → spurious bitflip
                if not isinstance(entry['sql'], str) or 'CREATE' not in entry['sql']:
                    continue  # SQL doesn't contain CREATE → truncated/wrong
                if not isinstance(entry['rootpage'], int) or entry['rootpage'] < 1:
                    continue  # invalid rootpage
                if num_pages > 0 and entry['rootpage'] > num_pages:
                    continue  # rootpage beyond database size
                entries.append(entry)
    
    return entries


def extract_schema_from_raw_text(data: bytes) -> List[Dict]:
    """
    Scan for CREATE TABLE statements as raw text when structured parsing fails.
    This handles cases where the sqlite_master record is too corrupted for
    normal parsing but the SQL text is still readable.
    """
    entries = []
    for m in re.finditer(rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', data):
        sql = m.group(0).decode('utf-8', errors='replace')
        table_name = m.group(1).decode('utf-8')
        entries.append({
            'type': 'table',
            'name': table_name,
            'tbl_name': table_name,
            'rootpage': 2,  # default assumption for single-table databases
            'sql': sql
        })
    return entries


def extract_schema_from_sql(sql: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Parse a CREATE TABLE statement to extract table name and columns.
    Returns (table_name, [(col_name, col_type), ...])
    """
    # Simple parser for CREATE TABLE
    m = re.match(r'CREATE\s+TABLE\s+(\w+)\s*\((.+)\)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return ('', [])
    
    table_name = m.group(1)
    cols_str = m.group(2)
    
    columns = []
    # Split by comma, but be careful of nested parens
    depth = 0
    current = ''
    for ch in cols_str:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            columns.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip():
        columns.append(current.strip())
    
    result = []
    for col_def in columns:
        parts = col_def.split()
        if len(parts) >= 2:
            col_name = parts[0].strip('"').strip("'").strip('`')
            col_type = parts[1].upper()
            result.append((col_name, col_type))
        elif len(parts) == 1:
            col_name = parts[0].strip('"').strip("'").strip('`')
            result.append((col_name, 'TEXT'))
    
    return (table_name, result)


# ─── Page Scanning ────────────────────────────────────────────────────────

def scan_page_for_records(page_buf: bytes, page_num: int, page_size: int,
                           num_columns: Optional[int] = None,
                           column_types: Optional[List[str]] = None,
                           text_pattern: Optional[bytes] = None) -> List[Tuple[int, List[Any]]]:
    """
    Scan a page for recoverable records.
    First tries structured parsing (cell pointer array), then falls back to
    raw scanning for record patterns.
    """
    records = []
    seen_rowids = set()
    
    # Determine if this is page 1
    is_page1 = (page_num == 1)
    btree_off = 100 if is_page1 else 0
    
    if btree_off >= len(page_buf):
        return []
    
    page_type = page_buf[btree_off]
    
    # Only process leaf table pages (type 13)
    if page_type != 13:
        return []
    
    num_cells = struct.unpack('>H', page_buf[btree_off+3:btree_off+5])[0]
    cell_content_offset = struct.unpack('>H', page_buf[btree_off+5:btree_off+7])[0]
    
    # Read cell pointers
    cell_ptrs = []
    for i in range(num_cells):
        ptr_off = btree_off + 8 + 2*i
        if ptr_off + 2 > len(page_buf):
            break
        ptr = struct.unpack('>H', page_buf[ptr_off:ptr_off+2])[0]
        cell_ptrs.append(ptr)
    
    # Parse each cell
    for ptr in cell_ptrs:
        if ptr >= len(page_buf):
            continue
        
        off = ptr
        payload_size, consumed = read_varint(page_buf, off)
        off += consumed
        rowid, consumed = read_varint(page_buf, off)
        off += consumed
        
        if payload_size <= 0 or payload_size > page_size:
            continue
        if rowid <= 0:
            continue
        
        # Try direct parse
        result = try_parse_record(page_buf, off, payload_size)
        
        # Try bit-flip fix
        if result is None:
            result = try_fix_record_bitflip(page_buf, off, payload_size, num_columns)
        
        # Try multi-bit-flip fix (expensive, only for small pages)
        if result is None and page_size <= 8192:
            result = try_fix_record_multi_bitflip(page_buf, off, payload_size, num_columns, max_flips=2)
        
        if result:
            serial_types, values = result
            if rowid not in seen_rowids:
                records.append((rowid, values))
                seen_rowids.add(rowid)
    
    # Fallback: if structured parsing recovered fewer cells than expected,
    # try raw fragment scanning for any remaining text patterns
    if len(records) < num_cells and text_pattern:
        fragments = scan_raw_for_fragments(page_buf, page_size, text_pattern)
        for rowid, values in fragments:
            if rowid not in seen_rowids:
                if num_columns is None or len(values) == num_columns:
                    records.append((rowid, values))
                    seen_rowids.add(rowid)
    
    return records


def scan_raw_for_fragments(data: bytes, page_size: int, 
                            text_pattern: Optional[bytes] = None) -> List[Tuple[int, List[Any]]]:
    """
    When structured parsing fails entirely, scan the raw file for
    recognizable text patterns and try to reconstruct records around them.
    Returns list of (rowid, values) tuples.
    """
    records = []
    
    if text_pattern is None:
        return records
    
    idx = 0
    while True:
        idx = data.find(text_pattern, idx)
        if idx == -1:
            break
        
        # Found a text fragment. Try to find the record header before it.
        # Look backwards for: [payload_size] [rowid] [header_size] [serial_types...] [text_data]
        
        # Try reading backwards from the text to find rowid and payload_size
        for search_back in range(3, 30):  # look up to 30 bytes back
            test_off = idx - search_back
            if test_off < 0:
                continue
            
            # Try to read payload_size varint
            try:
                payload_size, ps_consumed = read_varint(data, test_off)
                if payload_size <= 0 or payload_size > page_size:
                    continue
                
                # Try to read rowid varint
                rowid_off = test_off + ps_consumed
                rowid, rid_consumed = read_varint(data, rowid_off)
                if rowid <= 0 or rowid > 1000000:  # reasonable rowid limit
                    continue
                
                # Try to read header_size varint
                rec_off = rowid_off + rid_consumed
                header_size, hs_consumed = read_varint(data, rec_off)
                if header_size <= 0 or header_size > payload_size:
                    continue
                
                # Read serial types
                st_off = rec_off + hs_consumed
                serial_types = []
                total_st_size = 0
                valid = True
                while st_off < rec_off + header_size:
                    st, c = read_varint(data, st_off)
                    serial_types.append(st)
                    sz = serial_type_size(st)
                    if sz < 0:
                        valid = False
                        break
                    total_st_size += sz
                    st_off += c
                
                if not valid:
                    continue
                
                # Check if total size matches payload_size
                if header_size + total_st_size != payload_size:
                    continue
                
                # Decode values
                val_off = rec_off + header_size
                values = []
                decode_ok = True
                for st in serial_types:
                    val = decode_value(data, val_off, st)
                    if val is None and st != 0:  # NULL is ok
                        decode_ok = False
                        break
                    values.append(val)
                    val_off += serial_type_size(st)
                
                if not decode_ok:
                    continue
                
                # Check if any text value contains our pattern
                has_pattern = False
                for v in values:
                    if isinstance(v, str) and text_pattern.decode('utf-8', errors='ignore') in v:
                        has_pattern = True
                        break
                
                if has_pattern:
                    records.append((rowid, values))
                    break  # found a valid record for this text occurrence
                    
            except (IndexError, ValueError):
                continue
        
        idx += 1
    
    return records


# ─── Main Recovery ────────────────────────────────────────────────────────

def recover_database(db_path: str, output_path: str, 
                     schema_override: Optional[str] = None) -> List[Dict]:
    """
    Main recovery function. Reads a corrupted SQLite database and attempts
    to recover all records.
    """
    with open(db_path, 'rb') as f:
        data = f.read()
    
    # Parse file header
    if len(data) < 100:
        print("Error: file too small to be a SQLite database")
        return []
    
    magic = data[0:16]
    if magic != b'SQLite format 3\x00':
        print("Error: not a SQLite database (bad magic)")
        return []
    
    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1:
        page_size = 65536
    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
        print(f"Warning: unusual page size {page_size}")
    
    num_pages = len(data) // page_size
    print(f"Database: {len(data)} bytes, page_size={page_size}, pages={num_pages}")
    
    # Parse sqlite_master from page 1
    page1 = data[0:page_size]
    master_entries = parse_sqlite_master(page1, 0, num_pages)
    
    # ALWAYS try text extraction as well
    text_entries = extract_schema_from_raw_text(data)  # search entire file
    
    # Prefer text entries if they give valid SQL
    if text_entries:
        for te in text_entries:
            tname, cols = extract_schema_from_sql(te['sql'])
            if cols:  # text extraction found valid SQL
                master_entries = text_entries  # prefer text extraction
                print(f"Using text-extracted schema: {len(text_entries)} table(s)")
                break
    
    # If structured parsing failed AND text extraction failed
    if not master_entries:
        master_entries = text_entries
    
    tables = {}  # table_name -> {rootpage, columns, sql}
    
    for entry in master_entries:
        if entry['type'] == 'table':
            table_name = entry['name']
            rootpage = entry['rootpage']
            sql = entry['sql']
            tname, columns = extract_schema_from_sql(sql)
            tables[table_name] = {
                'rootpage': rootpage,
                'columns': columns,
                'sql': sql
            }
            print(f"Table '{table_name}': rootpage={rootpage}, columns={columns}")
    
    # If schema couldn't be parsed from sqlite_master, try to infer from raw data
    if not tables and schema_override:
        # Parse override: "col1:type1,col2:type2,..."
        columns = []
        for part in schema_override.split(','):
            parts = part.strip().split(':')
            if len(parts) == 2:
                columns.append((parts[0], parts[1].upper()))
        tables['_inferred'] = {
            'rootpage': 2,
            'columns': columns,
            'sql': ''
        }
    
    # If still no tables, try to infer from page structure
    if not tables:
        # Assume page 2 is a data page
        for pg in range(2, num_pages + 1):
            pg_data = data[(pg-1)*page_size:pg*page_size]
            if len(pg_data) < 12:
                continue
            pg_type = pg_data[0]
            if pg_type == 13:
                num_cells = struct.unpack('>H', pg_data[3:5])[0]
                if num_cells > 0:
                    # Try to infer column count from parseable cells
                    # Try multiple cells, not just the first
                    for ptr_idx in range(min(num_cells, 8)):
                        ptr = struct.unpack('>H', pg_data[8+2*ptr_idx:10+2*ptr_idx])[0]
                        off = ptr
                        ps, c = read_varint(pg_data, off)
                        off += c
                        rid, c = read_varint(pg_data, off)
                        off += c
                        result = try_parse_record(pg_data, off, ps)
                        if result is None:
                            result = try_fix_record_bitflip(pg_data, off, ps)
                        if result:
                            ncol = len(result[0])
                            tables['_inferred'] = {
                                'rootpage': pg,
                                'columns': [(f'col{i+1}', 'TEXT') for i in range(ncol)],
                                'sql': ''
                            }
                            break
                    if '_inferred' in tables:
                        break
    
    # BEST EFFORT MODE: If still no tables found, scan all pages for any parseable records
    # This handles severe corruption where schema is completely unrecoverable
    if not tables:
        print("No schema found - entering best-effort recovery mode")
        all_records_raw = []
        
        for pg in range(1, num_pages + 1):
            pg_data = data[(pg-1)*page_size:pg*page_size]
            if len(pg_data) < page_size:
                pg_data = pg_data + b'\x00' * (page_size - len(pg_data))
            
            # Skip page 1 (sqlite_master) for data records
            if pg == 1:
                continue
            
            # Scan without knowing schema
            page_records = scan_page_for_records(
                pg_data, pg, page_size,
                num_columns=None,
                column_types=None,
                text_pattern=None
            )
            
            for rowid, values in page_records:
                all_records_raw.append((pg, rowid, values))
        
        if all_records_raw:
            # Group by column count to separate potential tables
            by_ncol = {}
            for pg, rowid, values in all_records_raw:
                ncol = len(values)
                if ncol not in by_ncol:
                    by_ncol[ncol] = []
                by_ncol[ncol].append((pg, rowid, values))
            
            # Create inferred tables for each group
            for i, (ncol, recs) in enumerate(by_ncol.items()):
                table_name = f'_recovered_table_{i+1}'
                tables[table_name] = {
                    'rootpage': 0,  # unknown
                    'columns': [(f'col{j+1}', 'TEXT') for j in range(ncol)],
                    'sql': ''
                }
                # Store the records for later retrieval
                all_records[table_name] = (
                    tables[table_name]['columns'],
                    [(rowid, values) for _, rowid, values in recs]
                )
            
            print(f"Best-effort recovery found {len(all_records_raw)} records in {len(by_ncol)} table group(s)")
    
    # Recover records from each table
    all_records = {}
    
    for table_name, table_info in tables.items():
        rootpage = table_info['rootpage']
        columns = table_info['columns']
        num_columns = len(columns)
        column_types = [ct for _, ct in columns]
        
        records = []
        
        # Scan pages starting from rootpage
        # For simple cases (single leaf page), just scan that page
        # For multi-page tables, we'd need to traverse the b-tree
        # But with corruption, we scan all pages looking for matching records
        
        for pg in range(1, num_pages + 1):
            pg_data = data[(pg-1)*page_size:pg*page_size]
            if len(pg_data) < page_size:
                # Pad with zeros if truncated
                pg_data = pg_data + b'\x00' * (page_size - len(pg_data))
            
            # Try to infer a text pattern for fragment scanning
            # Use table name if it looks like a text identifier
            text_pattern = None
            if table_name.isalnum() and len(table_name) > 2:
                text_pattern = table_name.encode('utf-8')
            
            page_records = scan_page_for_records(
                pg_data, pg, page_size,
                num_columns=num_columns,
                column_types=column_types,
                text_pattern=text_pattern
            )
            
            for rowid, values in page_records:
                if len(values) == num_columns:
                    # Skip sqlite_master entries
                    if pg == 1 and table_name != '_inferred':
                        continue
                    records.append((rowid, values))
        
        # Deduplicate by rowid
        seen = set()
        unique_records = []
        for rowid, values in records:
            if rowid not in seen:
                seen.add(rowid)
                unique_records.append((rowid, values))
        
        unique_records.sort(key=lambda x: x[0])
        all_records[table_name] = (columns, unique_records)
    
    # Build output
    output = []
    
    if len(tables) == 1:
        # Single table: output as flat list
        table_name = list(tables.keys())[0]
        columns, records = all_records.get(table_name, ([], []))
        col_names = [cn for cn, _ in columns]
        
        for rowid, values in records:
            row = {}
            for i, (val, col_name) in enumerate(zip(values, col_names)):
                row[col_name] = value_to_json(val)
            output.append(row)
    else:
        # Multiple tables: output with table names
        for table_name in tables:
            columns, records = all_records.get(table_name, ([], []))
            col_names = [cn for cn, _ in columns]
            table_rows = []
            for rowid, values in records:
                row = {}
                for i, (val, col_name) in enumerate(zip(values, col_names)):
                    row[col_name] = value_to_json(val)
                table_rows.append(row)
            output.append({
                'table': table_name,
                'rows': table_rows
            })
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    total = sum(len(recs) for _, (_, recs) in all_records.items())
    print(f"Recovered {total} records total")
    for tname, (cols, recs) in all_records.items():
        print(f"  {tname}: {len(recs)} records")
    
    return output


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.db> <output.json> [--schema COL1:TYPE1,COL2:TYPE2,...]")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    schema_override = None
    
    if '--schema' in sys.argv:
        idx = sys.argv.index('--schema')
        if idx + 1 < len(sys.argv):
            schema_override = sys.argv[idx + 1]
    
    recover_database(db_path, output_path, schema_override)


if __name__ == '__main__':
    main()
