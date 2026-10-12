#!/usr/bin/env python3
"""
SQLite corruption recovery tool.
Recovers rows from damaged SQLite files by binary parsing.

Usage:
    python3 recover.py <db_path> <output_json_path> [--columns col1,col2,...]

The script:
1. Tries standard sqlite3 access first
2. Falls back to binary B-tree traversal + record parsing
3. Detects and repairs corrupted serial types
4. Handles interior pages, overflow pages, and multi-table databases
5. Outputs JSON array of row objects
"""
import struct, json, sys, sqlite3, re, os

# ---------------------------------------------------------------------------
# Low-level primitives
# ---------------------------------------------------------------------------

def read_varint(data, offset):
    """Read a SQLite varint starting at data[offset].
    Returns (value, bytes_consumed)."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, i
        b = data[offset + i]
        if i < 8:
            result = (result << 7) | (b & 0x7f)
            if b < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | b
            return result, i + 1
    return result, 9

def serial_type_size(st):
    """Return data size in bytes for a serial type, or -1 if invalid."""
    if st in (0, 8, 9): return 0
    elif 1 <= st <= 6: return [0, 1, 2, 3, 4, 6, 8][st]
    elif st == 7: return 8
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1

def decode_serial_value(data, offset, st):
    """Decode a single value given its serial type. Returns (value, bytes_consumed)."""
    if st == 0: return None, 0
    elif 1 <= st <= 6:
        n = [0,1,2,3,4,6,8][st]
        if offset + n > len(data): return None, 0
        return int.from_bytes(data[offset:offset+n], 'big', signed=True), n
    elif st == 7:
        if offset + 8 > len(data): return None, 0
        return struct.unpack('>d', data[offset:offset+8])[0], 8
    elif st == 8: return 0, 0
    elif st == 9: return 1, 0
    elif st >= 13 and st % 2 == 1:
        n = (st - 13) // 2
        if offset + n > len(data): return None, 0
        return data[offset:offset+n].decode('utf-8', errors='replace'), n
    elif st >= 12 and st % 2 == 0:
        n = (st - 12) // 2
        if offset + n > len(data): return None, 0
        return bytes(data[offset:offset+n]), n
    return None, 0

# ---------------------------------------------------------------------------
# Record decoding
# ---------------------------------------------------------------------------

def decode_record(data, offset, payload_len):
    """Decode a SQLite record at data[offset:offset+payload_len].
    Returns (serial_types, values) or None on failure."""
    if offset + payload_len > len(data) or payload_len < 2:
        return None

    header_size = data[offset]
    if header_size < 2 or header_size > payload_len:
        return None

    # Parse serial types from header
    serial_types = []
    pos = 1  # relative to record start
    while pos < header_size:
        st, consumed = read_varint(data, offset + pos)
        serial_types.append(st)
        pos += consumed

    if pos != header_size:
        return None

    # Validate: compute expected data size
    total_data = 0
    for st in serial_types:
        sz = serial_type_size(st)
        if sz < 0: return None
        total_data += sz

    if header_size + total_data > payload_len:
        return None  # Corruption: types need more data than available

    # Decode values
    values = []
    di = offset + header_size
    for st in serial_types:
        val, consumed = decode_serial_value(data, di, st)
        values.append(val)
        di += consumed

    return serial_types, values

def try_fix_corrupted_record(data, offset, payload_len, expected_ncols=None):
    """Attempt to fix a record with corrupted serial types."""
    if offset + payload_len > len(data) or payload_len < 2:
        return None

    header_size = data[offset]
    if header_size < 2 or header_size > payload_len:
        return None

    # Parse raw serial types
    raw_types = []
    pos = 1
    while pos < header_size:
        st, consumed = read_varint(data, offset + pos)
        raw_types.append(st)
        pos += consumed

    if expected_ncols and len(raw_types) != expected_ncols:
        return None

    available_data = payload_len - header_size

    # Check which types are inconsistent
    declared_sizes = [serial_type_size(st) for st in raw_types]
    total_declared = sum(s for s in declared_sizes if s >= 0)

    if total_declared <= available_data and all(s >= 0 for s in declared_sizes):
        # Actually consistent - decode normally
        return decode_record(data, offset, payload_len)

    # Find corrupted columns
    corrupted_indices = []
    known_size = 0
    for i, (st, sz) in enumerate(zip(raw_types, declared_sizes)):
        if sz < 0 or sz > available_data:
            corrupted_indices.append(i)
        else:
            known_size += sz

    remaining = available_data - known_size

    # Fix: assume single corrupted column is text
    if len(corrupted_indices) == 1 and remaining > 0:
        idx = corrupted_indices[0]
        fixed_st = 13 + 2 * remaining  # text serial type
        fixed_types = list(raw_types)
        fixed_types[idx] = fixed_st

        # Decode with fixed types
        values = []
        di = offset + header_size
        for st in fixed_types:
            val, consumed = decode_serial_value(data, di, st)
            values.append(val)
            di += consumed

        return fixed_types, values

    return None

# ---------------------------------------------------------------------------
# Overflow page handling
# ---------------------------------------------------------------------------

def read_full_payload(data, page_size, page_data, rec_offset, payload_len,
                      cell_end_in_page):
    """Read a potentially overflowed record payload.
    
    If the entire payload fits in the current page, return it directly.
    Otherwise, follow the overflow page chain.
    
    Args:
        data: full file bytes
        page_size: page size
        page_data: current page bytes
        rec_offset: offset of record start within page_data
        payload_len: total payload length
        cell_end_in_page: offset where the cell ends in page_data
                          (for leaf cells, this is where overflow page# is stored)
    
    Returns: bytes of the full payload, or None on failure.
    """
    # Check if payload fits entirely in the current page
    if rec_offset + payload_len <= len(page_data):
        return page_data[rec_offset:rec_offset + payload_len]
    
    # Payload overflows. The local portion goes up to the end of usable space.
    # For a leaf table cell, the last 4 bytes of the cell are the first overflow page#.
    # Local payload size = payload_len that fits before the 4-byte overflow pointer.
    # The cell in the page is: [payload_len varint][rowid varint][local_payload][overflow_page:4]
    # We need to figure out how much local payload we have.
    
    # The cell occupies from the cell pointer to cell_end_in_page.
    # The local payload starts at rec_offset and ends at cell_end_in_page - 4.
    local_payload_end = cell_end_in_page - 4
    if local_payload_end <= rec_offset:
        return None
    
    local_payload = page_data[rec_offset:local_payload_end]
    
    # Read the first overflow page number
    if cell_end_in_page > len(page_data):
        return None
    overflow_page = struct.unpack('>I', page_data[local_payload_end:cell_end_in_page])[0]
    
    # Follow overflow chain
    full_payload = bytearray(local_payload)
    visited = set()
    
    while overflow_page != 0 and overflow_page not in visited:
        visited.add(overflow_page)
        if overflow_page < 1 or overflow_page > len(data) // page_size:
            break
        
        ov_start = (overflow_page - 1) * page_size
        ov_page = data[ov_start:ov_start + page_size]
        if len(ov_page) < 4:
            break
        
        # First 4 bytes: next overflow page (0 = end)
        next_overflow = struct.unpack('>I', ov_page[0:4])[0]
        # Remaining bytes are payload continuation
        ov_payload = ov_page[4:]
        full_payload.extend(ov_payload)
        
        overflow_page = next_overflow
    
    # Trim to exact payload_len
    if len(full_payload) >= payload_len:
        return bytes(full_payload[:payload_len])
    
    return bytes(full_payload)

# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def parse_page_cells(page_data, page_size, expected_ncols=None,
                     data_file=None, page_num=None):
    """Parse cells from a b-tree leaf table page (type 0x0D).
    Returns list of (rowid, values).
    
    If data_file and page_num are provided, handles overflow pages.
    """
    results = []
    if len(page_data) < 8:
        return results

    page_type = page_data[0]
    if page_type != 0x0D:  # leaf table only
        return results

    n_cells = struct.unpack('>H', page_data[3:5])[0]
    content_start = struct.unpack('>H', page_data[5:7])[0]

    if n_cells > page_size // 4:  # Sanity check
        return results

    # Read cell pointers
    ptrs = []
    for i in range(n_cells):
        off = 8 + 2 * i
        if off + 2 > len(page_data):
            break
        p = struct.unpack('>H', page_data[off:off+2])[0]
        if p < content_start or p >= page_size:
            continue  # corrupted pointer
        ptrs.append(p)

    # Decode each cell
    for idx, p in enumerate(ptrs):
        try:
            # Payload length varint
            payload_len, consumed = read_varint(page_data, p)
            if payload_len <= 0:
                continue
            next_off = p + consumed

            # Row ID varint
            rowid, consumed2 = read_varint(page_data, next_off)
            rec_offset = next_off + consumed2

            # Determine cell end (for overflow detection)
            # Next cell starts at ptrs[idx+1] or content_start if this is the last
            # Actually, we need to know where this cell's data ends in the page.
            # For simplicity, estimate: the cell occupies from p to the next cell pointer
            # or to content_start if it's the last cell.
            if idx + 1 < len(ptrs):
                cell_end = ptrs[idx + 1]
            else:
                cell_end = page_size  # conservative upper bound
            
            # Check if payload fits in page
            if rec_offset + payload_len <= len(page_data):
                # No overflow
                result = decode_record(page_data, rec_offset, payload_len)
                if result:
                    results.append((rowid, result[1]))
                else:
                    fixed = try_fix_corrupted_record(
                        page_data, rec_offset, payload_len, expected_ncols)
                    if fixed:
                        results.append((rowid, fixed[1]))
            elif data_file is not None and page_num is not None:
                # Overflow: read full payload from overflow chain
                full_payload = read_full_payload(
                    data_file, page_size, page_data, rec_offset, payload_len, cell_end)
                if full_payload and len(full_payload) >= 2:
                    result = decode_record(full_payload, 0, len(full_payload))
                    if result:
                        results.append((rowid, result[1]))
                    else:
                        fixed = try_fix_corrupted_record(
                            full_payload, 0, len(full_payload), expected_ncols)
                        if fixed:
                            results.append((rowid, fixed[1]))
        except Exception:
            continue

    return results

# ---------------------------------------------------------------------------
# B-tree traversal
# ---------------------------------------------------------------------------

def collect_leaf_pages(data, page_size, root_page):
    """Walk the B-tree from root_page, collecting all leaf table page numbers.
    
    Handles:
    - Leaf pages (0x0D): added directly
    - Interior pages (0x05): recurse into children
    - Corrupted pages: skipped with warning
    - Cycle detection: visited set prevents infinite loops
    """
    leaf_pages = []
    visited = set()
    num_pages = len(data) // page_size

    def walk(page_num):
        # SQLite page numbers are 1-indexed: page 1 = offset 0
        if page_num < 1 or page_num > num_pages:
            return
        if page_num in visited:
            return
        visited.add(page_num)

        start = (page_num - 1) * page_size
        page = data[start:start + page_size]
        if len(page) < 12:
            return

        # Page 1 b-tree header is at offset 100
        hdr = 100 if page_num == 1 else 0
        if hdr >= len(page):
            return
        ptype = page[hdr]

        if ptype == 0x0D:  # Leaf table — data page
            leaf_pages.append(page_num)

        elif ptype == 0x05:  # Interior table — recurse into children
            n_cells = struct.unpack('>H', page[hdr+3:hdr+5])[0]
            if n_cells > page_size // 4:
                return  # Sanity check
            
            # Right-most child page number (4 bytes at hdr+8)
            rightmost = struct.unpack('>I', page[hdr+8:hdr+12])[0]

            # Cell pointer array starts at hdr+12
            ptr_base = hdr + 12
            for i in range(n_cells):
                cp = ptr_base + 2 * i
                if cp + 2 > len(page):
                    break
                cell_off = struct.unpack('>H', page[cp:cp+2])[0]
                if cell_off + 4 > len(page):
                    continue
                # Interior cell: [child_page:4][rowid:varint]
                child = struct.unpack('>I', page[cell_off:cell_off+4])[0]
                walk(child)

            # Don't forget the rightmost child
            walk(rightmost)

        elif ptype == 0x02:  # Interior index — not relevant for table data
            pass
        elif ptype == 0x0A:  # Leaf index — not relevant for table data
            pass
        else:
            # Corrupted or unknown page type — skip
            print(f"  Warning: page {page_num} has unknown type {ptype:#x}, skipping",
                  file=sys.stderr)

    walk(root_page)
    return leaf_pages

# ---------------------------------------------------------------------------
# Schema extraction
# ---------------------------------------------------------------------------

def extract_schema(data, page_size):
    """Extract table info from sqlite_master on page 1.
    
    Returns list of (table_name, rootpage, sql) tuples.
    """
    page1 = data[0:min(page_size, len(data))]
    hdr = 100  # B-tree header starts after 100-byte file header
    if hdr >= len(page1) or page1[hdr] not in (0x0D, 0x05):
        return []

    n_cells = struct.unpack('>H', page1[hdr+3:hdr+5])[0]
    ptrs = []
    for i in range(n_cells):
        off = hdr + 8 + 2*i
        if off + 2 > len(page1):
            break
        p = struct.unpack('>H', page1[off:off+2])[0]
        ptrs.append(p)

    schemas = []
    for p in ptrs:
        try:
            payload_len, consumed = read_varint(page1, p)
            next_off = p + consumed
            rowid, consumed2 = read_varint(page1, next_off)
            rec_offset = next_off + consumed2
            result = decode_record(page1, rec_offset, payload_len)
            if result and len(result[1]) >= 5 and result[1][0] == 'table':
                # sqlite_master columns: type, name, tbl_name, rootpage, sql
                schemas.append((result[1][1], result[1][3], result[1][4]))
            else:
                # Try corruption repair on schema record
                fixed = try_fix_corrupted_record(
                    page1, rec_offset, payload_len, expected_ncols=5)
                if fixed and len(fixed[1]) >= 5 and fixed[1][0] == 'table':
                    schemas.append((fixed[1][1], fixed[1][3], fixed[1][4]))
        except:
            continue
    return schemas

def parse_column_info(create_sql):
    """Parse column names and types from CREATE TABLE statement.
    Handles potentially truncated SQL from corrupted databases."""
    m = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?(\w+)["`\]]?\s*\((.+)',
                 create_sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    cols_str = m.group(2)
    columns = []
    for part in cols_str.split(','):
        part = part.strip().rstrip(')')
        if not part:
            continue
        if part.upper().startswith(('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT')):
            continue
        tokens = part.split()
        if tokens:
            col_name = tokens[0].strip('"[]`')
            col_type = tokens[1].upper() if len(tokens) > 1 else 'TEXT'
            # Validate type is reasonable (alphanumeric, not too long)
            if col_type.isalpha() and len(col_type) < 30:
                columns.append((col_name, col_type))
    return columns

# ---------------------------------------------------------------------------
# Raw scanning fallback
# ---------------------------------------------------------------------------

def scan_for_records(data, expected_ncols=2, known_text_pattern=None):
    """Fallback: scan raw bytes for valid record patterns."""
    records = []
    for offset in range(len(data) - 4):
        try:
            header_size = data[offset]
            if header_size < 2 or header_size > 50:
                continue

            serial_types = []
            pos = 1  # relative to record start
            valid_header = True
            while pos < header_size:
                st, consumed = read_varint(data, offset + pos)
                serial_types.append(st)
                pos += consumed
                if pos > header_size or len(serial_types) > 20:
                    valid_header = False
                    break

            if not valid_header or len(serial_types) != expected_ncols:
                continue

            total_data = sum(serial_type_size(st) for st in serial_types)
            if any(serial_type_size(st) < 0 for st in serial_types):
                continue

            total = header_size + total_data
            if offset + total > len(data):
                continue

            # Decode values
            values = []
            di = offset + header_size
            valid = True
            for st in serial_types:
                val, consumed = decode_serial_value(data, di, st)
                if val is None and st != 0:
                    valid = False
                    break
                values.append(val)
                di += consumed

            if not valid:
                continue

            # Check text pattern if provided
            if known_text_pattern:
                text_vals = [v for v in values if isinstance(v, str)]
                if text_vals and not any(known_text_pattern in v for v in text_vals):
                    continue

            records.append((offset, values))
        except:
            continue

    return records

# ---------------------------------------------------------------------------
# Main recovery
# ---------------------------------------------------------------------------

def recover(db_path):
    """Main recovery. Returns dict of {table_name: (col_names, rows)}."""
    with open(db_path, 'rb') as f:
        data = f.read()

    if len(data) < 100 or data[:16] != b'SQLite format 3\x00':
        print("Not a valid SQLite database", file=sys.stderr)
        return None

    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size == 1: page_size = 65536
    num_pages = len(data) // page_size

    # Try standard access first
    try:
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        all_data = {}
        for (tname,) in tables:
            desc = conn.execute(f"SELECT * FROM [{tname}] LIMIT 0").description
            col_names = [d[0] for d in desc]
            rows = conn.execute(f"SELECT * FROM [{tname}]").fetchall()
            all_data[tname] = (col_names, [list(r) for r in rows])
        conn.close()
        if all_data:
            print("Standard access succeeded", file=sys.stderr)
            return all_data
    except:
        print("Standard access failed, using binary recovery", file=sys.stderr)

    # Extract schema (name, rootpage, sql)
    schema_list = extract_schema(data, page_size)
    table_info = {}  # {name: (rootpage, columns)}
    for tname, rootpage, sql in schema_list:
        cols = parse_column_info(sql)
        if cols:
            table_info[tname] = (rootpage, cols)
            print(f"Schema: {tname} rootpage={rootpage} -> {cols}", file=sys.stderr)

    # If no schema found, try to infer from raw scan
    if not table_info:
        print("No schema recovered, will try raw scan fallback", file=sys.stderr)

    # For each table, traverse its B-tree to find leaf pages
    all_records = {}
    all_leaf_pages_used = set()
    
    for tname, (rootpage, cols) in table_info.items():
        expected_ncols = len(cols)
        print(f"Traversing B-tree for '{tname}' from rootpage={rootpage}...",
              file=sys.stderr)
        
        leaf_pagenums = collect_leaf_pages(data, page_size, rootpage)
        print(f"  Found {len(leaf_pagenums)} leaf pages", file=sys.stderr)
        
        table_cells = []
        for pn in leaf_pagenums:
            # pn is 1-indexed SQLite page number
            page_data = data[(pn - 1) * page_size:pn * page_size]
            cells = parse_page_cells(
                page_data, page_size, expected_ncols,
                data_file=data, page_num=pn)
            if cells:
                print(f"  Page {pn}: {len(cells)} cells", file=sys.stderr)
                table_cells.extend(cells)
            all_leaf_pages_used.add(pn)
        
        if table_cells:
            col_names = [c[0] for c in cols]
            all_records[tname] = (col_names, [r[1] for r in table_cells])

    # Fallback: if B-tree traversal found nothing, scan all leaf pages
    if not all_records:
        print("B-tree traversal found nothing, scanning all pages...", file=sys.stderr)
        
        # Collect all leaf pages (1-indexed)
        all_leaf_pages = []
        for pn in range(1, num_pages + 1):
            if pn == 1:
                continue  # Schema page
            page_data = data[(pn - 1) * page_size:pn * page_size]
            if len(page_data) >= 8 and page_data[0] == 0x0D:
                all_leaf_pages.append(pn)
        
        # Try to assign to tables by matching column count
        for tname, (rootpage, cols) in table_info.items():
            expected_ncols = len(cols)
            table_cells = []
            for pn in all_leaf_pages:
                page_data = data[(pn - 1) * page_size:pn * page_size]
                cells = parse_page_cells(
                    page_data, page_size, expected_ncols,
                    data_file=data, page_num=pn)
                if cells:
                    table_cells.extend(cells)
            if table_cells:
                col_names = [c[0] for c in cols]
                all_records[tname] = (col_names, [r[1] for r in table_cells])

    # Final fallback: raw byte scan
    if not all_records and table_info:
        print("Page scanning found nothing, trying raw byte scan...", file=sys.stderr)
        first_table = list(table_info.keys())[0]
        first_cols = table_info[first_table][1]
        expected_ncols = len(first_cols)
        
        raw_records = scan_for_records(data, expected_ncols)
        if raw_records:
            print(f"Raw scan found {len(raw_records)} records", file=sys.stderr)
            col_names = [c[0] for c in first_cols]
            all_records[first_table] = (col_names, [vals for _, vals in raw_records])

    return all_records

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_path> <output_json> [--columns col1,col2,...]",
              file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    output_path = sys.argv[2]

    # Parse optional column override
    override_cols = None
    if '--columns' in sys.argv:
        idx = sys.argv.index('--columns')
        if idx + 1 < len(sys.argv):
            override_cols = sys.argv[idx + 1].split(',')

    result = recover(db_path)
    if not result:
        print("Recovery failed", file=sys.stderr)
        sys.exit(1)

    # Serialize to JSON
    output = []
    for tname, (col_names, rows) in result.items():
        if override_cols:
            col_names = override_cols
        for row in rows:
            obj = {}
            for i, (name, val) in enumerate(zip(col_names, row)):
                if isinstance(val, bytes):
                    val = val.decode('utf-8', errors='replace')
                obj[name] = val
            output.append(obj)

    with open(output_path, 'w') as f:
        json.dump(output, f)

    print(f"Wrote {len(output)} rows to {output_path}", file=sys.stderr)

if __name__ == '__main__':
    main()
