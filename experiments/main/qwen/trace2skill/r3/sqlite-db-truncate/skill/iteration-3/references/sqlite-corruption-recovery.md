# SQLite Corruption Recovery and Binary Parsing

When standard SQLite tools (`sqlite3`) reject a database as malformed or truncated, bypass integrity checks and parse the raw bytes directly to extract recoverable data.

## 1. Extract Schema from Raw Hex Dump
Even when page 1 (schema page) is corrupted, `CREATE TABLE` statements are often stored as plain text near the end of the page.
1. Dump full hex of page 1 (offset `0x0000` to `page_size`).
2. Search for ASCII `CREATE TABLE` pattern.
3. Extract the full SQL statement to determine table name, column names, and declared types (TEXT, REAL, INTEGER, etc.).
4. Use this schema to interpret record payloads in data pages.

## 2. Raw Binary Parsing
Parse SQLite pages by reading the file header and B-tree pages:
1. **File Header**: Read page size from bytes 16-17 of the file header (first 100 bytes of page 1).
2. **B-tree Page Header**: At page start (or offset 100 for page 1), read page type (`0x0d` = leaf table b-tree), cell count (bytes 3-4, big-endian u16), and cell content area offset (bytes 5-6).
3. **Cell Pointer Array**: Starts at page offset 8. Read `cell_count` × 2-byte big-endian pointers. Each pointer gives the offset (relative to page start) of a record payload.

## 3. Decode Record Payloads
Each cell payload starts with a payload-length varint, a rowid varint, then a record header (header-length varint followed by serial-type varints for each column).
1. Read `payload_length` and `rowid` varints.
2. Read `header_length` varint; then read serial-type varints.
3. For each serial type, extract the corresponding data segment:
   - `0`: NULL
   - `1-6`: integers of increasing size (1 to 6 bytes, signed)
   - `7`: 8-byte IEEE 754 float (big-endian)
   - `8`: integer 0
   - `9`: integer 1
   - `10, 11`: reserved
   - Even values `≥12`: blob of length `(type-12)/2`
   - Odd values `≥13`: text of length `(type-13)/2`
4. Advance data offset after each column. Use Python `struct.unpack('>d', bytes)` for REAL values.

## 4. Bit-Flip Corruption Detection
Detect bit-flip corruptions by validating serial type bytes against expected data lengths and comparing declared payload sizes against actual available data.
- If a serial type declares a length exceeding available payload bytes (e.g., `0x61` declaring 42-byte text when only 11 bytes remain), suspect a bit-flip.
- **Common patterns**: `0x61` (text len 42) should be `0x21` (text len 10) for short strings; `0x5b` (text len 39) should be `0x5f` (text len 41) for schema SQL.
- **Validation**: Check if the corrected serial type produces a record that fits the payload and yields sensible data. Cross-reference with cell pointer spacing to confirm original cell sizes. Verify page header cell content start <= minimum cell pointer.

## 5. Float Value Integrity and Zeroed Cell Reconstruction
When recovering floating-point values (serial type `0x07`), verify whether the 8-byte sequence is an exact IEEE 754 representation of a 'clean' number (e.g., `0.5` = `3FE0000000000000`, `99.99` = `4058FF5C28F5C28F`). Exact matches strongly indicate uncorrupted original data, whereas random bit flips produce chaotic values.

When a cell is mostly zeroed but has surviving non-zero bytes, use positional knowledge to reconstruct:
1. Map surviving non-zero bytes to expected cell layout (payload_size byte, rowid byte, header bytes, TEXT column bytes, REAL column bytes).
2. If the last character of a TEXT field survives (e.g., `0x39`='9' at position 14 of a 23-byte cell), infer the full text from the pattern.
3. For REAL values, if first 2 bytes survive (e.g., `0x3f 0xe0`) and remaining 6 bytes are zero, decode as IEEE-754 double: `0x3fe0000000000000` = 0.5 exactly.
4. Reconstruct the full cell and write to a fixed copy.