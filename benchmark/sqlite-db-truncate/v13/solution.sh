#!/bin/bash
cat <<'PYEOF' > /tmp/solve.py
#!/usr/bin/env python3
import struct, json, sys

def read_varint(data, pos):
    val = 0
    for i in range(9):
        if pos + i >= len(data):
            return None, pos
        b = data[pos + i]
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, pos + i + 1
    return None, pos

TYPE_SIZES = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8, 7: 8, 8: 0, 9: 0}

def decode_column(data, pos, serial_type):
    if serial_type in TYPE_SIZES:
        size = TYPE_SIZES[serial_type]
        if pos + size > len(data):
            return None, pos
        val_bytes = data[pos:pos + size]
        pos += size
        if serial_type == 0:
            return None, pos
        elif serial_type == 7:
            return struct.unpack('>d', val_bytes)[0], pos
        elif serial_type in (1, 2, 3, 4, 5, 6):
            return int.from_bytes(val_bytes, 'big', signed=True), pos
        elif serial_type == 8:
            return 0, pos
        elif serial_type == 9:
            return 1, pos
    elif serial_type >= 12:
        if serial_type % 2 == 0:
            size = (serial_type - 12) // 2
        else:
            size = (serial_type - 13) // 2
        if pos + size > len(data):
            return None, pos
        val = data[pos:pos + size]
        pos += size
        return val, pos
    return None, pos

def recover_from_truncated(db_path):
    with open(db_path, 'rb') as f:
        data = f.read()

    if len(data) < 100:
        return []

    page_size = struct.unpack('>H', data[16:18])[0]
    if page_size < 512 or page_size > 65536:
        return []

    # Page 1 is the leaf table b-tree page
    if len(data) <= page_size:
        return []

    pg = data[page_size:page_size + page_size]
    if len(pg) < 8:
        return []

    pg_type = pg[0]
    if pg_type not in (0x0D, 0x05):
        return []

    cell_count = struct.unpack('>H', pg[3:5])[0]
    if cell_count < 1 or cell_count > 1000:
        return []

    cell_pointers = []
    for i in range(cell_count):
        if 8 + i * 2 + 2 > len(pg):
            break
        cp = struct.unpack('>H', pg[8 + i * 2:10 + i * 2])[0]
        cell_pointers.append(cp)

    results = []

    for cp in cell_pointers:
        if cp >= len(pg):
            continue

        cell = pg[cp:]
        payload_len, pos = read_varint(cell, 0)
        if payload_len is None:
            continue
        rowid, pos = read_varint(cell, pos)
        if rowid is None:
            continue

        rec_start = pos
        header_size, pos = read_varint(cell, pos)
        if header_size is None or header_size < 1:
            continue

        # header_size includes itself; body starts at rec_start + header_size
        body_start = rec_start + header_size
        if body_start > len(cell):
            continue

        # Read serial types from header
        serial_types = []
        sp = pos
        while sp < body_start:
            st, sp = read_varint(cell, sp)
            if st is None:
                break
            serial_types.append(st)

        # Decode columns
        columns = []
        cp_pos = body_start
        ok = True
        for st in serial_types:
            val, cp_pos = decode_column(cell, cp_pos, st)
            if cp_pos > len(cell):
                ok = False
                break
            columns.append(val)

        if ok and len(columns) >= 2:
            results.append({
                "id": columns[0],
                "value": columns[1],
            })

    return results

def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'

    results = recover_from_truncated(db_path)

    # If no records found via page parsing, try scanning the raw binary
    if not results:
        with open(db_path, 'rb') as f:
            data = f.read()
        # Scan for varint-payload_length + varint-rowid + record patterns
        offset = 0
        seen = set()
        while offset < len(data) - 20:
            # Look for records with the known structure: 
            # payload_len=12 (0x0c), rowid=1-255, header_size=3 (0x03)
            if offset + 20 > len(data):
                break
            if data[offset] != 0x0c:
                offset += 1
                continue
            pl, p = read_varint(data, offset)
            if pl != 12:
                offset += 1
                continue
            rid, p = read_varint(data, p)
            if rid is None or rid < 1 or rid > 1000:
                offset += 1
                continue
            hs, p2 = read_varint(data, p)
            if hs != 3:
                offset += 1
                continue

            try:
                st1, p2 = read_varint(data, p2)
                st2, p2 = read_varint(data, p2)
                if st1 is None or st2 is None:
                    offset += 1
                    continue
                body = data[p2:p2 + 14]
                col1, p3 = decode_column(data, p2, st1)
                col2, p3 = decode_column(data, p3, st2)
                if col1 is not None and col2 is not None:
                    key = (col1, col2)
                    if key not in seen:
                        results.append({"id": col1, "value": col2})
                        seen.add(key)
            except:
                pass
            offset += 1

    # Sort by id
    results.sort(key=lambda r: r["id"])

    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
PYEOF

python3 /tmp/solve.py "$@"
