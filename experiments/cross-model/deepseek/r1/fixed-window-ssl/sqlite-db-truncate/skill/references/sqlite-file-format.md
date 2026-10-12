# SQLite on-disk file format — tested reference

Facts below were verified against real bytes during the v01 recovery
(2-page, 4096-byte-page database written by SQLite **3.41.2**) and against
synthetic test databases built with Python sqlite3 (3.46.1) inside the task
container.  Layout is stable across these versions; section "verified"
marks the evidence, section "extrapolated" flags rules reasoned from the
specification that were exercised only synthetically.

## 1. Database header (first 100 bytes of the file)

| offset | size | field | v01 value |
|---|---|---|---|
| 0 | 16 | magic `"SQLite format 3\0"` | `53 51 4c 69 74 65 20 66 6f 72 6d 61 74 20 33 00` |
| 16 | 2 | page size (big-endian; 1 ⇒ 65536; power of two, 512..65536) | `10 00` = 4096 |
| 18 | 1 | file format write version (1 legacy, 2 WAL) | 1 |
| 19 | 1 | file format read version | 1 |
| 20 | 1 | reserved bytes per page (for extensions) | 0 |
| 21 | 1 | max embedded payload fraction | 0x40 (64) |
| 22 | 1 | min embedded payload fraction | 0x20 (32) |
| 23 | 1 | leaf payload fraction | 0x20 (32) |
| 24 | 4 | file change counter | 2 (bytes `00 00 00 02`) |
| 28 | 4 | size of database in pages (legacy) | 2 |
| 32 | 4 | first freelist trunk page | 0 |
| 36 | 4 | total freelist pages | 0 |
| 40 | 4 | schema cookie | 1 |
| 44 | 4 | schema format number | 4 |
| 48 | 4 | default page cache size | 0 |
| 52 | 4 | largest root btree page | 0 (nonzero only under auto-vacuum) |
| 56 | 4 | text encoding (1=UTF-8, 2=UTF-16le, 3=UTF-16be) | 1 |
| 60 | 4 | user version | 0 |
| 64 | 4 | incremental vacuum mode | 0 |
| 68 | 4 | application id | 0 |
| 72 | 20 | reserved for extensions | zeros |
| 92 | 4 | version-valid-for (change counter at last valid write) | 2 |
| 96 | 4 | SQLite version number that last wrote (e.g. 3041002 = 3.41.2) | `00 2e 66 ea` |

Triage use: compare offset **28** (declared size in pages) against
`len(file)/page_size`.  If declared > actual, the file was truncated;
trailing rows are lost.  (Offset 36 is the freelist page count — unrelated
to the file's size; do not compare it against the file length.)
Header fields are dense and rarely flipped in this family; a flipped header
byte is usually visible as an absurd value (page size not a power of two,
etc.).

## 2. Btree page header

For page 1 the btree header starts at offset **100** (after the database
header); for every other page at the page offset.

| offset (rel. btree header) | size | field |
|---|---|---|
| 0 | 1 | page type: 0x02 index interior, 0x05 table interior, 0x0a index leaf, 0x0d table leaf, 0x00 overflow |
| 1 | 2 | first freeblock offset (page-relative), 0 = none |
| 3 | 2 | number of cells on the page |
| 5 | 2 | start of cell content area (page-relative) |
| 7 | 1 | fragmented free bytes |
| 8 | 4 | (interior pages only) right-most child page number |
| 8/12 | 2×n | cell pointer array: n cell offsets, page-relative, ascending key order |

Each cell pointer points at the **first byte** of the cell.  Cells are
stored packed from content_start upward in **descending key order**: the
first pointer (smallest key) is the highest address.

v01 page 2 example (verified): `0d 00 00 00 08 0f 72 00` then pointers
`0ff0 0fe0 0fd0 0fc0 0fb0 0fa0 0f89 0f72` → leaf table page, no freeblock,
8 cells, content area starts at 0x0F72 (page-relative).

## 3. Cell formats

Table-leaf cell (type 0x0d): `varint(payload length) varint(rowid) payload…`
— payload spills per §5; if it spills, a 4-byte big-endian first-overflow
page number follows the local payload.

Table-interior cell (type 0x05): `4-byte child page varint(payload length)
varint(rowid)` — no payload body stored on the page; the child page holds
all keys ≤ this cell's rowid.

Index-leaf cell (type 0x0a): `varint(payload length) payload` — no rowid;
the key **is** the payload (record of the indexed columns).  NOT decoded by
the recovery tool (see SKILL.md Limitations).

Index-interior cell (type 0x02): `4-byte child varint(payload length)
payload`.

## 4. Varint

Big-endian, 7 bits per byte, high bit set = another byte follows; the 9th
byte contributes 8 bits.  `0x81 0x01` → 129.

## 5. Record layout and serial types

Record payload (inside a table-leaf cell): `varint(H) serial1 serial2 …
bodies…`, where H = total record-header size **including the H varint
itself**, so the serial-type varints occupy H−1 bytes.  Check:
`payload_len == H + Σ body sizes` and the H varint's own length is
consistent — this arithmetic is the cheapest damage detector in the whole
format (v01: a flipped serial-type byte made Σ bodies = 59 vs payload 61,
instantly flagged).

| serial type | meaning | body size |
|---|---|---|
| 0 | NULL | 0 |
| 1..6 | signed big-endian integer | 1,2,3,4,6,8 |
| 7 | IEEE-754 double, big-endian | 8 |
| 8 | integer 0 | 0 |
| 9 | integer 1 | 0 |
| 10, 11 | reserved | — |
| even ≥ 12 | blob | (N−12)/2 |
| odd ≥ 13 | text (UTF-8) | (N−13)/2 |

**Affinity is not storage class** (verified).  `value REAL` in v01 held six
rows with serial type 1 (1-byte ints: 10, 25, 42, 50, 75, 99) and two rows
with serial type 7 (99.99, 0.5).  `typeof(value)` reported "real" on read
because column affinity converts on read — never infer stored serial types
from declared column types.

## 6. Overflow (records that cross page boundaries)

U = usable page size = page_size − reserved bytes.  For table-leaf pages:
X = U − 35.  If payload P ≤ X → entirely local.  Else (extrapolated from
sqlite btree.c; verified synthetically with a 9000-char value on 4096-byte
pages, P≈9003 → local≈819, remainder 8184 = 2 overflow pages):

- M = ((U − 12) × 32) // 255 − 23   (integer division; for 4096: 489)
- K = M + ((P − M) mod (U − 4))     (for 4096: 489 + (P−489) mod 4092)
- local = K (clamped to [0, P]; if K is out of range the page is corrupt)

The cell stores `local` bytes, then a 4-byte big-endian pointer to the first
overflow page.  Each overflow page: 4-byte big-endian next-page pointer
(0 = end) + up to U−4 payload bytes.  The record header/type stream simply
continues across overflow pages — reassemble the payload before decoding.

## 7. Structural invariants (compact pages: freeblock == 0, frag == 0)

- `cell_count == len(pointers) == number of decodable cells`.
- Cell 0 (first pointer) ends at the usable page end: `cell_len == usable −
  ptrs[0]`.
- Cell i (i ≥ 1) spans `[ptrs[i], ptrs[i−1])`: `cell_len_i == ptrs[i−1] −
  ptrs[i]`.
- `ptrs[-1] == content_start`.
- Sum: `Σ cell_lens == usable − content_start`.

v01 page 2 verified: 6×16-byte cells at 0xFF0..0xFA0, then 2×23-byte cells
at 0xF89/0xF72; gaps: 0x1000−0xFF0 = 16, 0xFF0−0xFE0 = 16 … 0xFA0−0xF89 =
23, 0xF89−0xF72 = 23; `0xF72 == content_start`; sum 142 == 0x1000−0xF72.
Note the gap between pointer i and i+1 equals the size of cell **i+1** when
sizes differ (16 and 23 mixed): the "gap == size of lower cell" formulation
is the correct one.

A "repair" that resolves a page to zero cells is rejected: hypotheses that
erase evidence are not repairs (this killed a false candidate that flipped
the cell-count byte, which made the tiling predicate pass vacuously).

## 8. sqlite_master record

One row per schema object, columns:
`type TEXT ('table'|'index'|'view'|'trigger'), name, tbl_name, rootpage
(INTEGER; 0 for views), sql`.  Rootpage for user tables points at the table
btree (type 0x0d/0x05 pages).

v01 schema cell (verified, after repairing its flipped serial-type byte):
`'table','test','test',2,'CREATE TABLE test (word TEXT, value REAL)'` —
payload 61 = header 6 (serial types 23,21,21,1,95) + bodies 5+4+4+1+41.

## 9. Rowid-alias columns (INTEGER PRIMARY KEY)

For a rowid table, a column declared exactly `INTEGER PRIMARY KEY` (alone,
optional `ASC`/`AUTOINCREMENT`, no `DESC`, table not `WITHOUT ROWID`) is a
rowid alias: its value is the **cell's rowid varint**.  The record still
**occupies a payload slot for it, holding serial type 0 (NULL)** —
verified on a 12k-row db where every record decoded as `[NULL, 'row…']`
with rowid = k.  Recovery rule: take the emitted value from the cell rowid
regardless of what the slot holds; if a nonstandard writer omits the slot
(`len(vals) == len(cols) − 1`), map positionally without consuming it.
Composite PRIMARY KEY, `INTEGER PRIMARY KEY DESC`, and WITHOUT ROWID tables
are not aliases.

## 10. Flip census (bit-level damage model)

Given a reference replica (identical schema/values/write pattern — v01's
original reproduced exactly this way):

- count bits where damaged=1, replica=0 → 0→1 flips (v01: **89**)
- count bits where replica=1, damaged=0 → 1→0 flips (v01: **1**,
  exactly the serial-type 0x5B←0x5F the repair found)
- p01 = 89 / ~64,700 zero bits ≈ **1.4e-3 /bit**; predicted 1→0 flips =
  842 replica-set bits × p01 ≈ **1.16** vs observed 1 → closed.

Damage here was **symmetric per-bit flips**, not additive noise — an
earlier "additive" hypothesis was falsified by the single cleared bit, and
the v01 byte-level census (930 set bits in the damaged file vs 842 in the
replica, out of 65,536 file bits; 342 of 8192 bytes nonzero) is how to
reproduce that reasoning on any case.

Writer/reader note: v01 was written by 3.41.2 (header bytes 96–99 =
0x002E66EA) and parsed with sqlite 3.46.1; the row format for this schema
was byte-identical, so the container's sqlite3 was a valid oracle.