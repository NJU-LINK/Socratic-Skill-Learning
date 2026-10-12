---
name: sqlite-db-truncate
description: Recover rows from corrupted SQLite databases using payload-size checksums, bit-flip correction, and text-pattern scanning
---

# SQLite Database Corruption Recovery

This skill recovers data from SQLite databases that have been corrupted through truncation, zeroed regions, bit flips, or damaged page structures. The recovery combines structured SQLite format parsing with principled error correction techniques.

## Core Algorithm

### 1. Parse SQLite File Structure

Read the 100-byte file header to extract:
- Page size (bytes 16-17, big-endian)
- Database size in pages (bytes 28-31)
- File format version

Each page has a b-tree header starting at offset 0 (or offset 100 for page 1):
- Page type (1 byte): 13 = leaf table b-tree
- Number of cells (2 bytes, big-endian)
- Cell content area start (2 bytes)
- Cell pointer array: N × 2-byte offsets

### 2. Extract Schema from sqlite_master

Page 1 contains the sqlite_master table with CREATE TABLE statements. Parse this to get:
- Table names
- Column names and types
- Root page numbers

**Fallback chain:** If structured parsing fails, the script tries:
1. **Text-based extraction:** Scan the raw file for `CREATE TABLE` text patterns and extract schema directly from SQL text
2. **Schema override:** Use `--schema` command-line argument if provided
3. **Structural inference:** Try to infer column count from the first parseable record on data pages
4. **Best-effort mode:** If all schema recovery fails, scan all pages for any parseable records and group them by column count

### 3. Parse Records Using Payload-Size Checksum

Each cell in a leaf b-tree page contains:
- Payload size (varint): total bytes of the record
- Row ID (varint): the INTEGER PRIMARY KEY
- Record payload: header + data

**Record format:**
- Header size (varint): includes this varint itself
- Serial types (varints): one per column
- Column data: concatenated values

**Critical integrity check:** The declared payload_size must equal:
```
header_size + sum(serial_type_size(st) for st in serial_types)
```

If this doesn't match, the record is corrupted.

### 4. Bit-Flip Error Correction

When the payload-size checksum fails, try single-bit-flip corrections on:
1. **Header size byte(s):** The header_size varint itself may be corrupted
2. **Serial type bytes:** Individual serial type varints may have bit flips

For each byte position in the header, try flipping each of the 8 bits and check if the resulting serial types produce a total size matching the declared payload_size.

**Validation:** After correction, verify that text values are printable and that the number of columns matches the schema.

### 5. Multi-Bit-Flip Correction (Optional)

If single-bit correction fails, try flipping up to 2 bits total across the header. This is more expensive but handles cases where multiple bits are corrupted.

### 6. Raw Fragment Scanning

When structured parsing is impossible (e.g., cell headers completely destroyed), scan the raw file for recognizable text patterns (like "testword") and attempt to reconstruct records by:
- Finding text fragments
- Searching backwards for record headers
- Matching serial types to the fragment size

## Key Techniques

### Payload-Size as Checksum

The declared payload_size is the strongest integrity signal. It's stored in the cell header before the record, so it survives even when the record header is corrupted. Use it to:
- Detect corruption (size mismatch)
- Guide error correction (find bit flips that make sizes match)
- Validate recovery attempts

### Varint Encoding

SQLite uses variable-length integers (varints):
- Bytes 1-8: high 7 bits are data, low bit = continuation (1 = more bytes)
- Byte 9: all 8 bits are data
- Maximum 9 bytes for 64-bit values

### Serial Type Table

| Type | Meaning | Size |
|------|---------|------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit signed int | 2 |
| 3 | 24-bit signed int | 3 |
| 4 | 32-bit signed int | 4 |
| 5 | 48-bit signed int | 6 |
| 6 | 64-bit signed int | 8 |
| 7 | IEEE 754 float | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12, even | BLOB | (N-12)/2 |
| N≥13, odd | Text | (N-13)/2 |

## Usage

```bash
python3 scripts/recover_sqlite.py <input.db> <output.json> [--schema COL1:TYPE1,COL2:TYPE2,...]
```

**Options:**
- `--schema`: Override schema when sqlite_master is unreadable. Format: `col1:TYPE1,col2:TYPE2,...`

**Output:** JSON array of objects, one per recovered row. Column names are keys.

## Examples

### Basic Recovery

```bash
python3 scripts/recover_sqlite.py corrupted.db recovered.json
```

### With Schema Override

```bash
python3 scripts/recover_sqlite.py corrupted.db recovered.json --schema "name:TEXT,age:INTEGER,score:REAL"
```

## Known Limitations and Future Work

### Current Limitations

1. **B-tree interior pages not traversed:** The script scans all pages directly but doesn't follow the B-tree structure through interior pages (types 2, 5, 10). For large databases with hundreds of records spanning multiple leaf pages, this approach works because corrupted databases tend to be small. For healthy multi-page B-trees with intact interior pages, proper traversal would follow right-most-child pointers and cell pointers to discover all leaf pages.

2. **Overflow pages not handled:** SQLite stores large payloads (>usable_page_size - 12 bytes) across overflow pages linked by 4-byte page pointers. The script would miss records with long text columns or large BLOBs that span multiple pages. Detection requires checking if payload_size exceeds the local storage threshold and following the overflow page chain.

3. **Multiple tables with interleaved pages:** For databases with multiple tables, the best-effort mode groups records by column count, which may not perfectly separate tables with the same schema. Proper recovery would require either parsing sqlite_master correctly to get each table's rootpage, or clustering records by their serial type signatures and value patterns.

4. **Fragment scanner limitations:** The raw fragment scanner is a best-effort fallback for cases where cell headers are completely destroyed. It searches backwards from text patterns to reconstruct record headers, but this is heuristic and may produce false positives or miss records with unusual serial type combinations.

5. **Completely destroyed cells:** If both the cell header and record are zeroed or random, recovery is impossible. The script will skip these.

### Addressed Limitations

1. **Schema recovery with severe corruption:** The script now implements a 4-level fallback chain (structured parsing → text extraction → structural inference → best-effort mode) to handle cases where sqlite_master is completely unreadable.

2. **Zeroed regions:** The fragment scanner and best-effort mode can recover records even when large regions of the database are zeroed, as long as some record data remains intact.

### Future Enhancements

- **B-tree traversal:** Implement proper interior page parsing to follow cell pointers and right-most-child links for multi-page tables
- **Overflow page reconstruction:** Detect overflow flags in cell headers and follow page chains to reconstruct large records
  - The script includes helper functions `calculate_local_payload_size()` and `read_overflow_pages()` as reference implementation
  - Integration path: modify `scan_page_for_records()` to call `try_parse_record_with_overflow()` instead of `try_parse_record()`
  - Key challenge: overflow records have local payload smaller than declared payload_size, so the size check must be adjusted
- **Advanced table clustering:** Use serial type signatures, value patterns, and rowid ranges to better separate interleaved tables
- **WAL and journal recovery:** Handle Write-Ahead Log and rollback journal files for additional recovery paths

## Testing the Recovery

After recovery, validate the output:
1. Check that text values are reasonable (not garbage)
2. Verify numeric values are in expected ranges
3. Ensure row count matches expectations (if known)
4. Spot-check a few records against any available backups or documentation

## References

- `references/sqlite_format.md`: Detailed SQLite on-disk format reference
- SQLite documentation: https://www.sqlite.org/fileformat.html
