#!/usr/bin/env python3
"""
SQLite database recovery tool for corrupted databases.

Three-tier recovery architecture:
  Tier 1: Structured parsing - read b-tree headers, follow cell pointers, decode records
  Tier 2: Corruption-aware structured parsing - repair bit-flips in headers, validate
          cell counts, cross-check pointer arrays
  Tier 3: Raw content scanning - scan for recognizable patterns (text keys), reconstruct
          records from fragments without valid b-tree structure

Usage: python3 recover.py <database_path> <output_json_path> [--columns col1,col2,...]
       [--pattern REGEX]
"""

import struct
import json
import sys
import re
import os
import math
import argparse
from typing import Optional, List, Tuple, Dict, Any
from collections import Counter


# ─── SQLite constants ───────────────────────────────────────────────────────

SQLITE_HEADER_SIZE = 100
BTREE_LEAF_TABLE = 0x0D
BTREE_INTERIOR_TABLE = 0x05
BTREE_LEAF_INDEX = 0x0A
BTREE_INTERIOR_INDEX = 0x02


# ─── Varint and serial type utilities ───────────────────────────────────────

def read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    """Read a SQLite varint. Returns (value, bytes_consumed)."""
    if offset >= len(data):
        return 0, 1
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, i
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | byte
            return result, 9
    return result, 9


def serial_type_size(st: int) -> int:
    """Return byte size for a serial type, or -1 if invalid."""
    if st == 0: return 0
    elif st == 1: return 1
    elif st == 2: return 2
    elif st == 3: return 3
    elif st == 4: return 4
    elif st == 5: return 6
    elif st == 6: return 8
    elif st == 7: return 8
    elif st == 8: return 0
    elif st == 9: return 0
    elif st >= 12 and st % 2 == 0: return (st - 12) // 2
    elif st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1


def decode_value(data: bytes, offset: int, st: int) -> Tuple[Any, int]:
    """Decode a single value from data at offset given serial type."""
    if st == 0:
        return None, 0
    elif st == 1:
        return struct.unpack('>b', data[offset:offset+1])[0], 1
    elif st == 2:
        return struct.unpack('>h', data[offset:offset+2])[0], 2
    elif st == 3:
        b = data[offset:offset+3]
        return int.from_bytes(b, 'big', signed=True), 3
    elif st == 4:
        return struct.unpack('>i', data[offset:offset+4])[0], 4
    elif st == 5:
        b = data[offset:offset+6]
        return int.from_bytes(b, 'big', signed=True), 6
    elif st == 6:
        return struct.unpack('>q', data[offset:offset+8])[0], 8
    elif st == 7:
        return struct.unpack('>d', data[offset:offset+8])[0], 8
    elif st == 8:
        return 0, 0
    elif st == 9:
        return 1, 0
    elif st >= 12 and st % 2 == 0:
        blen = (st - 12) // 2
        return data[offset:offset+blen], blen
    elif st >= 13 and st % 2 == 1:
        tlen = (st - 13) // 2
        try:
            return data[offset:offset+tlen].decode('utf-8'), tlen
        except UnicodeDecodeError:
            return data[offset:offset+tlen].decode('latin-1'), tlen
    raise ValueError(f"Unknown serial type {st}")


def parse_record(payload: bytes) -> Optional[Tuple[List[int], List[Any]]]:
    """Parse a SQLite record payload. Returns (serial_types, values) or None."""
    try:
        if len(payload) < 1:
            return None
        header_len, hvi_len = read_varint(payload, 0)
        if header_len < 1 or header_len > len(payload):
            return None

        serial_types = []
        h_offset = hvi_len
        while h_offset < header_len:
            st, st_len = read_varint(payload, h_offset)
            if st_len == 0:
                return None
            serial_types.append(st)
            h_offset += st_len

        # Validate total data size fits
        d_offset = header_len
        for st in serial_types:
            sz = serial_type_size(st)
            if sz < 0:
                return None
            d_offset += sz
        if d_offset > len(payload):
            return None

        # Decode values
        d_offset = header_len
        values = []
        for st in serial_types:
            val, consumed = decode_value(payload, d_offset, st)
            values.append(val)
            d_offset += consumed

        return serial_types, values
    except Exception:
        return None


def try_single_bit_flip_repair(payload: bytes) -> Optional[Tuple[List[int], List[Any]]]:
    """Try to repair a corrupted payload by flipping single bits in the header area."""
    if len(payload) < 2:
        return None
    header_len_guess = payload[0]
    max_header_bytes = min(header_len_guess + 1, len(payload), 20)

    for byte_idx in range(max_header_bytes):
        for bit in range(8):
            fixed = bytearray(payload)
            fixed[byte_idx] ^= (1 << bit)
            result = parse_record(bytes(fixed))
            if result is not None:
                serial_types, values = result
                has_text = any(isinstance(v, str) and len(v) > 0 for v in values)
                if has_text:
                    return result
    return None


def try_multi_bit_flip_repair(payload: bytes, max_flips: int = 2) -> Optional[Tuple[List[int], List[Any]]]:
    """Try to repair a corrupted payload by flipping up to max_flips bits in the header area.
    
    This is more expensive than single-bit repair but handles severe corruption.
    Tries all 1-bit and 2-bit combinations, scores them, and returns the best.
    
    Uses heuristics to prefer repairs that produce clean, sensible values.
    """
    if len(payload) < 2 or max_flips < 1:
        return None
    
    header_len_guess = payload[0]
    max_header_bytes = min(header_len_guess + 1, len(payload), 15)  # Limit for performance
    
    best_result = None
    best_score = -1000
    
    # Try 1-bit flips
    for byte_idx in range(max_header_bytes):
        for bit in range(8):
            fixed = bytearray(payload)
            fixed[byte_idx] ^= (1 << bit)
            result = parse_record(bytes(fixed))
            if result is not None:
                serial_types, values = result
                has_text = any(isinstance(v, str) and len(v) > 0 for v in values)
                if has_text:
                    score = _score_repair(values)
                    if score > best_score:
                        best_score = score
                        best_result = result
    
    # Try 2-bit combinations
    if max_flips >= 2:
        for byte_idx1 in range(max_header_bytes):
            for bit1 in range(8):
                for byte_idx2 in range(byte_idx1, max_header_bytes):
                    start_bit2 = bit1 + 1 if byte_idx2 == byte_idx1 else 0
                    for bit2 in range(start_bit2, 8):
                        fixed = bytearray(payload)
                        fixed[byte_idx1] ^= (1 << bit1)
                        fixed[byte_idx2] ^= (1 << bit2)
                        result = parse_record(bytes(fixed))
                        if result is not None:
                            serial_types, values = result
                            has_text = any(isinstance(v, str) and len(v) > 0 for v in values)
                            if has_text:
                                score = _score_repair(values)
                                if score > best_score:
                                    best_score = score
                                    best_result = result
    
    return best_result


def _score_repair(values: List[Any]) -> int:
    """Score a repair result using heuristics. Higher is better."""
    score = 0
    
    # Prefer TEXT over BLOB
    text_count = sum(1 for v in values if isinstance(v, str))
    blob_count = sum(1 for v in values if isinstance(v, bytes))
    score += text_count * 5 - blob_count * 10
    
    # Prefer clean text (printable ASCII, no control chars except space)
    for v in values:
        if isinstance(v, str):
            # Check if text is clean
            clean_chars = sum(1 for c in v if 32 <= ord(c) < 127)
            score += clean_chars * 2
            # Heavily penalize special characters like @, control chars
            special_chars = sum(1 for c in v if ord(c) < 32 or ord(c) >= 127 or c in '@#$%^&*()[]{}|\\;:,.<>?/~`')
            score -= special_chars * 10
            # Penalize very short text values (likely wrong interpretation)
            if len(v) <= 2:
                score -= 5
    
    # Prefer reasonable numeric values
    for v in values:
        if isinstance(v, (int, float)):
            # Prefer values in reasonable ranges
            if isinstance(v, float) and not (math.isnan(v) or math.isinf(v)):
                if -1e6 < v < 1e6:
                    score += 10
            elif isinstance(v, int):
                if -1e9 < v < 1e9:
                    score += 5
    
    return score


# ─── SQLite file parsing ────────────────────────────────────────────────────

def parse_sqlite_header(data: bytes) -> Optional[Dict]:
    """Parse the 100-byte SQLite file header."""
    if len(data) < SQLITE_HEADER_SIZE:
        return None
    if data[:16] != b'SQLite format 3\x00':
        return None
    return {
        'page_size': struct.unpack('>H', data[16:18])[0],
        'write_version': data[18],
        'read_version': data[19],
        'reserved_space': data[20],
        'max_payload_frac': data[21],
        'min_payload_frac': data[22],
        'leaf_payload_frac': data[23],
        'change_counter': struct.unpack('>I', data[24:28])[0],
        'db_size_pages': struct.unpack('>I', data[28:32])[0],
        'first_freelist': struct.unpack('>I', data[32:36])[0],
        'total_freelist': struct.unpack('>I', data[36:40])[0],
        'schema_cookie': struct.unpack('>I', data[40:44])[0],
        'schema_format': struct.unpack('>I', data[44:48])[0],
    }


def parse_btree_page_header(page_data: bytes, is_first_page: bool = False) -> Optional[Dict]:
    """Parse a b-tree page header."""
    # For page 1, the b-tree header starts at offset 100 (after the SQLite file header)
    # For other pages, it starts at offset 0
    offset = 100 if is_first_page else 0
    if len(page_data) < offset + 8:
        return None

    page_type = page_data[offset]
    if page_type not in (BTREE_LEAF_TABLE, BTREE_INTERIOR_TABLE, BTREE_LEAF_INDEX, BTREE_INTERIOR_INDEX):
        return None

    result = {
        'type': page_type,
        'freeblock_offset': struct.unpack('>H', page_data[offset+1:offset+3])[0],
        'num_cells': struct.unpack('>H', page_data[offset+3:offset+5])[0],
        'cell_content_start': struct.unpack('>H', page_data[offset+5:offset+7])[0],
        'fragmented_bytes': page_data[offset+7],
    }

    if page_type in (BTREE_INTERIOR_TABLE, BTREE_INTERIOR_INDEX):
        result['rightmost_pointer'] = struct.unpack('>I', page_data[offset+8:offset+12])[0]
        ptr_start = offset + 12
    else:
        ptr_start = offset + 8

    cell_ptrs = []
    for i in range(result['num_cells']):
        p = ptr_start + i * 2
        if p + 2 > len(page_data):
            break
        cell_ptrs.append(struct.unpack('>H', page_data[p:p+2])[0])
    result['cell_ptrs'] = cell_ptrs

    return result


def try_repair_btree_header(page_data: bytes, is_first_page: bool = False) -> Optional[bytes]:
    """Try to repair a corrupted b-tree page header by flipping bits.
    
    Returns repaired page data if successful, None otherwise.
    """
    offset = 100 if is_first_page else 0
    if len(page_data) < offset + 8:
        return None
    
    # Try flipping each bit in the first 8 bytes (page header)
    for byte_idx in range(8):
        for bit in range(8):
            fixed = bytearray(page_data)
            fixed[offset + byte_idx] ^= (1 << bit)
            
            # Check if this produces a valid header
            hdr = parse_btree_page_header(bytes(fixed), is_first_page)
            if hdr is not None:
                # Additional validation: num_cells should be reasonable
                if 0 < hdr['num_cells'] < 1000:
                    # cell_content_start should be within page
                    if hdr['cell_content_start'] <= len(page_data):
                        return bytes(fixed)
    
    return None


def parse_leaf_table_cell(page_data: bytes, ptr: int) -> Optional[Tuple[int, bytes]]:
    """Parse a leaf table b-tree cell. Returns (rowid, payload) or None."""
    try:
        payload_len, vi1 = read_varint(page_data, ptr)
        if payload_len <= 0 or payload_len > len(page_data):
            return None
        rowid, vi2 = read_varint(page_data, ptr + vi1)
        payload = page_data[ptr + vi1 + vi2: ptr + vi1 + vi2 + payload_len]
        if len(payload) < payload_len:
            return None
        return rowid, payload
    except Exception:
        return None


def detect_zeroed_regions(data: bytes, page_size: int) -> List[Tuple[int, int]]:
    """Detect regions of the database that are entirely zeroed out.
    
    Returns list of (start_page, end_page) tuples for zeroed page ranges.
    A page is considered zeroed if it has >99% zeros AND no valid b-tree header.
    """
    zeroed_pages = []
    num_pages = len(data) // page_size
    
    for page_num in range(1, num_pages + 1):
        page_offset = (page_num - 1) * page_size
        page_data = data[page_offset:page_offset + page_size]
        
        # Check if page is mostly zeros (>99%)
        zero_count = page_data.count(0)
        if zero_count > page_size * 0.99:
            # Also check if there's no valid b-tree header
            is_first = (page_num == 1)
            hdr = parse_btree_page_header(page_data, is_first)
            if hdr is None:
                zeroed_pages.append(page_num)
    
    # Group consecutive pages
    if not zeroed_pages:
        return []
    
    ranges = []
    start = zeroed_pages[0]
    end = zeroed_pages[0]
    
    for page in zeroed_pages[1:]:
        if page == end + 1:
            end = page
        else:
            ranges.append((start, end))
            start = page
            end = page
    ranges.append((start, end))
    
    return ranges


def detect_truncation(data: bytes, page_size: int, expected_pages: int) -> Dict:
    """Detect if the database file is truncated.
    
    Returns dict with truncation info:
    - is_truncated: bool
    - expected_pages: int
    - actual_pages: int
    - missing_pages: int
    - truncated_portion: float (0.0 to 1.0)
    """
    actual_size = len(data)
    expected_size = page_size * expected_pages
    actual_pages = actual_size // page_size
    
    is_truncated = actual_size < expected_size
    missing_pages = max(0, expected_pages - actual_pages)
    truncated_portion = missing_pages / expected_pages if expected_pages > 0 else 0.0
    
    return {
        'is_truncated': is_truncated,
        'expected_pages': expected_pages,
        'actual_pages': actual_pages,
        'missing_pages': missing_pages,
        'truncated_portion': truncated_portion,
    }


# ─── Tier 1 & 2: Structured recovery ───────────────────────────────────────

def structured_recovery(data: bytes, page_size: int) -> List[Dict]:
    """Structured recovery through b-tree parsing with bit-flip repair fallback."""
    records = []
    num_pages = len(data) // page_size

    for page_num in range(1, num_pages + 1):
        page_offset = (page_num - 1) * page_size
        page_data = data[page_offset:page_offset + page_size]
        is_first = (page_num == 1)

        hdr = parse_btree_page_header(page_data, is_first)
        
        # If header is corrupted, try to repair it
        if hdr is None:
            repaired_page = try_repair_btree_header(page_data, is_first)
            if repaired_page is not None:
                hdr = parse_btree_page_header(repaired_page, is_first)
                if hdr is not None:
                    print(f"[INFO] Repaired corrupted b-tree header on page {page_num}")
                    page_data = repaired_page
        
        if hdr is None:
            continue
        if hdr['type'] != BTREE_LEAF_TABLE:
            continue

        for ptr in hdr['cell_ptrs']:
            cell = parse_leaf_table_cell(page_data, ptr)
            if cell is None:
                continue
            rowid, payload = cell

            # Tier 1: normal parse
            result = parse_record(payload)
            if result is not None:
                serial_types, values = result
                # Skip sqlite_master records (page 1, or records containing CREATE TABLE)
                if page_num == 1:
                    continue
                # Also skip if any value looks like SQL schema
                has_sql = any(isinstance(v, str) and 'CREATE TABLE' in v.upper() for v in values)
                if has_sql:
                    continue
                records.append({
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'values': values,
                    'page': page_num,
                })
                continue

            # Tier 2: single-bit-flip repair
            repaired = try_single_bit_flip_repair(payload)
            if repaired is not None:
                # Also try multi-bit repair to see if we can do better
                multi_repaired = try_multi_bit_flip_repair(payload, max_flips=2)
                
                # Compare scores and use the better result
                if multi_repaired is not None:
                    single_score = _score_repair(repaired[1])
                    multi_score = _score_repair(multi_repaired[1])
                    
                    if multi_score > single_score:
                        # Multi-bit repair is better
                        serial_types, values = multi_repaired
                        if page_num == 1:
                            continue
                        has_sql = any(isinstance(v, str) and 'CREATE TABLE' in v.upper() for v in values)
                        if has_sql:
                            continue
                        records.append({
                            'rowid': rowid,
                            'serial_types': serial_types,
                            'values': values,
                            'page': page_num,
                            'repaired': True,
                            'multi_bit': True,
                        })
                        continue
                
                # Single-bit repair is good enough (or multi-bit failed)
                serial_types, values = repaired
                # Skip sqlite_master records
                if page_num == 1:
                    continue
                has_sql = any(isinstance(v, str) and 'CREATE TABLE' in v.upper() for v in values)
                if has_sql:
                    continue
                records.append({
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'values': values,
                    'page': page_num,
                    'repaired': True,
                })
                continue
            
            # Tier 2b: multi-bit-flip repair (for severe corruption, when single-bit fails)
            multi_repaired = try_multi_bit_flip_repair(payload, max_flips=2)
            if multi_repaired is not None:
                serial_types, values = multi_repaired
                if page_num == 1:
                    continue
                has_sql = any(isinstance(v, str) and 'CREATE TABLE' in v.upper() for v in values)
                if has_sql:
                    continue
                records.append({
                    'rowid': rowid,
                    'serial_types': serial_types,
                    'values': values,
                    'page': page_num,
                    'repaired': True,
                    'multi_bit': True,
                })

    return records


# ─── Tier 3: Raw content scanning ──────────────────────────────────────────

def is_valid_text(text: str) -> bool:
    """Check if a text value looks like valid record data (not SQL schema or garbage)."""
    if not text:
        return False
    # Must be entirely printable ASCII (no control chars except space)
    if not all(32 <= ord(c) < 127 for c in text):
        return False
    # Filter out common SQL schema fragments
    sql_keywords = ['CREATE', 'TABLE', 'INSERT', 'SELECT', 'sqlite', 'master']
    text_upper = text.upper()
    for kw in sql_keywords:
        if kw in text_upper:
            return False
    return True


def raw_scan_recovery(data: bytes, page_size: int, text_pattern: Optional[str] = None) -> List[Dict]:
    """
    Raw content scanning: find records by scanning for recognizable text patterns
    and reconstructing record structures around them.
    
    Strategy:
    - Find all occurrences of the text pattern (or generic printable text)
    - For each hit, try multiple possible text lengths (the regex may grab extra bytes)
    - Look backwards for a valid record header with matching serial type
    - Also try single-bit-flip repair on the header if normal validation fails
    - Validate that text values are printable and not SQL schema fragments
    - Apply spatial deduplication and schema consensus filtering
    """
    candidates = []  # Collect all candidates first, then filter

    # Build search pattern
    if text_pattern:
        pattern = re.compile(text_pattern.encode('utf-8') if isinstance(text_pattern, str) else text_pattern)
    else:
        # Generic: look for any printable ASCII text of length >= 4
        pattern = re.compile(rb'[a-zA-Z_][a-zA-Z0-9_]{3,40}')

    def try_reconstruct_at(text_offset, text_len):
        """Try to reconstruct a record given a text at a specific offset and length."""
        expected_text_st = 2 * text_len + 13
        if expected_text_st > 1000:  # sanity
            return None

        # Look backwards for header
        for back in range(1, min(30, text_offset)):
            header_start = text_offset - back

            h_len, h_vi = read_varint(data, header_start)
            if h_len < 2 or h_len > 50:
                continue

            # Read serial types
            serial_types = []
            h_off = header_start + h_vi
            valid = True
            while h_off < header_start + h_len:
                st, st_vi = read_varint(data, h_off)
                if st_vi == 0 or serial_type_size(st) < 0:
                    valid = False
                    break
                serial_types.append(st)
                h_off += st_vi

            if not valid or len(serial_types) < 2:
                continue

            # Check if expected_text_st matches any serial type
            text_idx = None
            for idx, st in enumerate(serial_types):
                if st == expected_text_st:
                    text_idx = idx
                    break
            if text_idx is None:
                continue

            # Verify data offset alignment
            data_start = header_start + h_len
            col_offset = data_start
            text_data_offset = None
            for idx, st in enumerate(serial_types):
                if idx == text_idx:
                    text_data_offset = col_offset
                    break
                sz = serial_type_size(st)
                if sz < 0:
                    text_data_offset = None
                    break
                col_offset += sz

            if text_data_offset != text_offset:
                continue

            # Read all values
            col_offset = data_start
            values = []
            try:
                for st in serial_types:
                    val, consumed = decode_value(data, col_offset, st)
                    values.append(val)
                    col_offset += consumed
            except Exception:
                continue

            return serial_types, values, header_start

        return None

    def try_reconstruct_with_repair(text_offset, text_len):
        """Try reconstruction with single-bit-flip repair on the header."""
        expected_text_st = 2 * text_len + 13
        if expected_text_st > 1000:
            return None

        for back in range(1, min(30, text_offset)):
            header_start = text_offset - back

            h_len, h_vi = read_varint(data, header_start)
            if h_len < 2 or h_len > 50:
                continue

            # Try flipping each bit in the header bytes
            header_bytes = data[header_start:header_start + h_len]
            for byte_idx in range(len(header_bytes)):
                for bit in range(8):
                    fixed = bytearray(header_bytes)
                    fixed[byte_idx] ^= (1 << bit)

                    # Parse the fixed header
                    serial_types = []
                    h_off = h_vi
                    valid = True
                    try:
                        while h_off < h_len:
                            st, st_vi = read_varint(bytes(fixed), h_off)
                            if st_vi == 0 or serial_type_size(st) < 0:
                                valid = False
                                break
                            serial_types.append(st)
                            h_off += st_vi
                    except:
                        valid = False

                    if not valid or len(serial_types) < 2:
                        continue

                    # Check if expected_text_st matches
                    text_idx = None
                    for idx, st in enumerate(serial_types):
                        if st == expected_text_st:
                            text_idx = idx
                            break
                    if text_idx is None:
                        continue

                    # Verify data offset
                    data_start = header_start + h_len
                    col_offset = data_start
                    text_data_offset = None
                    for idx, st in enumerate(serial_types):
                        if idx == text_idx:
                            text_data_offset = col_offset
                            break
                        sz = serial_type_size(st)
                        if sz < 0:
                            text_data_offset = None
                            break
                        col_offset += sz

                    if text_data_offset != text_offset:
                        continue

                    # Read values using original data (not fixed) for data portion
                    col_offset = data_start
                    values = []
                    try:
                        for st in serial_types:
                            val, consumed = decode_value(data, col_offset, st)
                            values.append(val)
                            col_offset += consumed
                    except Exception:
                        continue

                    return serial_types, values, header_start

        return None

    for m in pattern.finditer(data):
        match_text = m.group(0)
        text_offset = m.start()
        match_len = len(match_text)

        # Try the match length and nearby lengths.
        # The regex may match a prefix (e.g. "testword" matches but actual text is "testword09")
        # or may grab trailing bytes (e.g. generic regex matches "testword07c" instead of "testword07")
        # Prefer SHORTER text lengths first (regex grabbing trailing bytes is more common)
        found = False
        # Build list of candidate lengths: try shorter first, then longer
        candidate_lengths = []
        # Try shorter lengths first (regex grabbed trailing bytes)
        for delta in range(-5, 1):
            tl = match_len + delta
            if tl >= 4:
                candidate_lengths.append(tl)
        # Try longer (regex matched only a prefix)
        for delta in range(1, 25):
            tl = match_len + delta
            if text_offset + tl <= len(data):
                candidate_lengths.append(tl)
            else:
                break
        
        for text_len in candidate_lengths:
            # First try normal header
            result = try_reconstruct_at(text_offset, text_len)
            if result is not None:
                serial_types, values, header_start = result
                # Validate text values
                text_values = [v for v in values if isinstance(v, str)]
                if all(is_valid_text(t) for t in text_values):
                    candidates.append({
                        'text_offset': text_offset,
                        'text_len': text_len,
                        'header_start': header_start,
                        'serial_types': serial_types,
                        'values': values,
                        'page': text_offset // page_size + 1 if page_size > 0 else 0,
                        'raw_scan': True,
                        'repaired': False,
                    })
                    found = True
                    break

            # Try with bit-flip repair
            result = try_reconstruct_with_repair(text_offset, text_len)
            if result is not None:
                serial_types, values, header_start = result
                text_values = [v for v in values if isinstance(v, str)]
                if all(is_valid_text(t) for t in text_values):
                    candidates.append({
                        'text_offset': text_offset,
                        'text_len': text_len,
                        'header_start': header_start,
                        'serial_types': serial_types,
                        'values': values,
                        'page': text_offset // page_size + 1 if page_size > 0 else 0,
                        'raw_scan': True,
                        'repaired': True,
                    })
                    found = True
                    break

    # Post-processing: spatial deduplication and schema consensus
    records = _post_process_raw_candidates(candidates)
    return records


def _post_process_raw_candidates(candidates: List[Dict]) -> List[Dict]:
    """
    Post-process raw scan candidates:
    1. Spatial deduplication: if two candidates have overlapping text regions,
       keep the one with shorter text length (or schema-consistent serial types)
    2. Schema consensus: reject candidates whose serial types don't match the majority pattern
    """
    if not candidates:
        return []

    # Sort by text_offset, then by text_len (shorter first)
    candidates.sort(key=lambda c: (c['text_offset'], c['text_len']))

    # Spatial deduplication: remove overlapping candidates
    deduped = []
    for cand in candidates:
        text_start = cand['text_offset']
        text_end = text_start + cand['text_len']
        
        # Check if this overlaps with any already-accepted candidate
        overlaps = False
        for accepted in deduped:
            acc_start = accepted['text_offset']
            acc_end = acc_start + accepted['text_len']
            # Overlap if ranges intersect
            if not (text_end <= acc_start or text_start >= acc_end):
                overlaps = True
                # Keep the shorter one (already sorted, so current is longer or equal)
                break
        
        if not overlaps:
            deduped.append(cand)

    # Schema consensus: find the most common NUMBER of columns
    # (not exact serial types, since INTEGER vs REAL may vary)
    col_counts = Counter()
    for c in deduped:
        col_counts[len(c['serial_types'])] += 1
    
    if col_counts:
        most_common_col_count = col_counts.most_common(1)[0][0]
        # Filter out candidates that don't have the consensus column count
        filtered = [c for c in deduped if len(c['serial_types']) == most_common_col_count]
        # But if filtering removes too many, keep the original deduped set
        if len(filtered) >= len(deduped) * 0.5:
            deduped = filtered

    # Remove duplicates by value tuple
    seen_keys = set()
    records = []
    for c in deduped:
        key = tuple(c['values'])
        if key not in seen_keys:
            seen_keys.add(key)
            records.append(c)

    return records


# ─── Schema inference ──────────────────────────────────────────────────────

def infer_schema(records: List[Dict]) -> Optional[List[str]]:
    """Infer column types from recovered records' serial types."""
    if not records:
        return None

    st_seqs = Counter()
    for r in records:
        st_seqs[tuple(r['serial_types'])] += 1

    most_common_st = st_seqs.most_common(1)[0][0]

    col_types = []
    for st in most_common_st:
        if st == 0:
            col_types.append('NULL')
        elif 1 <= st <= 6 or st in (8, 9):
            col_types.append('INTEGER')
        elif st == 7:
            col_types.append('REAL')
        elif st >= 12 and st % 2 == 0:
            col_types.append('BLOB')
        elif st >= 13 and st % 2 == 1:
            col_types.append('TEXT')
        else:
            col_types.append('UNKNOWN')

    return col_types


def try_read_schema_from_master(data: bytes, page_size: int) -> Optional[str]:
    """Try to read the CREATE TABLE statement from the sqlite_master page."""
    if page_size < 100:
        return None
    page1 = data[0:page_size]
    hdr = parse_btree_page_header(page1, is_first_page=True)
    if hdr is None or hdr['type'] != BTREE_LEAF_TABLE:
        return None

    for ptr in hdr['cell_ptrs']:
        cell = parse_leaf_table_cell(page1, ptr)
        if cell is None:
            continue
        rowid, payload = cell
        
        # Try normal parse first
        result = parse_record(payload)
        if result is not None:
            serial_types, values = result
            for v in values:
                if isinstance(v, str) and 'CREATE TABLE' in v.upper():
                    # Check if SQL looks complete (has closing paren)
                    if ')' in v:
                        return v
        
        # SQL is truncated or parse failed - try bit-flip repair
        # Try all single-bit flips and pick the one that produces the most complete SQL
        best_sql = None
        best_len = 0
        
        for byte_idx in range(len(payload)):
            for bit in range(8):
                fixed = bytearray(payload)
                fixed[byte_idx] ^= (1 << bit)
                
                repaired = parse_record(bytes(fixed))
                if repaired is not None:
                    _, repaired_values = repaired
                    for rv in repaired_values:
                        if isinstance(rv, str) and 'CREATE TABLE' in rv.upper():
                            # Prefer longer/more complete SQL
                            if len(rv) > best_len:
                                best_len = len(rv)
                                best_sql = rv
        
        if best_sql:
            return best_sql
    
    return None


def extract_column_names_from_sql(sql: str) -> Optional[List[str]]:
    """Extract column names from a CREATE TABLE statement."""
    import re
    # First try: match CREATE TABLE with closing paren
    match = re.search(r'CREATE\s+TABLE\s+\w+\s*\(([^)]+)\)', sql, re.IGNORECASE)
    if not match:
        # Fallback: SQL might be truncated, try without requiring closing paren
        match = re.search(r'CREATE\s+TABLE\s+\w+\s*\(([^)]+)', sql, re.IGNORECASE)
        if not match:
            return None
    
    cols_str = match.group(1)
    # Split by comma and extract column names (first word of each definition)
    cols = []
    for col_def in cols_str.split(','):
        col_def = col_def.strip()
        if col_def:
            # Column name is the first word
            col_name = col_def.split()[0]
            # Remove quotes if present
            col_name = col_name.strip('"`[]')
            cols.append(col_name)
    
    return cols if cols else None


# ─── Value formatting ──────────────────────────────────────────────────────

def format_value(v: Any) -> Any:
    """Format a value for JSON output."""
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return str(v)
        if v == int(v) and abs(v) < 2**53:
            return int(v)
        return v
    return v


# ─── Main recovery pipeline ────────────────────────────────────────────────

def recover(db_path: str, output_path: str, text_pattern: Optional[str] = None,
            column_names: Optional[List[str]] = None):
    """Main recovery function."""
    with open(db_path, 'rb') as f:
        data = f.read()

    # Parse SQLite header
    sqlite_hdr = parse_sqlite_header(data)
    if sqlite_hdr is None:
        page_size = 4096
        print(f"[WARN] SQLite header invalid, assuming page_size={page_size}")
    else:
        page_size = sqlite_hdr['page_size']
        if page_size == 1:
            page_size = 65536
        print(f"[INFO] Page size: {page_size}, DB pages: {sqlite_hdr['db_size_pages']}")

    # Detect zeroed regions
    zeroed_ranges = detect_zeroed_regions(data, page_size)
    if zeroed_ranges:
        for start, end in zeroed_ranges:
            if start == end:
                print(f"[WARN] Page {start} is zeroed out (>95% zeros)")
            else:
                print(f"[WARN] Pages {start}-{end} are zeroed out (>95% zeros)")

    # Detect truncation
    if sqlite_hdr:
        trunc_info = detect_truncation(data, page_size, sqlite_hdr['db_size_pages'])
        if trunc_info['is_truncated']:
            print(f"[WARN] Database is TRUNCATED: expected {trunc_info['expected_pages']} pages, "
                  f"found {trunc_info['actual_pages']} pages "
                  f"({trunc_info['missing_pages']} pages missing, "
                  f"{trunc_info['truncated_portion']*100:.1f}% truncated)")
            print(f"[WARN] Recovery will only process available pages")

    # Try to read schema from sqlite_master
    schema_sql = try_read_schema_from_master(data, page_size)
    if schema_sql:
        print(f"[INFO] Schema: {schema_sql}")
        # Auto-extract column names if not provided
        if column_names is None:
            extracted_cols = extract_column_names_from_sql(schema_sql)
            if extracted_cols:
                column_names = extracted_cols
                print(f"[INFO] Auto-extracted column names: {column_names}")

    # Tier 1+2: Structured recovery
    records = structured_recovery(data, page_size)
    print(f"[INFO] Tier 1+2 recovered {len(records)} records")

    # Tier 3: Raw scanning (supplement)
    raw_records = raw_scan_recovery(data, page_size, text_pattern)
    print(f"[INFO] Tier 3 raw scan found {len(raw_records)} records")

    # Merge: prefer structured records, add raw records not already found
    structured_keys = set()
    for r in records:
        key = tuple(r['values'])
        structured_keys.add(key)

    for r in raw_records:
        key = tuple(r['values'])
        if key not in structured_keys:
            records.append(r)
            structured_keys.add(key)

    print(f"[INFO] Total unique records: {len(records)}")

    # Sort by rowid if available
    records.sort(key=lambda r: (r.get('rowid') or 0))

    # Infer schema if column names not provided
    if column_names is None:
        col_types = infer_schema(records)
        if col_types:
            column_names = [f"col{i}" for i in range(len(col_types))]
            print(f"[INFO] Inferred {len(col_types)} columns with types: {col_types}")

    # Build JSON output
    output = []
    for r in records:
        values = r['values']
        if column_names and len(column_names) == len(values):
            row = {}
            for name, val in zip(column_names, values):
                row[name] = format_value(val)
            output.append(row)
        else:
            output.append([format_value(v) for v in values])

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"[INFO] Wrote {len(output)} records to {output_path}")
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SQLite database recovery tool')
    parser.add_argument('db_path', help='Path to corrupted SQLite database')
    parser.add_argument('output_path', help='Path for JSON output')
    parser.add_argument('--pattern', help='Regex pattern for text key search (Tier 3)')
    parser.add_argument('--columns', help='Comma-separated column names')
    args = parser.parse_args()

    col_names = args.columns.split(',') if args.columns else None
    recover(args.db_path, args.output_path, args.pattern, col_names)
