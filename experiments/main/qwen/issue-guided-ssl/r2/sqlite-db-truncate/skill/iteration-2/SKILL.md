---
name: sqlite-db-truncate
description: Recover records from corrupted SQLite databases using raw byte analysis when standard queries fail
---

# SQLite Corrupted Database Recovery

## Overview

This skill recovers records from SQLite databases that have been corrupted through mechanisms like truncation, zeroed regions, random byte flips, or damaged page structures. It works by directly parsing the SQLite binary format when ordinary SQL queries cannot access the data.

## When to Use

- Database file exists but SQLite reports "database disk image is malformed"
- Standard `SELECT` queries fail or return incomplete results
- File size is correct but internal structures are damaged
- Need to recover data from partially corrupted database files
- Database has been truncated, zeroed, or has bit-flip corruption

## Core Concepts

### SQLite File Structure

1. **Page-based storage**: Database divided into fixed-size pages (typically 1024, 2048, 4096, or 8192 bytes)
2. **Page size location**: Bytes 16-17 of the database header (big-endian)
3. **First page**: Starts with 100-byte database header, then b-tree structure
4. **Other pages**: Start directly with b-tree structure
5. **sqlite_master**: Schema table always on page 1, contains CREATE TABLE statements

### B-tree Leaf Table Page (Type 0x0D)

```
Offset 0: page type (1 byte) — 0x0D for leaf table
Offset 1: first freeblock (2 bytes, big-endian)
Offset 3: cell count N (2 bytes, big-endian)
Offset 5: cell content area start (2 bytes, big-endian)
Offset 7: fragmented free bytes (1 byte)
Offset 8: cell pointer array — N × 2-byte big-endian offsets
```

### Cell Structure (Leaf Table)

Each cell contains:
```
payload_length : varint (total record size)
rowid          : varint (row identifier)
record_payload : payload_length bytes (encoded record)
```

### SQLite Record Format

Records are self-describing:
```
header_size    : varint (H = total header bytes including this varint)
serial_type_1  : varint
serial_type_2  : varint
...
serial_type_M  : varint
data_for_col_1
data_for_col_2
...
data_for_col_M
```

### Serial Type Reference

| Serial Type | Meaning | Data Bytes |
|-------------|---------|------------|
| 0 | NULL | 0 |
| 1 | 8-bit int | 1 |
| 2 | 16-bit int | 2 |
| 3 | 24-bit int | 3 |
| 4 | 32-bit int | 4 |
| 5 | 48-bit int | 6 |
| 6 | 64-bit int | 8 |
| 7 | IEEE-754 float | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| 10–11 | Reserved | — |
| Even K ≥ 12 | BLOB | (K−12)/2 bytes |
| Odd K ≥ 13 | TEXT | (K−13)/2 bytes |

**Key formula**: For TEXT with serial type K, the byte count is `(K - 13) / 2`.

### Varint Encoding

Each byte uses 7 data bits; the high bit means "more bytes follow":
- Values 0–127: single byte
- Values 128+: shift-accumulate: `value = (value << 7) | (byte & 0x7F)` while high bit is set
- 9th byte uses all 8 bits

## Recovery Algorithm

### Step 1: Extract Schema (When Possible)

The sqlite_master table on page 1 often survives corruption. Extract it to understand:
- Table names and structures
- Column names and types
- Which tables to recover

**sqlite_master record format**: 5 columns (type TEXT, name TEXT, tbl_name TEXT, rootpage INT, sql TEXT)

### Step 2: Cell Pointer Parsing

When page structures are intact:
1. Read page size from database header (bytes 16-17)
2. For each page, check if page type is 0x0D (leaf table)
3. Read cell count and cell pointer array
4. For each cell pointer:
   - Decode payload_length and rowid varints
   - Extract record payload
   - Decode record using serial types
   - **Apply schema-aware filtering** to skip schema records
   - Extract column values

**Critical**: Different tables share rowid space. The sqlite_master table and user data tables both use rowid=1, 2, 3, etc. Always filter records by schema structure before adding to results.

### Step 3: Raw Content Scanning (Fallback)

When page structures are corrupted:
1. Scan through raw bytes looking for cell-like patterns
2. For each potential cell start:
   - Check if first byte could be payload_length (high bit clear, reasonable size)
   - Check if second byte could be rowid
   - Extract record and attempt to decode
   - Validate decoded values (e.g., check for expected text patterns)
3. Use heuristics to identify valid records:
   - Record header size must be reasonable
   - Serial types must decode to valid column data
   - Text columns should contain readable strings

### Step 4: Corruption Handling

When serial types are corrupted (bit flips):
1. Try decoding with original serial types
2. If that fails, try common alternatives:
   - For TEXT columns: try serial types 0x21, 0x23, 0x25, etc.
   - For integer columns: try serial types 0x01-0x06
   - For float columns: try serial type 0x07
3. Validate alternatives by checking if decoded data makes sense

### Step 5: Schema-Aware Filtering

Skip schema records by detecting their structure:
- sqlite_master records have 5 columns
- At least 3 TEXT columns (type, name, tbl_name, sql)
- 1 INT column (rootpage)
- First TEXT column is 'table', 'index', 'view', or 'trigger'

## Implementation

See `recover.py` for a complete Python implementation that:
- Extracts schema from sqlite_master when possible
- Reads page size from database header
- Attempts cell pointer parsing for leaf table pages
- Falls back to raw content scanning
- Handles corrupted serial types via alternative guessing
- Decodes both integer and float values correctly
- Filters schema records to avoid rowid collisions
- Outputs recovered records as JSON

## Usage

```bash
python3 recover.py <input.db> <output.json> [target_table]
```

The script:
1. Extracts schema information (if recoverable)
2. Recovers all valid records from all pages
3. Filters out schema records
4. Outputs data records as JSON

## Handling Different Corruption Mechanisms

### Bit-Flip Corruption
- Affects individual bytes (often serial types)
- Records remain mostly intact
- Use alternative serial type guessing

### Truncation
- File is shorter than expected
- Pages at the end are missing
- Recover what's available from intact pages

### Zeroed Regions
- Large sections filled with zeros
- Cell pointers or page headers may be damaged
- Use raw content scanning to find records

### Damaged Page Structures
- Page type byte corrupted
- Cell pointer array damaged
- Fall back to byte-by-byte scanning

### Records Crossing Page Boundaries
- Rare but possible in large records
- Check if payload extends beyond page end
- Reassemble from multiple pages if needed

## Limitations

- Cannot recover records where the actual data bytes are corrupted (only header/metadata corruption is fixable)
- May produce false positives when scanning raw bytes (validation heuristics help but aren't perfect)
- Performance degrades with very large databases due to byte-by-byte scanning
- **Must filter records before deduplication** to avoid mixing records from different tables that share rowid values
- Schema extraction may fail if page 1 is heavily damaged

## Testing

Tested on corrupted SQLite databases with:
- Bit-flip corruption in serial type bytes (e.g., 0x21 → 0x61)
- Damaged cell pointer arrays
- Mixed integer and float column types
- Text columns with recognizable patterns
- Multiple tables sharing rowid space (sqlite_master + data table)

Successfully recovered 8/8 records from a test database with:
- Schema: `CREATE TABLE test (word TEXT, value REAL)`
- 1 corrupted serial type byte (fixed via alternative type guessing)
- 6 records with integer values (serial type 0x01)
- 2 records with float values (serial type 0x07)
- Schema record on page 0 filtered out to avoid rowid collision

## Adapting to Different Tasks

The recovery script provides a general mechanism. To adapt to different tasks:

1. **Extract the schema** to understand table structure
2. **Identify target records** using patterns from the task instruction
3. **Filter recovered records** based on expected column values
4. **Format output** according to task specification

Example patterns for record identification:
- Text patterns: `testword\d+`, `user_\w+`, `item-\d+`
- Numeric ranges: values between min and max
- Column structure: specific number of columns with expected types
- Content validation: check if decoded values make sense

The key is to recover ALL valid records first, then filter based on task requirements.
