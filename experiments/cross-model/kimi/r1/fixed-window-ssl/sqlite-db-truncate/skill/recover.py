#!/usr/bin/env python3
"""
SQLite Database Recovery Script

Recovers rows from corrupted SQLite databases by:
1. Walking b-tree cell pointers on all pages
2. Validating payload consistency  
3. Using payload-guided fallback with distinct serial shapes
4. Signature scanning with exact-offset invariant
5. Merging, deduplicating, and validating results
"""

import struct
import json
import re
import sys
from collections import Counter


def read_varint(data, offset):
    """Read SQLite varint from data at offset. Returns (value, new_offset)."""
    v = 0
    for i in range(9):
        x = data[offset + i]
        if i == 8:
            v = (v << 8) | x
            return v, offset + i + 1
        else:
            v = (v << 7) | (x & 0x7f)
            if not (x & 0x80):
                return v, offset + i + 1
    return v, offset + 9


def serial_type_width(s):
    """Return byte width for serial type."""
    if s == 0:
        return 0
    elif 1 <= s <= 6:
        return [1, 2, 3, 4, 6, 8][s - 1]
    elif s == 7:
        return 8
    elif s in (8, 9):
        return 0
    elif s >= 12:
        return (s - 12) // 2 if s % 2 == 0 else (s - 13) // 2
    return 0


def decode_value(data, offset, serial_type):
    """Decode a single value based on serial type."""
    if serial_type == 0:
        return None, offset
    elif 1 <= serial_type <= 6:
        n = [1, 2, 3, 4, 6, 8][serial_type - 1]
        val = int.from_bytes(data[offset:offset+n], 'big', signed=True)
        return val, offset + n
    elif serial_type == 7:
        val = struct.unpack('>d', data[offset:offset+8])[0]
        return val, offset + 8
    elif serial_type == 8:
        return 0, offset
    elif serial_type == 9:
        return 1, offset
    elif serial_type >= 12:
        n = (serial_type - 12) // 2 if serial_type % 2 == 0 else (serial_type - 13) // 2
        raw = data[offset:offset+n]
        if serial_type % 2 == 0:
            return raw, offset + n
        else:
            try:
                return raw.decode('utf-8'), offset + n
            except:
                return raw.decode('utf-8', 'replace'), offset + n
    return None, offset


def try_decode_with_serials(data, header_end, serials):
    """Try to decode values using given serial types."""
    try:
        values = []
        p = header_end
        for s in serials:
            val, p = decode_value(data, p, s)
            values.append(val)
        return values
    except:
        return None


def values_match_pattern(values, pattern):
    """Check if any value matches the word pattern."""
    for v in values:
        if isinstance(v, str) and re.search(pattern, v):
            return True
    return False


def parse_record_with_fallback(data, offset, payload_len, candidate_serials=None, word_pattern=None):
    """
    Parse record with validation and payload-guided fallback.
    
    On gate failure, try each distinct sibling serial vector; accept only when 
    header_len + sum(widths) == payload_len; tiebreak by word-pattern match, 
    then modal prior.
    
    Example: v01 has INT rows (0x21, 0x01: 3+10+1=14) and FLOAT rows (0x21, 0x07: 3+10+8=21).
    If a FLOAT row's header flips to (0x21, 0x01), payload math rejects it (14 != 21)
    and accepts (0x21, 0x07) instead (21 == 21).
    """
    try:
        header_len, pos = read_varint(data, offset)
        header_end = offset + header_len
        
        # Parse serial types from header
        serials = []
        p = pos
        while p < header_end:
            s, p = read_varint(data, p)
            serials.append(s)
        
        # Calculate expected payload
        values_width = sum(serial_type_width(s) for s in serials)
        expected_payload = header_len + values_width
        is_valid = (expected_payload == payload_len)
        
        if is_valid:
            values = []
            p = header_end
            for s in serials:
                val, p = decode_value(data, p, s)
                values.append(val)
            return values, serials, True
        
        # Header corrupted - try each candidate shape
        if candidate_serials:
            survivors = []
            for candidate in candidate_serials:
                candidate_width = sum(serial_type_width(s) for s in candidate)
                if header_len + candidate_width == payload_len:
                    values = try_decode_with_serials(data, header_end, candidate)
                    if values:
                        survivors.append((values, list(candidate)))
            
            if survivors:
                # Prefer survivors whose values match the word pattern
                if word_pattern:
                    matching = [s for s in survivors if values_match_pattern(s[0], word_pattern)]
                    if matching:
                        return matching[0][0], matching[0][1], False
                # Default to first survivor (modal as tiebreaker)
                return survivors[0][0], survivors[0][1], False
        
        return None, None, False
    except Exception:
        return None, None, False


def parse_cell(data, offset, candidate_serials=None, word_pattern=None):
    """Parse a table b-tree leaf cell."""
    try:
        payload_len, pos = read_varint(data, offset)
        rowid, pos = read_varint(data, pos)
        record_start = pos
        
        values, serials, is_valid = parse_record_with_fallback(
            data, record_start, payload_len, candidate_serials, word_pattern
        )
        
        if values is None:
            return None
        
        return {
            'offset': offset,
            'rowid': rowid,
            'values': values,
            'serials': serials,
            'is_valid': is_valid,
            'payload_len': payload_len
        }
    except Exception:
        return None


def cell_walk_recovery(data, page_size, candidate_serials=None, word_pattern=None):
    """Walk all pages, parse cell pointers, recover rows."""
    results = []
    all_serials = []
    
    num_pages = len(data) // page_size
    print(f"Scanning {num_pages} pages...")
    
    for page_num in range(1, num_pages + 1):
        page_offset = (page_num - 1) * page_size
        page_type = data[page_offset]
        
        if page_type not in (0x02, 0x05, 0x0a, 0x0d):
            continue
        if page_type != 0x0d:
            continue
        
        cell_count = int.from_bytes(data[page_offset+3:page_offset+5], 'big')
        
        for i in range(cell_count):
            ptr_offset = page_offset + 8 + i * 2
            ptr = int.from_bytes(data[ptr_offset:ptr_offset+2], 'big')
            cell_offset = page_offset + ptr
            
            result = parse_cell(data, cell_offset, candidate_serials, word_pattern)
            if result:
                results.append(result)
                if result['is_valid']:
                    all_serials.append(tuple(result['serials']))
    
    # Collect DISTINCT serial vectors from valid cells
    distinct_serials = list(set(all_serials)) if all_serials else []
    if distinct_serials:
        print(f"Inferred {len(distinct_serials)} distinct serial shapes")
    
    return results, distinct_serials


def signature_scan_recovery(data, word_pattern, candidate_serials=None):
    """Signature scan with exact-offset invariant and rejection diagnostics."""
    results = []
    
    sig_bytes = word_pattern.encode()
    sig_str = word_pattern
    
    raw_matches = list(re.finditer(sig_bytes, data))
    rejected = {'parse_fail': 0, 'no_sig_in_value': 0, 'offset_mismatch': 0}
    
    for m in raw_matches:
        sig_start = m.start()
        
        for start_offset in range(max(0, sig_start - 20), sig_start):
            try:
                payload_len, pos = read_varint(data, start_offset)
                rowid, pos = read_varint(data, pos)
                record_start = pos
                
                values, serials, is_valid = parse_record_with_fallback(
                    data, record_start, payload_len, candidate_serials, word_pattern
                )
                
                if values is None:
                    rejected['parse_fail'] += 1
                    continue
                
                header_len, _ = read_varint(data, record_start)
                header_end = record_start + header_len
                exact_match = False
                
                for i, v in enumerate(values):
                    if isinstance(v, str) and re.search(sig_str, v):
                        value_offset = header_end
                        for j in range(i):
                            value_offset += serial_type_width(serials[j])
                        if value_offset == sig_start:
                            exact_match = True
                            break
                        else:
                            rejected['offset_mismatch'] += 1
                    elif isinstance(v, str):
                        rejected['no_sig_in_value'] += 1
                
                if exact_match:
                    results.append({
                        'offset': start_offset,
                        'rowid': rowid,
                        'values': values,
                        'serials': serials,
                        'is_valid': is_valid,
                        'payload_len': payload_len
                    })
                    break
            except Exception as e:
                rejected['parse_fail'] += 1
                continue
    
    print(f"Found {len(results)} cells via scan (rejected: {rejected})")
    
    if len(results) == 0 and len(raw_matches) > 0:
        print(f"WARNING: {len(raw_matches)} raw signature matches but 0 accepted")
    
    return results


def merge_results(cell_results, scan_results):
    """Merge and deduplicate by offset."""
    merged = {}
    for r in cell_results:
        merged[r['offset']] = r
    for r in scan_results:
        if r['offset'] not in merged:
            merged[r['offset']] = r
    return list(merged.values())


def recover_sqlite(db_path, output_path, word_pattern):
    """Main recovery function."""
    data = open(db_path, 'rb').read()
    
    page_size = int.from_bytes(data[16:18], 'big')
    
    # Pass 1: Collect distinct serial shapes
    print("=== Pass 1: Infer distinct serial shapes ===")
    cell_results, candidate_serials = cell_walk_recovery(data, page_size, None, word_pattern)
    print(f"Found {len(cell_results)} cells via walk")
    
    # Pass 2: Re-walk with payload-guided fallback
    if candidate_serials:
        print("\n=== Pass 2: Re-walk with payload-guided fallback ===")
        cell_results, _ = cell_walk_recovery(data, page_size, candidate_serials, word_pattern)
    
    # Signature scan
    print("\n=== Signature Scan ===")
    sig_results = signature_scan_recovery(data, word_pattern, candidate_serials)
    
    # Merge
    all_results = merge_results(cell_results, sig_results)
    print(f"\nTotal unique offsets: {len(all_results)}")
    
    # Extract records
    records = []
    for r in all_results:
        values = r['values']
        
        word_idx = None
        for i, v in enumerate(values):
            if isinstance(v, str) and re.search(word_pattern, v):
                word_idx = i
                break
        
        if word_idx is None:
            continue
        
        word = values[word_idx]
        match = re.search(word_pattern, word)
        if not match:
            continue
        word = match.group(0)
        
        value = values[word_idx + 1] if word_idx + 1 < len(values) else None
        
        records.append({'word': word, 'value': value})
    
    # Deduplicate by word
    seen = {}
    for r in records:
        if r['word'] not in seen:
            seen[r['word']] = r
    records = list(seen.values())
    
    records.sort(key=lambda x: x['word'])
    
    print(f"\nRecovered {len(records)} records")
    for r in records:
        print(f"  {r['word']} = {r['value']}")
    
    output = [{'word': r['word'], 'value': r['value']} for r in records]
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    return records


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <db_path> <output_path> [word_pattern]")
        sys.exit(1)
    
    db_path = sys.argv[1]
    output_path = sys.argv[2]
    word_pattern = sys.argv[3] if len(sys.argv) > 3 else r'testword\d{2}'
    
    recover_sqlite(db_path, output_path, word_pattern)
