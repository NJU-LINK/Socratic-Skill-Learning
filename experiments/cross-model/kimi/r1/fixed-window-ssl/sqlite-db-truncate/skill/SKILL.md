---
name: sqlite-db-truncate
description: Recover rows from corrupted SQLite databases by parsing raw page structures, handling varints, serial types, and validation with fallback strategies for damaged headers.
---

# SQLite Database Recovery Skill

## ⚡ QUICK START (USE THIS FIRST)

**A tested reference implementation is bundled with this skill as `recover.py`.**

The skill directory is NOT directly accessible in the task container. You must READ the file using the read tool, then deploy it to /app:

```bash
# Step 1: Read recover.py from the skill package, then write to /app via heredoc
# (Using task_shell - write tool may have workspace boundaries)
task_shell: cat > /app/recover.py << 'EOF'
[paste the full recover.py content from read tool]
EOF

# Alternative if your environment allows direct write:
# write('/app/recover.py', content)

# Step 2: Run it with the pattern from the task instruction
python3 /app/recover.py /app/trunc.db /app/recover.json 'testword\d{2}'
# Pattern comes from the instruction's example output (e.g., "testwordXY")

# Step 3: Verify the output
cat /app/recover.json
```

**Only hand-roll a custom parser when the script's diagnostics show it can't cope** (e.g., damaged cell pointers that signature scan can't find, multi-table schemas requiring DDL parsing, overflow pages, or truncation artifacts).

The script automatically:
- Parses all table leaf pages (0x0d)
- Validates payload consistency
- Collects distinct serial shapes from valid records for payload-guided fallback
- Recovers corrupted headers via fallback
- Validates output against the pattern

---

## Overview

This skill covers recovery of logically valid rows from corrupted SQLite databases when standard queries fail. The approach combines:
- Raw page/record-header analysis
- Proper varint and serial-type decoding
- B-tree cell-pointer walking
- **Payload validation with fallback for damaged headers**
- **Value-shape validation against expected patterns**
- Cross-check diagnostics

## SQLite File Format Essentials

### Database Header (first 100 bytes)
| Offset | Size | Field |
|--------|------|-------|
| 0-15 | 16 | Magic string `"SQLite format 3\x00"` |
| 16-17 | 2 | Page size (big-endian), e.g., `0x1000` = 4096 |
| 20 | 1 | Reserved bytes at end of each page |
| 28-31 | 4 | Database size in pages |
| 56-59 | 4 | Text encoding (1=UTF-8, 2=UTF-16le, 3=UTF-16be) |

**Truncation detection**: If `header_page_count × page_size > actual_file_size`, the file is truncated. Adjust expectations and treat the final partial page as fragments.

### B-Tree Page Structure

**Page header** (offset from page start):
- Byte 0: Page type (`0x02`=index interior, `0x05`=table interior, `0x0a`=index leaf, `0x0d`=table leaf)
- Bytes 1-2: First freeblock offset (0 if none)
- Bytes 3-4: Number of cells (big-endian)
- Bytes 5-6: Cell content start offset (from page start)
- Byte 7: Fragmented free bytes
- Interior pages (0x02, 0x05): 12-byte header, cells are `(4-byte child page | varint rowid)`
- Leaf pages (0x0a, 0x0d): 8-byte header, cells start at byte 8

Cell content grows downward from the end of the page.

### Cell Structure (Table B-Tree Leaf)
```
payload-length(varint) | rowid(varint) | record
```

**INTEGER PRIMARY KEY alias**: When a column is declared `INTEGER PRIMARY KEY`, it becomes an alias for the rowid. In the record, this column is stored as NULL (serial type 0), and the actual value comes from the cell's rowid field. Reconstruct by using rowid when serial type is 0 and the DDL indicates PRIMARY KEY.

### Record Format
```
header-length(varint) | serial-type(varints)... | values...
```

## Varint Encoding

SQLite uses a big-endian varint format (up to 9 bytes):
- Bytes 1-8: High bit set = continuation, 7 data bits
- Byte 9: All 8 bits used (no continuation bit)

```python
def read_varint(data, offset):
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
```

## Serial Type Decoding

| Serial Type | Meaning | Byte Width |
|-------------|---------|------------|
| 0 | NULL | 0 |
| 1-6 | Signed integer | 1,2,3,4,6,8 bytes respectively |
| 7 | IEEE-754 float64 | 8 bytes |
| 8 | Integer 0 | 0 bytes (literal) |
| 9 | Integer 1 | 0 bytes (literal) |
| ≥12, even (2k) | BLOB | (k-12)/2 bytes |
| ≥13, odd (2k+1) | TEXT | (k-13)/2 bytes |

```python
def serial_type_width(s):
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
```

## Value Decoding

Values are big-endian. Floats use `>d` format:

```python
import struct

def decode_value(data, offset, serial_type):
    if serial_type == 0:
        return None, offset
    elif 1 <= serial_type <= 6:
        n = [1, 2, 3, 4, 6, 8][serial_type - 1]
        val = int.from_bytes(data[offset:offset+n], 'big', signed=True)
        return val, offset + n
    elif serial_type == 7:
        val = struct.unpack('>d', data[offset:offset+8])[0]  # CRITICAL: big-endian
        return val, offset + 8
    elif serial_type == 8:
        return 0, offset
    elif serial_type == 9:
        return 1, offset
    elif serial_type >= 12:
        n = (serial_type - 12) // 2 if serial_type % 2 == 0 else (serial_type - 13) // 2
        raw = data[offset:offset+n]
        if serial_type % 2 == 0:
            return raw, offset + n  # BLOB
        else:
            return raw.decode('utf-8', 'replace'), offset + n
```

## Recovery Strategy

### Step 1: Parse Page Header

```python
def parse_page_header(data, page_offset):
    page_type = data[page_offset]
    if page_type not in (0x02, 0x05, 0x0a, 0x0d):
        return None  # Damaged/zeroed page
    
    cell_count = int.from_bytes(data[page_offset+3:page_offset+5], 'big')
    content_start = int.from_bytes(data[page_offset+5:page_offset+7], 'big')
    
    header_size = 12 if page_type in (0x02, 0x05) else 8
    pointers = []
    for i in range(cell_count):
        ptr_off = page_offset + header_size + i * 2
        ptr = int.from_bytes(data[ptr_off:ptr_off+2], 'big')
        pointers.append(page_offset + ptr)
    
    return page_type, cell_count, pointers
```

### Step 2: Parse Cell with Payload Validation (CRITICAL)

**The payload-consistency gate is mandatory** - never emit a record without validating:

```python
def parse_cell(data, offset, expected_shape=None):
    """
    Parse a cell with validation. expected_shape = list of serial types
    from DDL or sibling records (e.g., [0x21, 0x01] for TEXT(10)+INT).
    """
    try:
        payload_len, pos = read_varint(data, offset)
        rowid, pos = read_varint(data, pos)
        record_start = pos
        
        header_len, pos = read_varint(data, pos)
        header_end = record_start + header_len
        
        # Parse serial types from header
        serials = []
        p = pos
        while p < header_end:
            s, p = read_varint(data, p)
            serials.append(s)
        
        # PAYLOAD VALIDATION GATE
        values_width = sum(serial_type_width(s) for s in serials)
        expected_payload = header_len + values_width
        
        if expected_payload != payload_len:
            # Header corrupted - use fallback with expected shape
            if expected_shape:
                values = []
                q = header_end
                for s in expected_shape:
                    val, q = decode_value(data, q, s)
                    values.append(val)
                return {'rowid': rowid, 'values': values, 'recovered': True}
            return None
        
        # Normal parsing
        values = []
        p = header_end
        for s in serials:
            val, p = decode_value(data, p, s)
            values.append(val)
        
        return {'rowid': rowid, 'values': values, 'valid': True}
    except Exception:
        return None
```

### Step 3: Value-Shape Validation (CRITICAL)

**Never emit values without validating against expected patterns**:

```python
def validate_record(record, word_pattern=r'testword\d{2}'):
    """
    Validate recovered record matches expected shape.
    Pattern derived from task instruction or DDL.
    """
    if not record or 'values' not in record:
        return False
    
    values = record['values']
    if len(values) < 2:
        return False
    
    word = values[0]
    if not isinstance(word, str):
        return False
    
    # Strip trailing garbage (NUL, newline, etc. from corruption)
    match = re.search(word_pattern, word)
    if not match:
        return False
    
    record['values'][0] = match.group(0)
    return True
```

### Step 4: Overflow Page Handling

When payload exceeds what fits locally:

```python
def gather_payload(data, cell_offset, payload_len, page_size, reserved=0):
    """Gather payload, following overflow chain if needed."""
    U = page_size - reserved
    max_local = U - 35
    min_local = ((U - 12) * 32) // 255 - 23
    
    if payload_len <= max_local:
        return data[cell_offset:cell_offset+payload_len]
    
    # Overflow case
    local = min_local + (payload_len - min_local) % (U - 4)
    if local > max_local:
        local = min_local
    
    payload = bytearray(data[cell_offset:cell_offset+local])
    overflow_page = int.from_bytes(
        data[cell_offset+local:cell_offset+local+4], 'big'
    )
    
    while overflow_page and len(payload) < payload_len:
        page_off = (overflow_page - 1) * page_size
        if page_off >= len(data):
            break
        
        next_page = int.from_bytes(data[page_off:page_off+4], 'big')
        chunk_size = min(U - 4, payload_len - len(payload))
        payload += data[page_off+4:page_off+4+chunk_size]
        overflow_page = next_page
    
    return bytes(payload[:payload_len])
```

### Step 5: Cross-Validation and Diagnostics

**Always cross-check - disagreement reveals tool limitations, not absence of data**:

```python
def diagnose_recovery(db_path, parsed_count):
    """
    Run sqlite3 .recover and diagnose any disagreement.
    .recover failing indicates its dependency on intact structures,
    NOT that no data exists.
    """
    import subprocess
    result = subprocess.run(
        ['sqlite3', db_path, '.recover'],
        capture_output=True, text=True
    )
    
    # Count CREATE TABLE vs INSERT statements in output
    creates = result.stdout.count('CREATE TABLE')
    inserts = result.stdout.count('INSERT')
    
    if inserts == 0 and parsed_count > 0:
        print(f"DIAGNOSIS: sqlite3 .recover found {inserts} rows")
        print(f"  but direct parsing found {parsed_count}")
        print(f"  -> Page 1 (sqlite_master) likely corrupted;")
        print(f"     .recover cannot read table definitions;")
        print(f"     direct parsing succeeds on data pages.")
    
    return inserts
```

## Complete Recovery Script Template

```python
import struct
import json
import re

def recover_sqlite(db_path, output_path, word_pattern=r'testword\d{2}', expected_serials=None):
    """
    Recover rows from corrupted SQLite database.
    
    Args:
        db_path: Path to corrupted database
        output_path: Path for output JSON
        word_pattern: Regex for valid word values (from task instruction)
        expected_serials: Fallback serial types [text_serial, int_serial]
                         (e.g., [0x21, 0x01] for TEXT(10)+INT)
    """
    data = open(db_path, 'rb').read()
    
    # Read header
    page_size = int.from_bytes(data[16:18], 'big')
    reserved = data[20]
    num_pages = int.from_bytes(data[28:32], 'big')
    
    print(f"File: {len(data)} bytes, page_size={page_size}")
    print(f"Expected pages: {num_pages}, actual: {len(data)//page_size}")
    
    # Detect truncation
    expected_size = num_pages * page_size
    if len(data) < expected_size:
        print(f"WARNING: Truncated (expected {expected_size})")
    
    results = []
    
    # Scan all pages
    for page_num in range(2, len(data) // page_size + 1):  # Skip page 1 (schema)
        page_offset = (page_num - 1) * page_size
        page_type = data[page_offset]
        
        if page_type != 0x0d:  # Only table leaf pages
            continue
        
        cell_count = int.from_bytes(data[page_offset+3:page_offset+5], 'big')
        
        for i in range(cell_count):
            ptr_off = page_offset + 8 + i * 2
            cell_off = page_offset + int.from_bytes(
                data[ptr_off:ptr_off+2], 'big'
            )
            
            result = parse_cell(data, cell_off, expected_serials)
            if result and validate_record(result, word_pattern):
                results.append(result)
    
    # Sort and output
    results.sort(key=lambda x: x['rowid'])
    output = [{'word': r['values'][0], 'value': r['values'][1]} for r in results]
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Cross-check
    diagnose_recovery(db_path, len(results))
    
    return output
```

## Deriving Expected Shape from Context

**Never hardcode schema-specific values in the skill** - derive at runtime:

### From Task Instruction
```python
# Extract pattern from instruction example
def extract_pattern(instruction_text):
    # "testwordXY" pattern
    match = re.search(r'"(\w+)\d+"', instruction_text)
    if match:
        prefix = match.group(1)
        return re.compile(prefix + r'\d+')
    return None
```

### From DDL in sqlite_master (Page 1)
```python
def parse_sqlite_master(data, page_size):
    """
    Parse page 1 to extract table DDL.
    Page 1 header starts at offset 100 (after file header).
    """
    page_offset = 0
    header_start = 100  # After 100-byte file header
    
    page_type = data[header_start]
    cell_count = int.from_bytes(data[header_start+3:header_start+5], 'big')
    
    tables = {}
    for i in range(cell_count):
        ptr_off = header_start + 8 + i * 2
        cell_off = header_start + int.from_bytes(
            data[ptr_off:ptr_off+2], 'big'
        )
        
        # Parse sqlite_master row: (type, name, tbl_name, rootpage, sql)
        result = parse_cell(data, cell_off)
        if result and len(result['values']) >= 5:
            row_type, name, tbl_name, rootpage, sql = result['values'][:5]
            if row_type == 'table':
                tables[name] = {
                    'rootpage': rootpage,
                    'sql': sql,
                    'columns': parse_ddl_columns(sql)
                }
    
    return tables

def parse_ddl_columns(sql):
    """Extract column names and types from CREATE TABLE statement."""
    match = re.search(r'\((.+)\)', sql, re.DOTALL)
    if not match:
        return []
    
    cols = []
    for col_def in match.group(1).split(','):
        parts = col_def.strip().split()
        if parts:
            cols.append({
                'name': parts[0],
                'type': parts[1].upper() if len(parts) > 1 else 'TEXT'
            })
    return cols
```

### Infer Serial Types from DDL
```python
def ddl_to_serial_types(columns):
    """Map column types to expected serial types."""
    serials = []
    for col in columns:
        t = col['type']
        if 'INT' in t:
            serials.append(0x01)  # 1-byte int (or larger if needed)
        elif 'REAL' in t or 'FLOA' in t or 'DOUB' in t:
            serials.append(0x07)  # float64
        elif 'TEXT' in t:
            # Need to know width - use signature scan to estimate
            serials.append('TEXT')
        else:
            serials.append(None)
    return serials
```

## Validation Checklist

- [ ] Header offsets correct (page size at 16, encoding at 56)
- [ ] Truncation detected and reported
- [ ] Page type validated (valid: 0x02, 0x05, 0x0a, 0x0d)
- [ ] Cell pointers correctly resolved (add page offset)
- [ ] Varint decoding handles continuation bits
- [ ] **Payload validation: header_len + sum(widths) == payload_len**
- [ ] **Fallback activated on validation failure**
- [ ] **Value-shape validation against expected pattern**
- [ ] Float values use `>d` (big-endian) unpacking
- [ ] Overflow pages followed for large payloads
- [ ] Cross-check with `.recover` and diagnose disagreements
- [ ] Output JSON matches required schema

## Three-Bucket Recovery Reporting

When analyzing recovery quality, categorize rows into three buckets:

### 1. Clean Recovery (valid header)
- Payload validation passed
- Header consistent with payload length
- Serial types decoded normally

### 2. Repaired Recovery (invalid header, fixed via fallback)
- Payload validation failed
- Recovered by trying each distinct serial shape; accept only when header_len + sum(serial_widths) == payload_len (payload math selects correct shape)
- Value recovered correctly despite header corruption

**Canonical Example (v01)**: Table has INT rows with serials (0x21, 0x01) and FLOAT rows with (0x21, 0x07). Header is 3 bytes.
- INT row: 3 + 10 + 1 = 14 bytes payload
- FLOAT row: 3 + 10 + 8 = 21 bytes payload

If a FLOAT row's second serial flips from 0x07 to 0x01:
- Decoded serials (0x21, 0x01) give expected payload 14, but actual payload is 21 → validation fails
- Fallback tries (0x21, 0x01): 3+10+1 = 14 ≠ 21 → rejected
- Fallback tries (0x21, 0x07): 3+10+8 = 21 == 21 → accepted, FLOAT correctly decoded

### 3. Lost to Corruption
- Record physically destroyed (overlaps with flipped bytes)
- Unable to recover even with fallback
- Counted as legitimate loss

**Recovery Quality Formula**: `(clean + repaired) / (clean + repaired + lost)`

Do NOT compare against "rows that existed" — some rows may be physically destroyed. Compare against "rows not physically destroyed."

### Attribution Rules
- Flip in header (serials) → Repaired (via payload-guided shape selection)
- Flip in value → Lost (value genuinely corrupted)
- Flip in page pointer → Caught by signature scan (if cell lost)

## Signature Scan Exact-Offset Invariant

When using signature scanning (pattern matching raw bytes to find records with corrupted pointers), a **pattern match inside decoded values is necessary but not sufficient**. False positives occur when:
- A text fragment from an unrelated location happens to match the pattern
- Step-back parsing lands in the middle of a record
- The match offset doesn't align with the record structure

**The Exact-Offset Rule**: Accept a candidate record start only if:
1. Decoding the record lands the **signature column's first byte exactly on the match offset** (within the file)
2. The **payload math closes** (`header_len + sum(serial_widths) == payload_len`)

```python
def signature_scan_exact_offset(data, sig_pattern, candidate_serials=None):
    for m in re.finditer(sig_pattern, data):
        sig_start = m.start()
        for start_offset in range(max(0, sig_start - 20), sig_start):
            try:
                payload_len, pos = read_varint(data, start_offset)
                rowid, pos = read_varint(data, pos)
                record_start = pos
                
                # Parse and validate
                values, serials, is_valid = parse_record_with_fallback(
                    data, record_start, payload_len, candidate_serials
                )
                if values is None:
                    continue
                
                # EXACT-OFFSET CHECK: Find which value contains the signature
                # and verify it starts exactly at sig_start
                header_len, _ = read_varint(data, record_start)
                header_end = record_start + header_len
                for i, v in enumerate(values):
                    if isinstance(v, str) and re.search(sig_pattern, v):
                        # Calculate where this value starts in the file
                        # Values area starts at header_end, not record_start
                        value_offset = header_end
                        for j, s in enumerate(serials[:i]):
                            value_offset += serial_type_width(s)
                        # Only accept if signature starts EXACTLY at match position
                        if value_offset == sig_start:
                            return values, rowid
            except:
                continue
    return None
```

Without this check, rowid=116 'testword0' false positives emerge — the pattern matches but the record structure is garbage.

## Common Pitfalls

1. **Wrong header offsets**: Text encoding is at byte 56, not 21
2. **Assuming single-byte integers**: Values may be float64 (type 7) or multi-byte ints
3. **Grepping hex dumps**: Records can straddle line boundaries
4. **Missing payload validation**: Always check `header_len + sum(serial widths) == payload_len`
5. **Little-endian floats**: SQLite uses big-endian for all multi-byte values
6. **Trusting .recover**: If it returns nothing but parsing finds rows, the schema page is corrupted - not the data
7. **Emitting corrupted values**: Always validate against expected patterns (e.g., `^testword\d+$`)

## Corruption Patterns Across Family

### Truncation
- File ends mid-page
- Detect: `header_page_count × page_size > actual_size`
- Strategy: Parse complete pages, salvage partial final page via signature scan

### Zeroed Regions
- Pages or cells replaced with nulls
- Detect: Page type 0x00 or invalid
- Strategy: Skip damaged pages, use signature scan for intact regions

### Random Bit Flips
- Single-bit errors in headers or data
- Detect: Payload validation failure
- Strategy: Fallback to expected serial types from DDL/siblings

### Damaged Page Structures
- Cell pointers corrupted
- Detect: Parse errors or out-of-bounds offsets
- Strategy: Signature scan with step-back to find records, using the **exact-offset invariant** (see below)

### Split Fragments
- Records crossing page boundaries with overflow
- Detect: Payload exceeds `max_local` threshold
- Strategy: Follow overflow chain, reassemble fragments

### Multi-Table Interleaving
- Records from multiple tables on same page
- Strategy: Parse all records, assign to tables by column-count/serial-shape match

## Known Limitations

### Column Order Assumption
**Current fragility**: The emitter assumes the value column immediately follows the word column (`values[word_idx + 1]`). This breaks silently if the schema uses a different column order (e.g., value before word, or word, note, value).

**Future-proof rule**: Map public JSON keys → DDL column names → index lookup by name, never adjacency. The current implementation works for v01's two-column schema but will fail for variants with:
- `(value, word)` column order
- `(word, note, value)` with middle columns
- Multi-table schemas where value column position varies

**Fix direction**: Parse DDL from sqlite_master to get column names, match `word` and `value` by name, then compute indices.

## Development & Debugging Practices

Two patterns that separate working recovery from silent failures:

### 1. Never Use Bare `except: continue` in Candidate Loops

A bare exception handler converts loud bugs into silent zero-results. During development, count and print rejections by reason:

```python
rejected = {'parse_fail': 0, 'no_sig_in_value': 0, 'offset_mismatch': 0}

for candidate in candidates:
    try:
        record = parse_candidate(candidate)
        if not record:
            rejected['parse_fail'] += 1
            continue
        if not validate_signature(record):
            rejected['no_sig_in_value'] += 1
            continue
        if not exact_offset_check(record):
            rejected['offset_mismatch'] += 1
            continue
        accept(record)
    except Exception as e:
        rejected['parse_fail'] += 1
        continue

print(f"Accepted: {len(accepted)}, Rejected: {rejected}")
# "0 found, 96 rejected (TypeError: cannot use bytes pattern on str)" 
# → points at the bug in one run instead of a manual trace in five
```

### 2. Add Sanity Floors to Scan Reports

You KNOW the file contains N raw signature occurrences. If the scan accepts 0 of N, that's an internal contradiction worth an assertion:

```python
raw_matches = list(re.finditer(sig_pattern, data))
accepted = [r for r in candidates if exact_offset_check(r)]

# The scan exists precisely for when the walk loses cells
# Its silence should be loud
if len(accepted) == 0 and len(raw_matches) > 0:
    raise AssertionError(
        f"{len(raw_matches)} raw signature matches but 0 accepted - "
        "check bytes vs str pattern compatibility"
    )
```

A scan that finds nothing when the walk lost rows is precisely the case it exists for — make its failures visible.
