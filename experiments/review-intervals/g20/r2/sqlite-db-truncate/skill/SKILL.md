---
name: sqlite-db-truncate
description: Three-tier recovery architecture for corrupted SQLite databases with bit-flip errors, truncated records, and damaged page structures
---

# SQLite Database Recovery Skill

## Overview

This skill implements a three-tier recovery architecture for extracting data from corrupted SQLite databases. The architecture progressively escalates from structured parsing to raw byte scanning, handling various corruption scenarios including bit-flips, truncated records, and damaged page structures.

## Architecture

### Tier 1: Structured Parsing

Parse SQLite page headers and cell pointer arrays to extract records through normal b-tree traversal.

**When to use:** Database file header and page structures are intact.

**Process:**
1. Parse SQLite file header (first 100 bytes) to get page size
2. For each page, parse b-tree page header at offset 100 (page 1) or 0 (other pages)
3. Read cell pointer array from page header
4. For each cell pointer, parse the cell:
   - Read payload length (varint)
   - Read rowid (varint)
   - Extract payload bytes
5. Parse record payload:
   - Read header length (varint)
   - Read serial types (varints)
   - Decode values according to serial types

**Serial types:**
- 0: NULL
- 1-6: Integer (1, 2, 3, 4, 6, 8 bytes)
- 7: 8-byte IEEE 754 float
- 8: Constant 0
- 9: Constant 1
- ≥12 even: BLOB, length = (type - 12) / 2
- ≥13 odd: TEXT, length = (type - 13) / 2

### Tier 2: Corruption-Aware Structured Parsing

When Tier 1 fails to parse a record, attempt bit-flip repair on the record header.

**When to use:** Record parsing fails due to corrupted serial types or header length.

**Process:**
1. **Single-bit-flip repair:** For each byte in the record header (up to 20 bytes), for each bit position (0-7), flip the bit and attempt to parse the record. If parsing succeeds and produces at least one text value, accept the repair.
2. **Multi-bit-flip repair:** If single-bit repair fails or produces a low-quality result, try all 2-bit combinations in the header area (up to 15 bytes for performance). This handles severe corruption where multiple bits are flipped.
3. **Score comparison:** When both single-bit and multi-bit repairs succeed, compare them using a scoring heuristic that prefers:
   - TEXT values over BLOB values
   - Clean printable ASCII text (no special characters like @, #, etc.)
   - Reasonable numeric values (not extreme floats or huge integers)
   - Longer text values (short text is often a sign of wrong interpretation)

**Key insight:** A parse that "succeeds" structurally can still be semantically wrong due to corrupted length metadata. For example, a serial type of 0x5b (TEXT length 39) vs 0x5f (TEXT length 41) both parse successfully, but one produces truncated text. Always validate that parsed text looks complete (e.g., SQL statements have closing parentheses).

**Multi-bit repair example:** A corrupted serial type 0x1a might parse as TEXT(7) producing "test01@" (wrong), but a 2-bit flip to 0x19 produces TEXT(6) yielding "test01" (correct). The scoring heuristic correctly identifies the 2-bit repair as superior.

### Tier 3: Raw Content Scanning

When page headers are corrupted, scan raw bytes for recognizable text patterns and reconstruct records around them.

**When to use:** Page headers are damaged or unreadable, or to supplement Tiers 1-2 with missed records.

**Process:**
1. Search for text patterns (e.g., regex `testword\d+` or generic `[a-zA-Z_][a-zA-Z0-9_]{3,40}`)
2. For each text match at offset T with length L:
3. Try text lengths from L-5 to L+25 (regex may grab trailing bytes or match only a prefix)
4. For each candidate length, compute expected serial type: `2 * length + 13`
5. Look backwards from T (up to 30 bytes) for a record header:
   - Read header length (varint)
   - Read serial types (varints)
   - Check if expected serial type is present
   - Verify data offset alignment (text should start at expected position)
6. If header validates, decode all values
7. If normal header fails, try single-bit-flip repair on header bytes
8. Post-process candidates:
   - **Spatial deduplication:** If two candidates have overlapping text regions, keep the shorter one
   - **Schema consensus:** Reject candidates whose column count doesn't match the majority
   - **Text validation:** Filter out SQL schema fragments and non-printable text

## Schema Extraction

### Auto-detection from sqlite_master

1. Parse page 1 b-tree header (offset 100)
2. Extract sqlite_master records
3. Look for CREATE TABLE statements in text values
4. If SQL is truncated (missing closing paren), try exhaustive bit-flip repair:
   - Try all single-bit flips on the payload
   - Pick the repair that produces the longest SQL statement
5. Extract column names from SQL using regex: `CREATE\s+TABLE\s+\w+\s*\(([^)]+)\)`
6. Fallback: if closing paren missing, try `CREATE\s+TABLE\s+\w+\s*\(([^)]+)`

### Schema inference from data

If sqlite_master is unreadable, infer schema from recovered records:
1. Count serial type sequences across all records
2. Most common sequence defines column types
3. Generate generic column names: `col0`, `col1`, etc.

## Usage

```bash
python3 recover.py <database_path> <output_json_path> [--pattern REGEX] [--columns col1,col2,...]
```

**Options:**
- `--pattern`: Regex pattern for Tier 3 text search (e.g., `testword\d+`)
- `--columns`: Comma-separated column names (overrides auto-detection)

**Output:** JSON array of objects with column names as keys.

## Implementation Notes

### Zeroed Region Detection

SQLite pages often have large unused areas that are zeroed. The recovery tool detects truly zeroed regions by checking:
1. Page has >99% zeros
2. Page has no valid b-tree header

This prevents false positives on pages that are mostly zeros but still contain valid data in the cell content area.

### Truncation Detection

The tool detects if the database file is truncated by comparing the actual file size with the expected size from the SQLite header:
- Expected size = page_size × db_size_pages
- If actual size < expected size, the database is truncated
- Reports the number of missing pages and truncation percentage
- Recovery proceeds with available pages only

This is important for the "sqlite-db-truncate" family where truncation is a common corruption mechanism.

### Page Header Repair

When a b-tree page header is corrupted (e.g., page type byte is invalid), the tool attempts single-bit-flip repair on the first 8 bytes of the header. If a valid header is found with reasonable values (num_cells < 1000, cell_content_start within page bounds), the repair is accepted.

**Limitation:** Single-bit repair may produce a valid but incorrect header type (e.g., repairing 0x00 to 0x02 instead of 0x0D). In such cases, Tier 3 raw scanning serves as a fallback to recover records without relying on the page structure.

### Varint encoding

SQLite varints are 1-9 bytes. Each byte contributes 7 bits to the value (high bit is continuation flag). The 9th byte uses all 8 bits.

```python
def read_varint(data, offset):
    result = 0
    for i in range(9):
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | byte
            return result, 9
    return result, 9
```

### Page header offset

- Page 1: b-tree header at offset 100 (after SQLite file header)
- Other pages: b-tree header at offset 0

### Cell content layout

Cells grow backwards from the end of the page. Cell pointer array is at the beginning of the b-tree header (after the 8-byte page header).

### Filtering sqlite_master records

Page 1 contains the sqlite_master table. Filter out records from page 1 and records containing "CREATE TABLE" to avoid including schema metadata in the output.

### IEEE 754 float patterns

Common values have recognizable patterns:
- 0.5: `3fe0000000000000`
- 10.0: `4024000000000000`
- 99.99: `4058ff5c28f5c28f`

When recovering floats, check if the value is a whole number and convert to int if appropriate.

## Testing

Test with the v01 database:

```bash
python3 /skill/recover.py /app/trunc.db /app/recover.json
```

Expected output: 8 records with columns `word` and `value`, values ranging from testword02 to testword09.

## Limitations

- Multi-bit-flip repair is limited to 2-bit combinations for performance (handles most real-world corruption)
- Raw scanning may produce false positives if text patterns are not specific enough
- Schema inference requires multiple records with consistent structure
- Does not handle multi-page overflow records (payloads larger than page size)
- Zeroed region detection requires >99% zeros to avoid false positives
- Repair scoring heuristics may not always choose the correct repair in edge cases

## Future Enhancements

- 3+ bit-flip repair for extreme corruption cases
- Overflow page handling for large records
- Index recovery for non-table data
- Fragment reassembly for split records
- Multi-table recovery with table identification
- Improved repair scoring using machine learning or more sophisticated heuristics
