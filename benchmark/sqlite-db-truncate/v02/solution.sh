#!/bin/bash
cat <<'PYEOF' > /tmp/solve.py
import struct
import json
import sys

def read_varint(data, pos):
    """Read a SQLite varint starting at pos, return (value, new_pos) or (None, pos)."""
    val = 0
    for i in range(9):
        if pos + i >= len(data):
            return None, pos
        b = data[pos + i]
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, pos + i + 1
    return None, pos


def decode_serial_value(data, pos, serial_type):
    """Decode a single column value, return (value, new_pos)."""
    if serial_type == 0:
        return None, pos
    elif serial_type == 1:
        v = struct.unpack('>b', data[pos:pos+1])[0]
        return v, pos + 1
    elif serial_type == 2:
        v = struct.unpack('>h', data[pos:pos+2])[0]
        return v, pos + 2
    elif serial_type == 3:
        v = struct.unpack('>i', b'\x00' + data[pos:pos+3])[0]
        return v, pos + 3
    elif serial_type == 4:
        v = struct.unpack('>i', data[pos:pos+4])[0]
        return v, pos + 4
    elif serial_type == 5:
        v = struct.unpack('>q', b'\x00\x00' + data[pos:pos+6])[0]
        return v, pos + 6
    elif serial_type == 6:
        v = struct.unpack('>q', data[pos:pos+8])[0]
        return v, pos + 8
    elif serial_type == 7:
        v = struct.unpack('>d', data[pos:pos+8])[0]
        return v, pos + 8
    elif serial_type == 8:
        return 0, pos
    elif serial_type == 9:
        return 1, pos
    elif serial_type >= 12 and serial_type % 2 == 0:
        length = (serial_type - 12) // 2
        blob = data[pos:pos+length]
        return blob, pos + length
    elif serial_type >= 13 and serial_type % 2 == 1:
        length = (serial_type - 13) // 2
        try:
            text = data[pos:pos+length].decode('ascii')
        except:
            text = data[pos:pos+length].decode('latin-1')
        return text, pos + length
    else:
        return None, pos


def decode_record_body(data, pos, serial_types):
    """Decode record body from pos using serial_types list."""
    values = []
    for st in serial_types:
        v, pos = decode_serial_value(data, pos, st)
        values.append(v)
    return values, pos


def decode_cell(data, cell_start):
    """Decode a b-tree table leaf cell. Returns (payload_len, rowid, values) or (None,None,None)."""
    # Cells are relative to the page start, so cell_start is absolute file offset
    payload_len, pos = read_varint(data, cell_start)
    if payload_len is None:
        return None, None, None
    rowid, pos = read_varint(data, pos)
    if rowid is None:
        return None, None, None

    # Record starts at pos
    record_start = pos
    header_size, pos = read_varint(data, pos)
    if header_size is None:
        return None, None, None

    header_end = record_start + header_size
    serial_types = []
    while pos < header_end:
        st, pos = read_varint(data, pos)
        if st is None:
            return None, None, None
        serial_types.append(st)

    values, pos = decode_record_body(data, pos, serial_types)
    return payload_len, rowid, values


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'

    with open(db_path, 'rb') as f:
        data = f.read()

    if len(data) < 4096:
        print("File too small", file=sys.stderr)
        sys.exit(1)

    # Database header is zeroed (first 100 bytes).
    # Page 1's b-tree page starts at offset 100.
    # Page size must be at least 512 and is typically 4096.
    # Since the header is zeroed, we cannot read page_size from bytes 16-17.
    # The file has 2 pages of 4096 bytes each.
    page_size = 4096

    # --- Parse page 1 (sqlite_master) ---
    pg1 = data[:page_size]
    # B-tree page header starts at byte 100
    pg1_tree_start = 100
    if pg1_tree_start + 8 > len(pg1):
        print("Page 1 too small", file=sys.stderr)
        sys.exit(1)

    pg1_num_cells = struct.unpack('>H', pg1[pg1_tree_start+3:pg1_tree_start+5])[0]

    # Cell pointer array
    cpa = pg1_tree_start + 8

    data_rootpage = None
    for i in range(pg1_num_cells):
        cell_offset = struct.unpack('>H', pg1[cpa + 2*i:cpa + 2*i + 2])[0]
        # Cell offset is relative to the start of page 1 (offset 0 in file)
        _, rowid, values = decode_cell(data, cell_offset)
        if values and len(values) >= 4 and values[1] == 'data' and values[2] == 'data':
            data_rootpage = values[3]

    if data_rootpage is None:
        print("Could not find data table in sqlite_master", file=sys.stderr)
        sys.exit(1)

    # --- Parse the data page ---
    data_page = data_rootpage
    data_page_start = (data_page - 1) * page_size

    if data_page_start + 8 > len(data):
        print(f"Data page {data_page} out of bounds", file=sys.stderr)
        sys.exit(1)

    pg2_num_cells = struct.unpack('>H', data[data_page_start+3:data_page_start+5])[0]
    cpa2 = data_page_start + 8

    results = []
    for i in range(pg2_num_cells):
        cell_offset = struct.unpack('>H', data[cpa2 + 2*i:cpa2 + 2*i + 2])[0]
        cell_abs = data_page_start + cell_offset
        _, rowid, values = decode_cell(data, cell_abs)
        if values and len(values) >= 2:
            word = values[0]
            value = values[1]
            if isinstance(word, str) and isinstance(value, (int, float)):
                results.append({"word": word, "value": value})

    results.sort(key=lambda r: r["word"])

    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
PYEOF

python3 /tmp/solve.py "$@"
