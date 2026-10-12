# SQLite Binary Recovery and Repair

When `sqlite3` rejects a database as malformed, truncated, or corrupted, standard queries will fail. Use these manual binary parsing and repair patterns to recover data and fix the file.

## 1. Recover Schema from Page 1 (sqlite_master)
The first page (page 1) always contains the `sqlite_master` table (after the 100-byte file header).
1. Parse page 1's B-tree header (starting at offset 100).
2. Read the cell pointer, decode the cell's record with 5 columns: `type` (TEXT), `name` (TEXT), `tbl_name` (TEXT), `rootpage` (INT), and `sql` (TEXT).
3. Use the `sql` text to get the exact `CREATE TABLE` schema and `rootpage` to find the table data. Use column type affinities to validate record serial types.

## 2. Manual B-Tree Page and Record Parsing
Bypass integrity checks by parsing raw pages directly.
1. **File Header**: Read bytes 16-17 for page size.
2. **Page Header**: For each page, read flag byte (`0x0d`=leaf table, `0x05`=leaf index), cell count at bytes 3-4, cell-content-area offset at bytes 5-6, and 2-byte cell pointers starting at byte 8 (or byte 12 for interior table pages).
3. **Cell Decoding**: For each cell pointer, decode payload-length varint, rowid varint, then the record: header-size varint, followed by serial-type varints for each column, then column data:
   - 0 = NULL
   - 1-6 = ints (big-endian, signed)
   - 7 = IEEE-754 float (8 bytes)
   - ≥13 odd = TEXT of (N-13)/2 bytes
   - ≥12 even = BLOB

```python
import struct

def read_varint(data, pos):
    result = 0
    for i in range(9):
        byte = data[pos + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 128:
                return result, pos + i + 1
        else:
            result = (result << 8) | byte
            return result, pos + i + 1
    return result, pos
```

## 3. Detect and Correct Single-Bit-Flip Corruptions
Identify corrupted bytes by cross-referencing redundant structural constraints. Flip the minimum bits to satisfy all constraints simultaneously.
- **Cell-content-area offset**: Must equal the smallest cell pointer. (e.g., if pointer is `0x0FC1` but offset header says `0x0FC5`, the header byte likely has a flipped bit: `0xC5`→`0xC1`).
- **Payload length vs Serial types**: Each serial type's implied data length must sum (with header) to the declared payload length. (e.g., if payload is 61 and header+other columns consume 20 bytes, remaining column must be 41 bytes, so serial type must be `(41×2)+13=0x5F`, not `0x5B`).
- **Schema Validation**: Validate parsed serial types against the known schema. If `diff = parsed_type ^ expected_type` is non-zero and `diff & (diff - 1) == 0`, it's a single bit-flip.

## 4. Sanitize Free Space
After fixing structural corruptions, zero out all non-zero bytes in unallocated/free regions of each page (between the end of the cell pointer array and the start of the cell content area). Random bit flips in these zero-filled areas cause `sqlite3` to reject the database even when structural fields are correct.

```python
# For page 1: B-tree header starts at offset 100
# Free area: from (100 + 8 + 2*num_cells) to cell_content_offset
# For page N>1: B-tree header starts at page_start
# Free area: from (page_start + 8 + 2*num_cells) to (page_start + cell_content_offset)

for i in range(free_start, free_end):
    if data[i] != 0:
        data[i] = 0
```

Verify the fix: `sqlite3 fixed.db "PRAGMA integrity_check;"` should return `ok`.