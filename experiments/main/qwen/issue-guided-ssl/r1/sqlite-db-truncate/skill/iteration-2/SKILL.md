---
name: sqlite-db-truncate
description: >
  Recover rows from corrupted SQLite databases by parsing raw page structures,
  cell pointer arrays, varints, serial types, and record payloads at the byte
  level. Handles truncation, zeroed regions, random bit flips, damaged page
  structures, and fragmented records across varying schemas and scales.
---

# SQLite Database Corruption Recovery

## Overview

This skill recovers logically valid rows from damaged SQLite storage when
ordinary queries fail. It works by directly parsing the SQLite binary format
at the byte level, bypassing the corrupted structures that prevent normal
database access.

## Quick Start

The skill package is mounted at `/skill/` inside the task container. The recovery
script is at `/skill/scripts/recover_sqlite.py`.

**To recover a corrupted database:**
```bash
python3 /skill/scripts/recover_sqlite.py /app/trunc.db /app/recover.json
```

This single command handles: file header parsing, page structure analysis,
schema extraction from sqlite_master, cell-by-cell record recovery with
bit-flip correction for corrupted serial types, and JSON output.

If the script fails (e.g., severely corrupted page headers), fall back to
writing a custom recovery script using the format reference below.

## When to Use

- SQLite database file exists but `sqlite3` reports "database disk image is malformed"
- File has correct SQLite magic header but pages are corrupted
- Random bit flips, zeroed regions, or truncation have damaged the file
- Need to extract as many rows as possible from the damaged storage

## SQLite Binary Format Reference

### File Structure
- **File header**: First 100 bytes. Offset 16-17 = page size (big-endian uint16; 1 means 65536). Offset 28-31 = total page count.
- **Pages**: File divided into fixed-size pages (commonly 1024, 2048, 4096 bytes).
- **Page 1**: Contains the file header (100 bytes) followed by the B-tree page header. Also holds sqlite_master entries.

### B-tree Page Headers
Every B-tree page starts with a header (after the 100-byte file header on page 1):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Page type: 0x0D=table leaf, 0x05=table interior, 0x0A=index leaf, 0x02=index interior |
| 1-2 | 2 | First freeblock offset (0=none) |
| 3-4 | 2 | Number of cells |
| 5-6 | 2 | Start of cell content area |
| 7 | 1 | Fragmented free bytes |
| 8-11 | 4 | (Table interior only) Rightmost child pointer |

### Cell Pointer Array
Immediately after the page header: array of 2-byte big-endian offsets, one per cell, pointing into the page's content area. These pointers are often intact even when cell content is corrupted.

### Table Leaf Cell Format
```
[payload-length varint] [rowid varint] [payload bytes...]
```
If payload exceeds usable page space, last 4 bytes of local area contain overflow page number.

### Record Format (the payload)
```
[header-size varint] [serial-type-0 varint] [serial-type-1 varint] ... [column-data...]
```

### Serial Types
| Code | Meaning | Size |
|------|---------|------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit signed int | 2 |
| 3 | 24-bit signed int | 3 |
| 4 | 32-bit signed int | 4 |
| 5 | 48-bit signed int | 6 |
| 6 | 64-bit signed int | 8 |
| 7 | IEEE-754 float64 | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12, even | Blob | (N-12)/2 |
| N≥13, odd | Text (UTF-8) | (N-13)/2 |

### Varint Encoding
Up to 9 bytes. Each byte uses 7 data bits; high bit = "more bytes follow." The 9th byte uses all 8 bits.

```python
def read_varint(data, offset):
    result = 0
    for i in range(9):
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if not (byte & 0x80):
                return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
```

## Recovery Strategy

### Phase 1: Structured Page Parsing
1. Parse file header → get page size and page count
2. For each page, parse the B-tree page header → identify page type and cell count
3. Read cell pointer array → get offsets to each cell
4. For each cell pointer, parse the cell: payload-length varint → rowid varint → record payload
5. Parse the record: header-size varint → serial type varints → decode column values

### Phase 2: Schema Extraction
1. Parse page 1 (sqlite_master) to extract CREATE TABLE statements
2. Get column names and types for each user table
3. Map root page numbers to tables
4. If sqlite_master is too corrupted, infer schema from record patterns (consistent serial types across records)

### Phase 3: Corruption Handling
When record parsing fails due to corruption:

**Corrupted serial types** (bit flips in header bytes):
- Calculate expected data size from remaining payload
- If a serial type implies more data than available, try single-bit flips
- For the last column in a record, find a type whose size exactly matches remaining bytes
- Prefer text types for text columns, integer/float types for numeric columns

**Corrupted cell pointers**:
- If pointer points to all-zero region, skip the cell
- Scan the content area for valid-looking record headers

**Overflow pages**:
- If payload extends beyond page boundary, follow overflow page chain
- Each overflow page: first 4 bytes = next page number, rest = payload data

### Phase 4: Raw Scan Fallback
If structured parsing yields no results (severely damaged page headers):
- Scan entire file for record-like byte patterns
- Look for small header varints followed by valid serial types and UTF-8 text
- Match partial text strings against known patterns

### Phase 5: Output
- Map decoded values to column names from schema
- Clean up float values that are actually integers (e.g., 10.0 → 10)
- Write JSON array of row objects

## Usage

### Quick Recovery
```bash
python3 scripts/recover_sqlite.py <corrupted.db> <output.json>
```

### With Schema Hint
```bash
python3 scripts/recover_sqlite.py <corrupted.db> <output.json> \
  --schema "word:TEXT,value:REAL"
```

### Programmatic Use
```python
from recover_sqlite import recover_database
records = recover_database("corrupted.db", "output.json")
```

## Generalization Across the Family

### Corruption Mechanisms
- **Truncation**: File cut short; pages beyond truncation point are missing. Parse available pages normally.
- **Zeroed regions**: Sections filled with zeros. Cell pointers to zeroed areas are skipped; content scanning finds records in non-zero regions.
- **Random bit flips**: Individual bits changed. Varint and serial type parsing includes bit-flip correction.
- **Damaged page structures**: Page headers corrupted. Raw scan fallback finds records without relying on page structure.
- **Split fragments**: Records split across corrupted boundaries. Overflow page handling and fragment reassembly.

### Schema Variations
- Multiple tables: Follow sqlite_master to map table names → root pages → records
- Different column types: Serial types determine actual encoding per-record
- NULLs: Serial type 0 = NULL, zero bytes consumed
- Large text/blobs: May use overflow pages
- Cross-page records: Handled via overflow page chain

### Scale Variations
- Small (2-column, 8 rows): Direct cell-by-cell parsing
- Medium (dozens of rows, multiple tables): Same approach, iterate all pages
- Large (hundreds of rows): B-tree traversal via interior pages; follow child pointers

## Key Implementation Details

1. **Always work at byte level** — never rely on SQLite's own parser for corrupted files
2. **Cell pointer arrays are usually intact** even when cell content is corrupted
3. **Serial type corruption is common** — single-bit flips change type codes; fix by checking data size constraints
4. **Schema from sqlite_master may be partially corrupted** — extract what's usable, infer the rest
5. **Validate decoded values** — text should be valid UTF-8, integers should be in reasonable range
6. **Handle both int and float storage** — SQLite stores values in the most compact representation regardless of column type affinity
