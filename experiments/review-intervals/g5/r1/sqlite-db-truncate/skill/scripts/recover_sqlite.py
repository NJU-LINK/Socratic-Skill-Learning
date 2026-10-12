#!/usr/bin/env python3
"""
SQLite Forensic Recovery Tool

Recover records from corrupted SQLite databases when standard queries fail.
Handles bit-flips, truncation, zeroed regions, and damaged structures.

Usage:
    python3 recover_sqlite.py <input.db> <output.json> [--schema-only]
"""

import sys
import struct
import json
import re
import math
from typing import List, Dict, Any, Optional, Tuple

# SQLite constants
SQLITE_MAGIC = b'SQLite format 3\x00'
PAGE_LEAF_TABLE = 0x0D
PAGE_INTERNAL_TABLE = 0x05
PAGE_LEAF_INDEX = 0x0A
PAGE_INTERNAL_INDEX = 0x02


class SQLiteRecovery:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with open(db_path, 'rb') as f:
            self.data = bytearray(f.read())

        self.file_size = len(self.data)
        self.page_size = 0
        self.page_count = 0
        self.tables = {}  # name -> {rootpage, sql, columns}

    def read_varint(self, buf, offset: int) -> Tuple[int, int]:
        """Read a SQLite varint. Returns (value, bytes_consumed)."""
        result = 0
        for i in range(9):
            if offset + i >= len(buf):
                return result, i + 1
            b = buf[offset + i]
            if i < 8:
                result = (result << 7) | (b & 0x7f)
                if b < 0x80:
                    return result, i + 1
            else:
                result = (result << 8) | b
                return result, i + 1
        return result, 9

    def parse_header(self) -> bool:
        """Parse the 100-byte database header."""
        if self.file_size < 100:
            print(f"Error: File too small ({self.file_size} bytes)")
            return False

        # Check/fix magic string
        if self.data[:16] != SQLITE_MAGIC:
            print("Warning: Magic string corrupted, attempting fix...")
            self.data[:16] = SQLITE_MAGIC

        # Read page size
        self.page_size = int.from_bytes(self.data[16:18], 'big')
        if self.page_size == 1:
            self.page_size = 65536

        if self.page_size < 512 or self.page_size > 65536:
            print(f"Warning: Invalid page size {self.page_size}, trying 4096")
            self.page_size = 4096

        # Read page count
        self.page_count = int.from_bytes(self.data[28:32], 'big')
        actual_pages = self.file_size // self.page_size

        if self.page_count > actual_pages:
            print(f"Warning: Header claims {self.page_count} pages but file has {actual_pages}")
            self.page_count = actual_pages

        print(f"Database: page_size={self.page_size}, page_count={self.page_count}, file_size={self.file_size}")
        return True

    def get_page(self, page_num: int) -> bytes:
        """Get page data (1-indexed)."""
        if page_num < 1 or page_num > self.page_count:
            return b''
        start = (page_num - 1) * self.page_size
        end = start + self.page_size
        if end > self.file_size:
            end = self.file_size
        return self.data[start:end]

    def parse_btree_header(self, page_data: bytes, is_page1: bool = False) -> Optional[Dict]:
        """Parse b-tree page header."""
        offset = 100 if is_page1 else 0

        if len(page_data) < offset + 8:
            return None

        ptype = page_data[offset]
        if ptype not in (PAGE_LEAF_TABLE, PAGE_INTERNAL_TABLE, PAGE_LEAF_INDEX, PAGE_INTERNAL_INDEX):
            return None

        header = {
            'type': ptype,
            'first_freeblock': int.from_bytes(page_data[offset+1:offset+3], 'big'),
            'num_cells': int.from_bytes(page_data[offset+3:offset+5], 'big'),
            'cell_content_start': int.from_bytes(page_data[offset+5:offset+7], 'big'),
            'fragmented_bytes': page_data[offset+7]
        }

        if header['type'] in (PAGE_INTERNAL_TABLE, PAGE_INTERNAL_INDEX):
            header['right_child'] = int.from_bytes(page_data[offset+8:offset+12], 'big')
            header['cell_ptr_start'] = offset + 12
        else:
            header['cell_ptr_start'] = offset + 8

        return header

    def get_cell_pointers(self, page_data: bytes, header: Dict) -> List[int]:
        """Read cell pointer array."""
        ptrs = []
        start = header['cell_ptr_start']
        for i in range(header['num_cells']):
            if start + 2 > len(page_data):
                break
            ptr = int.from_bytes(page_data[start:start+2], 'big')
            if ptr < len(page_data):
                ptrs.append(ptr)
            start += 2
        return ptrs

    def parse_cell(self, page_data: bytes, offset: int, is_table_leaf: bool) -> Optional[Dict]:
        """Parse a cell at given offset."""
        if offset >= len(page_data):
            return None

        cell = {'offset': offset}

        if is_table_leaf:
            payload_len, n1 = self.read_varint(page_data, offset)
            if payload_len <= 0 or payload_len > len(page_data):
                return None
            rowid, n2 = self.read_varint(page_data, offset + n1)
            payload_start = offset + n1 + n2

            cell['payload_len'] = payload_len
            cell['rowid'] = rowid
            cell['payload'] = page_data[payload_start:payload_start + payload_len]
        else:
            if offset + 4 > len(page_data):
                return None
            child_page = int.from_bytes(page_data[offset:offset+4], 'big')
            rowid, n = self.read_varint(page_data, offset + 4)
            cell['child_page'] = child_page
            cell['rowid'] = rowid

        return cell

    def parse_record(self, payload: bytes) -> Optional[Dict]:
        """Parse a record payload into header and body."""
        if not payload or len(payload) < 1:
            return None

        header_size, hn = self.read_varint(payload, 0)
        if header_size < 1 or header_size > len(payload):
            return None

        serial_types = []
        pos = hn
        while pos < header_size:
            st, sn = self.read_varint(payload, pos)
            serial_types.append(st)
            pos += sn

        body = payload[header_size:]

        return {
            'header_size': header_size,
            'serial_types': serial_types,
            'body': body
        }

    def serial_type_size(self, serial_type: int) -> int:
        """Return the byte size for a given serial type."""
        if serial_type == 0:
            return 0
        elif serial_type == 1:
            return 1
        elif serial_type == 2:
            return 2
        elif serial_type == 3:
            return 3
        elif serial_type == 4:
            return 4
        elif serial_type == 5:
            return 6
        elif serial_type == 6:
            return 8
        elif serial_type == 7:
            return 8
        elif serial_type == 8:
            return 0
        elif serial_type == 9:
            return 0
        elif serial_type >= 12 and serial_type % 2 == 0:
            return (serial_type - 12) // 2
        elif serial_type >= 13 and serial_type % 2 == 1:
            return (serial_type - 13) // 2
        return -1

    def decode_value(self, body: bytes, offset: int, serial_type: int) -> Tuple[Any, int]:
        """Decode a value from body based on serial type."""
        if serial_type == 0:
            return None, 0
        elif serial_type == 1:
            if offset + 1 > len(body): return None, 0
            return struct.unpack('>b', body[offset:offset+1])[0], 1
        elif serial_type == 2:
            if offset + 2 > len(body): return None, 0
            return struct.unpack('>h', body[offset:offset+2])[0], 2
        elif serial_type == 3:
            if offset + 3 > len(body): return None, 0
            return int.from_bytes(body[offset:offset+3], 'big', signed=True), 3
        elif serial_type == 4:
            if offset + 4 > len(body): return None, 0
            return struct.unpack('>i', body[offset:offset+4])[0], 4
        elif serial_type == 5:
            if offset + 6 > len(body): return None, 0
            return int.from_bytes(body[offset:offset+6], 'big', signed=True), 6
        elif serial_type == 6:
            if offset + 8 > len(body): return None, 0
            return struct.unpack('>q', body[offset:offset+8])[0], 8
        elif serial_type == 7:
            if offset + 8 > len(body): return None, 0
            return struct.unpack('>d', body[offset:offset+8])[0], 8
        elif serial_type == 8:
            return 0, 0
        elif serial_type == 9:
            return 1, 0
        elif serial_type >= 12 and serial_type % 2 == 0:
            blob_len = (serial_type - 12) // 2
            if offset + blob_len > len(body): return None, 0
            return body[offset:offset+blob_len], blob_len
        elif serial_type >= 13 and serial_type % 2 == 1:
            text_len = (serial_type - 13) // 2
            if offset + text_len > len(body): return None, 0
            try:
                return body[offset:offset+text_len].decode('utf-8'), text_len
            except:
                return body[offset:offset+text_len].decode('latin-1'), text_len
        return None, 0

    def validate_record(self, record: Dict) -> bool:
        """Check if serial types are consistent with body length."""
        total = 0
        for st in record['serial_types']:
            sz = self.serial_type_size(st)
            if sz < 0:
                return False
            total += sz
        return total == len(record['body'])

    def decode_record_values(self, record: Dict) -> List[Any]:
        """Decode all values from a parsed record."""
        values = []
        offset = 0
        body = record['body']
        for st in record['serial_types']:
            val, consumed = self.decode_value(body, offset, st)
            values.append(val)
            offset += consumed
        return values

    def _decode_numeric_at(self, data: bytes, pos: int, size: int) -> Any:
        """Decode a numeric value of given size at position."""
        chunk = data[pos:pos+size]
        if size == 1:
            return chunk[0]
        elif size == 2:
            return struct.unpack('>h', chunk)[0]
        elif size == 3:
            return int.from_bytes(chunk, 'big', signed=True)
        elif size == 4:
            return struct.unpack('>i', chunk)[0]
        elif size == 6:
            return int.from_bytes(chunk, 'big', signed=True)
        elif size == 8:
            return struct.unpack('>q', chunk)[0]
        return None

    def _is_reasonable_float(self, val: float) -> bool:
        """Check if a float value is reasonable (not garbage)."""
        if val is None:
            return False
        if math.isnan(val) or math.isinf(val):
            return False
        # Be more restrictive: typical database floats are in reasonable ranges
        # Values like 1e179 are clearly garbage from misaligned bytes
        if abs(val) > 1e9:
            return False
        if val != 0 and abs(val) < 1e-9:
            return False
        return True

    def repair_and_decode(self, body: bytes, columns: List[Dict]) -> Optional[Dict]:
        """
        Repair corrupted serial types using schema-guided backtracking.
        
        Key insight: SQLite uses dynamic typing. A REAL column may store
        values as compact integers (1-8 bytes) rather than always 8-byte floats.
        So for numeric columns, try ALL valid sizes, not just the "expected" one.
        
        Strategy: enumerate all valid (value, size) per column, then backtrack
        to find assignment that consumes exactly len(body) bytes.
        Score assignments to prefer plausible values.
        """
        n_cols = len(columns)
        body_len = len(body)

        if n_cols == 0 or body_len == 0:
            return None

        def get_options(col: Dict, pos: int, remaining: int) -> List[Tuple[Any, int, float]]:
            """
            Get possible (value, size, score) for a column at given position.
            Score: higher is better. Used to pick best assignment.
            """
            col_type = col['type'].upper()
            options = []

            # Always consider NULL as an option (0 bytes)
            # Score 0 - lower than real data but allows NULL recovery
            options.append((None, 0, 0))

            if col_type == 'TEXT':
                # Try all text lengths, longest first for better scoring
                for length in range(min(remaining, 1000), 0, -1):
                    chunk = body[pos:pos+length]
                    try:
                        text = chunk.decode('utf-8')
                        if all(c.isprintable() or c in '\n\r\t' for c in text):
                            # Score: prefer longer text, all-ASCII text
                            score = length
                            if all(0x20 <= ord(c) < 0x7f for c in text):
                                score += 100  # bonus for pure ASCII
                            
                            # Heuristic: if remaining bytes form a reasonable float,
                            # this is likely the correct text boundary
                            remaining_bytes = body[pos+length:]
                            if len(remaining_bytes) >= 8:
                                fval = struct.unpack('>d', remaining_bytes[:8])[0]
                                if self._is_reasonable_float(fval):
                                    score += 50  # bonus: boundary leads to valid float
                            
                            options.append((text, length, score))
                    except:
                        pass
            else:
                # Numeric column (INTEGER, REAL, or unknown)
                # SQLite dynamic typing: try all integer sizes
                for size in [1, 2, 3, 4, 6, 8]:
                    if remaining >= size:
                        val = self._decode_numeric_at(body, pos, size)
                        if val is not None:
                            # Score: prefer small integers (more likely compact storage)
                            score = 10 - size  # prefer smaller
                            if isinstance(val, int) and 0 <= val < 10000:
                                score += 50  # bonus for small positive int
                            # Penalize if the bytes look like printable ASCII
                            # (likely part of a text string, not a real integer)
                            chunk = body[pos:pos+size]
                            ascii_count = sum(1 for b in chunk if 0x20 <= b < 0x7f)
                            if ascii_count == size and size <= 2:
                                score -= 80  # strong penalty: all bytes are printable ASCII
                            options.append((val, size, score))
                
                # Only try IEEE-754 float for REAL columns (not INTEGER)
                if col_type == 'REAL' and remaining >= 8:
                    fval = struct.unpack('>d', body[pos:pos+8])[0]
                    if self._is_reasonable_float(fval):
                        score = 150  # high bonus for reasonable float (strong signal)
                        options.append((fval, 8, score))
                    # Even unreasonable floats get a low score as last resort
                    elif not (math.isnan(fval) or math.isinf(fval)):
                        options.append((fval, 8, -100))

            return options

        # Backtracking with scoring
        best_assignment = [None]
        best_score = [-float('inf')]

        def try_assign(col_idx: int, pos: int, assignment: List, current_score: float):
            if col_idx == n_cols:
                if pos == body_len and current_score > best_score[0]:
                    best_score[0] = current_score
                    best_assignment[0] = assignment[:]
                return

            remaining = body_len - pos
            options = get_options(columns[col_idx], pos, remaining)

            # Sort by score descending to find good solutions first
            options.sort(key=lambda x: -x[2])

            for val, size, score in options:
                # Pruning: if current score + max possible remaining can't beat best
                max_remaining_score = (n_cols - col_idx - 1) * 150  # optimistic upper bound
                if current_score + score + max_remaining_score <= best_score[0]:
                    continue

                assignment.append((col_idx, val))
                try_assign(col_idx + 1, pos + size, assignment, current_score + score)
                assignment.pop()

        try_assign(0, 0, [], 0)

        if best_assignment[0]:
            result = {}
            for col_idx, val in best_assignment[0]:
                result[columns[col_idx]['name']] = val
            return result

        return None

    def _find_text_regions(self, body: bytes) -> List[Tuple[int, int]]:
        """Find contiguous runs of printable ASCII in body."""
        regions = []
        start = None
        for i, b in enumerate(body):
            if 0x20 <= b < 0x7f:
                if start is None:
                    start = i
            else:
                if start is not None:
                    if i - start >= 2:
                        regions.append((start, i))
                    start = None
        if start is not None and len(body) - start >= 2:
            regions.append((start, len(body)))
        return regions

    def extract_schema_from_page1(self):
        """Extract table schemas from sqlite_master on page 1."""
        page1 = self.get_page(1)
        header = self.parse_btree_header(page1, is_page1=True)

        if not header or header['type'] not in (PAGE_LEAF_TABLE, PAGE_INTERNAL_TABLE):
            print("Warning: Page 1 is not a valid b-tree page")
            return

        cell_ptrs = self.get_cell_pointers(page1, header)

        for ptr in cell_ptrs:
            cell = self.parse_cell(page1, ptr, is_table_leaf=True)
            if not cell or 'payload' not in cell:
                continue

            record = self.parse_record(cell['payload'])
            if not record:
                continue

            values = self.decode_record_values(record)

            # Check if SQL is truncated
            sql_truncated = False
            if values and len(values) >= 5:
                sql = values[4]
                if isinstance(sql, str) and sql and not sql.rstrip().endswith(')'):
                    sql_truncated = True
                    print("  SQL appears truncated, extracting full SQL from raw body...")

            if not self.validate_record(record) or sql_truncated:
                if not self.validate_record(record):
                    print("  Schema record has corrupted serial types, attempting raw extraction...")
                
                if len(record['serial_types']) >= 5:
                    offset = 0
                    valid = True
                    for i in range(4):
                        st = record['serial_types'][i]
                        sz = self.serial_type_size(st)
                        if sz < 0:
                            valid = False
                            break
                        offset += sz
                    
                    if valid:
                        sql_bytes = record['body'][offset:]
                        sql_end = 0
                        while sql_end < len(sql_bytes) and sql_bytes[sql_end] >= 0x20:
                            sql_end += 1
                        sql = sql_bytes[:sql_end].decode('utf-8', errors='replace')
                        
                        if len(values) < 5:
                            values.extend([None] * (5 - len(values)))
                        values[4] = sql

            if values and len(values) >= 5:
                obj_type = values[0]
                obj_name = values[1]
                tbl_name = values[2]
                rootpage = values[3]
                sql = values[4]

                if obj_type == 'table' and sql:
                    columns = self.parse_create_table(sql)

                    if not columns:
                        columns = self._extract_columns_from_raw_sql(record['body'])
                    
                    if not columns:
                        columns = [{'name': f'col{i}', 'type': 'TEXT'} for i in range(len(record['serial_types']))]

                    self.tables[tbl_name] = {
                        'rootpage': rootpage if isinstance(rootpage, int) else 0,
                        'sql': sql,
                        'columns': columns
                    }
                    print(f"Found table: {tbl_name} (rootpage={rootpage})")
                    print(f"  SQL: {sql}")
                    print(f"  Columns: {columns}")

    def _extract_columns_from_raw_sql(self, body: bytes) -> List[Dict]:
        """Try to extract column definitions from raw SQL in body bytes."""
        m = re.search(rb'CREATE\s+TABLE\s+\w+\s*\(([^)]+)\)', body, re.IGNORECASE)
        if m:
            cols_str = m.group(1).decode('utf-8', errors='replace')
            return self._parse_column_list(cols_str)

        m = re.search(rb'CREATE\s+TABLE\s+\w+\s*\((.+)', body, re.IGNORECASE)
        if m:
            cols_str = m.group(1).decode('utf-8', errors='replace')
            cols_str = cols_str.rstrip('\x00\xff')
            return self._parse_column_list(cols_str)

        return []

    def _parse_column_list(self, cols_str: str) -> List[Dict]:
        """Parse a comma-separated column definition string."""
        columns = []
        parts = cols_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            upper = part.upper()
            if upper.startswith(('PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT')):
                continue
            col = self.parse_column_def(part)
            if col['name']:
                columns.append(col)
        return columns

    def parse_create_table(self, sql: str) -> List[Dict]:
        """Parse CREATE TABLE statement to extract column info."""
        match = re.search(r'\((.*)\)', sql, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        cols_str = match.group(1)
        return self._parse_column_list(cols_str)

    def parse_column_def(self, col_def: str) -> Dict:
        """Parse a single column definition."""
        parts = col_def.split()
        if not parts:
            return {'name': '', 'type': 'TEXT'}

        name = parts[0].strip('"`[]')
        col_type = 'TEXT'

        if len(parts) > 1:
            type_str = parts[1].upper()
            if 'INT' in type_str:
                col_type = 'INTEGER'
            elif 'REAL' in type_str or 'FLOAT' in type_str or 'DOUBLE' in type_str:
                col_type = 'REAL'
            elif 'TEXT' in type_str or 'CHAR' in type_str or 'CLOB' in type_str:
                col_type = 'TEXT'
            elif 'BLOB' in type_str:
                col_type = 'BLOB'

        return {'name': name, 'type': col_type}

    def recover_table_data(self, table_name: str) -> List[Dict]:
        """Recover all records from a table."""
        if table_name not in self.tables:
            return []

        table_info = self.tables[table_name]
        rootpage = table_info['rootpage']
        columns = table_info['columns']

        records = []
        self.traverse_btree(rootpage, columns, records)

        return records

    def traverse_btree(self, page_num: int, columns: List[Dict], records: List[Dict]):
        """Recursively traverse b-tree to collect records."""
        page_data = self.get_page(page_num)
        if not page_data:
            return

        if all(b == 0 for b in page_data):
            print(f"  Warning: Page {page_num} is all zeros, skipping")
            return

        is_page1 = (page_num == 1)
        header = self.parse_btree_header(page_data, is_page1=is_page1)

        if not header:
            print(f"  Warning: Page {page_num} has invalid b-tree header")
            return

        if header['type'] == PAGE_LEAF_TABLE:
            cell_ptrs = self.get_cell_pointers(page_data, header)

            for ptr in cell_ptrs:
                cell = self.parse_cell(page_data, ptr, is_table_leaf=True)
                if not cell or 'payload' not in cell:
                    continue

                record = self.parse_record(cell['payload'])
                if not record:
                    continue

                if self.validate_record(record) and len(record['serial_types']) == len(columns):
                    values = self.decode_record_values(record)
                    row = {}
                    for i, col in enumerate(columns):
                        row[col['name']] = values[i] if i < len(values) else None
                    row['_rowid'] = cell.get('rowid')
                    records.append(row)
                else:
                    print(f"  Cell at offset {ptr}: serial types corrupted, attempting repair...")
                    repaired = self.repair_and_decode(record['body'], columns)
                    if repaired:
                        repaired['_rowid'] = cell.get('rowid')
                        records.append(repaired)
                    else:
                        print(f"    Repair failed for cell at offset {ptr}")

        elif header['type'] == PAGE_INTERNAL_TABLE:
            if 'right_child' in header:
                self.traverse_btree(header['right_child'], columns, records)

            cell_ptrs = self.get_cell_pointers(page_data, header)
            for ptr in cell_ptrs:
                cell = self.parse_cell(page_data, ptr, is_table_leaf=False)
                if cell and 'child_page' in cell:
                    self.traverse_btree(cell['child_page'], columns, records)

    def recover_with_text_scan(self, pattern: bytes, columns: List[Dict]) -> List[Dict]:
        """Fallback: scan for text patterns and reconstruct records."""
        records = []

        for match in re.finditer(pattern, self.data):
            text = match.group().decode('ascii', errors='replace')
            text_start = match.start()

            for hdr_offset in range(2, 10):
                pos = text_start - hdr_offset
                if pos < 0:
                    continue

                hdr_size = self.data[pos]
                if hdr_size == hdr_offset and hdr_size <= 20:
                    serial_types = []
                    p = pos + 1
                    while p < pos + hdr_size:
                        st, sn = self.read_varint(self.data, p)
                        serial_types.append(st)
                        p += sn

                    if len(serial_types) != len(columns):
                        continue

                    body_start = text_start
                    values = []
                    offset = 0

                    for i, (st, col) in enumerate(zip(serial_types, columns)):
                        if col['type'] == 'TEXT' and i == 0:
                            values.append(text)
                            offset = len(text)
                        else:
                            val, consumed = self.decode_value(self.data, body_start + offset, st)
                            if val is not None:
                                values.append(val)
                                offset += consumed
                            else:
                                break

                    if len(values) == len(columns):
                        row = {}
                        for i, col in enumerate(columns):
                            row[col['name']] = values[i]
                        records.append(row)
                    break

        return records

    def recover_all(self) -> Dict[str, List[Dict]]:
        """Main recovery entry point."""
        print(f"\n{'='*60}")
        print(f"SQLite Forensic Recovery")
        print(f"{'='*60}")
        print(f"File: {self.db_path}")
        print(f"Size: {self.file_size} bytes")

        if not self.parse_header():
            return {}

        print(f"\nExtracting schema...")
        self.extract_schema_from_page1()

        if not self.tables:
            print("Warning: No tables found in schema")
            return {}

        results = {}
        for table_name in self.tables:
            print(f"\nRecovering table: {table_name}")
            records = self.recover_table_data(table_name)

            if not records:
                print(f"  Standard recovery produced 0 records, trying text scan fallback...")
                columns = self.tables[table_name]['columns']
                records = self.recover_with_text_scan(rb'[\x20-\x7e]{4,}', columns)

            print(f"  Recovered {len(records)} records")
            results[table_name] = records

        return results


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 recover_sqlite.py <input.db> <output.json> [--schema-only]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    schema_only = '--schema-only' in sys.argv

    recovery = SQLiteRecovery(input_path)
    results = recovery.recover_all()

    if schema_only:
        print("\nSchema only mode - not writing records")
        return

    if len(results) == 1:
        table_name = list(results.keys())[0]
        output = results[table_name]
    else:
        output = results

    # Strip internal _rowid field
    if isinstance(output, list):
        for record in output:
            if isinstance(record, dict) and '_rowid' in record:
                del record['_rowid']
    elif isinstance(output, dict):
        for table_records in output.values():
            if isinstance(table_records, list):
                for record in table_records:
                    if isinstance(record, dict) and '_rowid' in record:
                        del record['_rowid']

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nWrote {output_path}")


if __name__ == '__main__':
    main()
