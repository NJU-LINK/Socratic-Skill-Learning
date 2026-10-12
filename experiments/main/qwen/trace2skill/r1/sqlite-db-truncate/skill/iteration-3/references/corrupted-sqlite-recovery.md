# Corrupted SQLite Recovery Techniques

When standard SQLite tools fail (e.g., 'database disk image is malformed') due to file corruption or truncation, use these manual parsing and fallback extraction techniques.

## Recovering Schema from Page 1
Page 1 contains the `sqlite_master` table. The B-tree header starts at offset 100 (after the 100-byte database header).
1. Read the B-tree header and cell pointers.
2. Parse the `sqlite_master` record to extract the `CREATE TABLE` statement.
3. Use the schema to determine expected column types (TEXT, REAL, INTEGER) for interpreting data cells.

## Manual B-Tree Leaf Page Parsing
To recover data when standard tools fail, manually parse raw B-tree leaf pages.
- Read page size from DB header (offset 16).
- For a table leaf page (flag `0x0d`), the 8-byte header contains: flag(1), first_freeblock(2), num_cells(2), cell_content_start(2), fragmented_bytes(1).
- Cell pointers follow immediately as 2-byte big-endian offsets relative to page start (starting at offset 8, or 108 for page 1).

```python
import struct
page_size = struct.unpack('>H', data[16:18])[0]
# Leaf table page header (type 0x0d):
num_cells = struct.unpack('>H', page[3:5])[0]
ptrs = [struct.unpack('>H', page[8+2*i:10+2*i])[0] for i in range(num_cells)]
for ptr in ptrs:
    # Parse varints for payload_len and rowid here
    pass
```

## Decoding Record Payloads
Each cell contains: `payload_length` (varint), `rowid` (varint), then the record payload.
The record payload structure:
1. `header_size` (varint)
2. Serial type codes (varints) for each column
3. Column data

Serial type decoding:
- `0`: NULL
- `1-6`: Integers of increasing size (1, 2, 3, 4, 6, 8 bytes)
- `7`: 8-byte IEEE-754 float
- `>=13` (odd): Text of length `(type - 13) / 2`
- `>=12` (even): Blob of length `(type - 12) / 2`

## Detecting and Correcting Corrupted Serial Types
SQLite record corruption often manifests as flipped bits in serial type bytes, causing text lengths to exceed payload bounds.
1. **Validate**: Compute `expected_payload = header_length + sum(column_sizes_from_serial_types)`. If `expected_payload != payload_length`, a serial type byte is likely corrupted. Check if decoded length exceeds available payload space.
2. **Correct**: Check for single-bit errors against expected values based on the schema or known data patterns.
   - *Example*: For a 10-character text string, the correct serial type is `13 + 2*10 = 33` (`0x21`). If the byte is `0x61`, bit 6 is flipped (`0x40`).
3. **Bypass / Fallback**: If strict header parsing fails, search the raw cell payload for known string patterns or schema-based prefixes. Infer type and value of subsequent columns by evaluating remaining byte count against the known schema.

```python
# Fallback extraction when serial types are corrupted:
idx = record.find(b'testword')
word = record[idx:idx+10].decode('utf-8')
remaining = record[idx+10:]
if len(remaining) == 1:
    value = float(remaining[0])  # 8-bit int
elif len(remaining) == 8:
    value = struct.unpack('>d', remaining)[0]  # 64-bit float
```

## Cross-reference with Fresh Database
Create a fresh SQLite database with the same schema and recovered data, then compare byte-by-byte with the corrupted file. This reveals all corruption points including subtle ones like incorrect content_start offsets, wrong serial types in schema entries, and scattered non-zero bytes in free space areas.
After manually parsing recoverable records, create a fresh DB with identical schema and INSERT the parsed data. Use a byte-by-byte diff to categorize differences into: (1) legitimate version differences, (2) structural corruption, (3) corrupted serial types causing payload mismatches, (4) random bit flips in free space. Fix all issues and verify with `PRAGMA integrity_check` to confirm complete recovery.