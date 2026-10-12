#!/bin/bash
# Recover records from a corrupted SQLite database.
# Pages 3-6 (interior btree pages) are zeroed, but all leaf pages (7-498)
# and the root interior page (2) are intact. Each leaf page contains one
# or two records from the 'items' table (word TEXT, data TEXT).
# Rowids 1-6 (on zeroed pages) are unrecoverable.

python3 << 'PYEOF'
import struct
import json
import sys

DB_PATH = "/app/trunc.db"
OUTPUT_PATH = "/app/recover.json"
PAGE_SIZE = 4096

def read_varint(buf, pos):
    """Read a SQLite varint. Returns (value, new_position)."""
    value = 0
    remaining = len(buf) - pos
    max_read = min(9, remaining)
    for i in range(max_read):
        byte = buf[pos + i]
        value = (value << 7) | (byte & 0x7f)
        if (byte & 0x80) == 0:
            return value, pos + i + 1
    return value, pos + max_read

with open(DB_PATH, 'rb') as f:
    data = f.read()

# Parse page 2 (interior table btree, root of items table)
# Interior pages have a 12-byte header: cell pointer array starts at offset 12
page2 = data[4096:8192]  # page 2 = offset PAGE_SIZE
num_cells_page2 = struct.unpack('>H', page2[3:5])[0]
right_child = struct.unpack('>I', page2[8:12])[0]

# Collect all leaf page numbers from the interior btree cells
leaf_pages = []
for ci in range(num_cells_page2):
    cell_ptr = struct.unpack('>H', page2[12 + ci * 2:12 + ci * 2 + 2])[0]
    left_child = struct.unpack('>I', page2[cell_ptr:cell_ptr + 4])[0]
    if 7 <= left_child <= 498:
        leaf_pages.append(left_child)
if 7 <= right_child <= 498:
    leaf_pages.append(right_child)

# Deduplicate and sort
leaf_pages = sorted(set(leaf_pages))

records = []
for page_num in leaf_pages:
    offset = (page_num - 1) * PAGE_SIZE
    page = data[offset:offset + PAGE_SIZE]
    flags = page[0]
    if flags != 0x0d and flags != 0x05:
        # Skip non-leaf pages (shouldn't happen but be safe)
        continue

    num_cells = struct.unpack('>H', page[3:5])[0]
    cell_ptr_area = page[8:8 + num_cells * 2]

    for ci in range(num_cells):
        cell_ptr = struct.unpack('>H', cell_ptr_area[ci * 2:(ci + 1) * 2])[0]
        cell = page[cell_ptr:]

        # Parse cell header: payload_len (varint), rowid (varint)
        payload_len, pos = read_varint(cell, 0)
        rowid, pos = read_varint(cell, pos)
        header_sz = pos  # total cell header bytes

        # Read full payload (no overflow needed — each record fits its page)
        payload = cell[header_sz:header_sz + payload_len]

        # Parse record header within payload
        hpos = 0
        rec_hdr_size, hpos = read_varint(payload, hpos)
        if rec_hdr_size <= 0:
            continue

        serial_types = []
        while hpos < rec_hdr_size:
            st, hpos = read_varint(payload, hpos)
            serial_types.append(st)

        if len(serial_types) < 2:
            continue

        body = payload[rec_hdr_size:]
        bpos = 0

        # Column 0: word (TEXT)
        word_st = serial_types[0]
        if word_st < 13 or word_st % 2 != 1:
            continue
        word_len = (word_st - 13) // 2
        if bpos + word_len > len(body):
            continue
        word = body[bpos:bpos + word_len].decode('utf-8')
        bpos += word_len

        # Column 1: data (TEXT)
        data_st = serial_types[1]
        if data_st < 13 or data_st % 2 != 1:
            continue
        data_len = (data_st - 13) // 2
        if bpos + data_len > len(body):
            data_str = body[bpos:].decode('utf-8')
        else:
            data_str = body[bpos:bpos + data_len].decode('utf-8')

        records.append({"word": word, "data": data_str})

# Sort by the numeric suffix in word
records.sort(key=lambda r: int(r['word'].split('_')[1]))

with open(OUTPUT_PATH, 'w') as f:
    json.dump(records, f, indent=2)

print(f"Recovered {len(records)} records", file=sys.stderr)
PYEOF
