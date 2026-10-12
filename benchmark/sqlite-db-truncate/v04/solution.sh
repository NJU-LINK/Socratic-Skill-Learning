#!/bin/bash

cat <<'PYEOF' > /tmp/solve.py
#!/usr/bin/env python3
import json
import re

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

def text_len_from_serial(ser):
    if ser >= 13 and (ser & 1):
        return (ser - 13) // 2
    return 0

def recover_text_records(db_path):
    with open(db_path, 'rb') as f:
        data = f.read()

    results = []
    seen = set()

    pattern = b"testword"
    offset = 0
    while True:
        pos = data.find(pattern, offset)
        if pos == -1:
            break

        header_start = pos - 5
        if header_start < 0:
            offset = pos + 1
            continue

        payload_len, after_pl = read_varint(data, header_start)
        rowid, after_rowid = read_varint(data, after_pl)
        header_size, after_hs = read_varint(data, after_rowid)

        if any(v is None for v in [payload_len, rowid, header_size]):
            offset = pos + 1
            continue

        if header_size < 2:
            offset = pos + 1
            continue

        ser0, ser0_end = read_varint(data, after_hs)
        ser1, ser1_end = read_varint(data, ser0_end)

        if ser0 is None or ser1 is None:
            offset = pos + 1
            continue

        word_len = text_len_from_serial(ser0)
        status_len = text_len_from_serial(ser1)

        if word_len <= 0 or status_len <= 0:
            offset = pos + 1
            continue

        data_start = after_rowid + payload_len - (word_len + status_len)
        if data_start < 0 or data_start + word_len + status_len > len(data):
            offset = pos + 1
            continue

        word_bytes = data[data_start:data_start + word_len]
        try:
            word = word_bytes.decode('ascii')
        except:
            offset = pos + 1
            continue

        if not re.match(r'^testword\d{2}$', word):
            offset = pos + 1
            continue

        status_bytes = data[data_start + word_len:data_start + word_len + status_len]
        try:
            status = status_bytes.decode('ascii')
        except:
            offset = pos + 1
            continue

        status = status.rstrip('\x00')

        if word not in seen:
            results.append({"word": word, "status": status})
            seen.add(word)

        offset = pos + 1

    results.sort(key=lambda r: r["word"])
    return results

def main():
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/trunc.db'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/app/recover.json'
    results = recover_text_records(db_path)

    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
PYEOF

DB_PATH="${1:-/app/trunc.db}"
OUT_PATH="${2:-/app/recover.json}"
python3 /tmp/solve.py "$DB_PATH" "$OUT_PATH"
