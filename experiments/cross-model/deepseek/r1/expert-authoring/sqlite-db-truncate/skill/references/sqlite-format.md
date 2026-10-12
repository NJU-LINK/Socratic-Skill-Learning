# SQLite on-disk format — recovery reference

Facts needed to read damaged SQLite files without the library. All integers are
big-endian unless stated otherwise. `U` = usable page size = page size (minus
reserved space, normally 0). Offsets below are page-relative except where noted.

## Varints

SQLite's variable-length integers are **big-endian base-128**: the most
significant 7-bit group comes first; bit 0x80 of a byte marks "more bytes
follow". 1-byte values (0–127) encode as themselves, so small files/pages never
exercise the continuation case.

- `0x5d` → 93.
- `0x81 0x2f` → `(0x01 << 7) | 0x2f` = 175.
- `0x80 0x01` → `1 << 7` = 128 (non-canonical long forms of small values
  occur in real files; decode per byte: `v = (v << 7) | (b & 0x7F)`).

## Database header (page 1, bytes 0..99)

| offset | size | meaning |
|---|---|---|
| 0 | 16 | magic "SQLite format 3\0" |
| 16 | 2 | page size (512..65536, power of two) |
| 18,19 | 1,1 | file format write/read version |
| 20 | 1 | reserved space per page |
| 21,22,23 | 1,1,1 | max/min/leaf payload fractions |
| 24 | 4 | file change counter |
| 28 | 4 | database size in pages |
| 32 | 4 | first freelist trunk page |
| 36 | 4 | number of freelist pages |
| 40 | 4 | schema cookie |
| 44 | 4 | schema format number |
| 48 | 4 | default page cache size |
| 52 | 4 | largest root btree page |
| 56 | 4 | text encoding: 1=UTF-8, 2=UTF-16le, 3=UTF-16be |
| 60 | 4 | user version |
| 64 | 4 | incremental vacuum |
| 68 | 4 | application ID |
| 92 | 4 | version-valid-for |
| 96 | 4 | SQLite version number that wrote the file |

Truncation checks: `len(file) == page_size * n_pages`, and `len(file) % page_size`.

## Btree page header

Page 1's btree header starts at offset 100 (after the database header); every
other page at offset 0.

| offset | size | meaning |
|---|---|---|
| 0 | 1 | page type: 2=int-index, 5=int-table, 10=leaf-index, 13=leaf-table |
| 1 | 2 | first freeblock offset (0 = none) |
| 3 | 2 | number of cells (N) |
| 5 | 2 | start of cell content area |
| 7 | 1 | fragmented free bytes |
| **leaf (10,13):** | | |
| 8 | 2N | cell pointer array (each is a page-relative cell offset) |
| **interior (2,5):** | | |
| 8 | 4 | rightmost child page number |
| 12 | 2N | cell pointer array |

## Cells

Leaf table (13): `varint(payload-size P) varint(rowid) record`.
Leaf index (10): `varint(P) record` (no rowid).
Interior table (5): `int32(left-child-page) varint(rowid-key)`.
Interior index (2): `int32(left-child-page) varint(P) record`.

## Record format

`record = varint(header-size H) H-1 serial-type varints payload-bytes`.
`H` counts the header-size varint itself plus all serial-type varints. The
payload is exactly `sum(size(serial_i))` bytes; for a table-leaf cell that sum
must equal `P` (payload generally = record bytes).

### Serial types

| code | size | decode |
|---|---|---|
| 0 | 0 | NULL |
| 1 | 1 | signed 8-bit |
| 2 | 2 | **signed** 16-bit big-endian |
| 3 | 3 | signed 24-bit |
| 4 | 4 | **signed** 32-bit big-endian |
| 5 | 6 | signed 48-bit |
| 6 | 8 | signed 64-bit |
| 7 | 8 | IEEE-754 float64 (`struct.unpack('>d')`) |
| 8 | 0 | integer 0 |
| 9 | 0 | integer 1 |
| 10,11 | — | reserved (flag as corrupt when seen) |
| ≥12 even | (st−12)/2 | BLOB |
| ≥13 odd | (st−13)/2 | TEXT (decode per DB encoding, UTF-8 by default) |

Text ≤ 0x7f-odd and blob lengths: e.g. serial 0x15 = 4-byte text, 0x21 =
10-byte text, 0x12 = 3-byte blob.

### Payload overflow ("spill")

If the payload does not fit (`P > U - 35`), the cell keeps local byte count
`K = M + ((P - M) % (U - 4))` where `M = ((U - 12) * 32 // 255) - 23`, stores the
first K payload bytes then a 4-byte next-page number. Overflow pages: 4-byte
next-page number (0 terminates) followed by `U - 4` payload bytes. For
recovery it is enough to know: local payload bytes run to 4 bytes before the
next cell/page boundary; the rest concatenates from the chain.

## sqlite_schema rows (page 1)

One row per object: `(type TEXT, name TEXT, tbl_name TEXT, rootpage INTEGER,
sql TEXT)`. User tables have type "table", name != "sqlite_schema". The
rootpage number is the entry point of the table's btree. Schema rows follow the
same record format; they are data, never output rows.

## Index and alias quirks

- Index btrees store `(key-columns..., rowid)` with NO rowid varint in cells.
- `INTEGER PRIMARY KEY` makes the column an alias of the rowid: it is NOT in the
  payload (or is stored as NULL for AUTOINCREMENT tables — byte-faithful NULLs).
- `sqlite_sequence` table may exist; exclude it unless the task asks for it.
- Freelist pages hold garbage; btree walks never reference them, and byte
  scanners should treat them as noise.

## Damage signatures (what to look for)

| symptom | interpretation |
|---|---|
| file shorter than `page_size * n_pages` | truncation; tail pages lost |
| long zero runs where cells should be | zeroed/truncated-then-padded region |
| isolated bytes equal to 1,2,4,8,0x10,0x20,0x40,0x80 in otherwise-zero regions | bit flips of zero bytes (corruption noise, ignore) |
| single structural byte breaking an otherwise consistent cell/page | 1-bit flip in a header field (repair candidate) |
| valid cells whose text/fill is NUL-padded | content zeroed but headers intact (flag partial) |
| ncell/ptrs intact but a cell at a ptr unparsable | damaged cell pointer (scan nearby offsets) |
| page header all zeros | page structure destroyed (use record scanning) |