---
name: sqlite-db-truncate
description: >-
  Recover logically valid rows from damaged, truncated, zeroed, or bit-flipped
  SQLite database files when ordinary queries (sqlite3, integrity_check,
  .recover) fail, and serialize the recoverable records as JSON using the
  case-specific public schema. Combines intact SQLite behavior with raw
  page, record-header, varint, serial-type, integer/float/text, overflow-chain,
  and fragment analysis, via a bundled tolerant parser
  (scripts/recover_sqlite.py).
---

# sqlite-db-truncate: recovery from damaged SQLite storage

## Family definition (from spec.yaml, grounded by train/v01)

**Invariant.** Recover *logically valid rows* from damaged SQLite storage when
ordinary queries are insufficient, and serialize the recoverable records using
the **case-specific public JSON schema** (in v01: `[{"word": "...", "value": N},
...]` written to `/app/recover.json`).

**Evidence boundary.** Recovery may combine intact SQLite behavior with raw
page, record-header, varint, serial-type, text, integer, float, and fragment
analysis. You do NOT need the file to be readable by sqlite3 — your parser is
the recovery tool.

**Variation axes** (expected to differ per case — the skill must cover all):
1. `corruption_mechanism` — truncation, zeroed regions, random byte flips,
   damaged page structures, split fragments requiring reassembly.
2. `schema_and_value_encoding` — table count, column order, serial types,
   NULLs, integers, IEEE-754 floats, text, records crossing page boundaries
   (overflow pages).
3. `record_identification` — textual keys, numeric keys, multiple interleaved
   table signatures, partially damaged headers.
4. `recovery_scale` — a few rows in one 2-column table up to hundreds of rows
   and several related tables (multi-page b-trees; v01 is the small end).

**Anchor evidence (v01, direct).** `/app/trunc.db` was an 8 KB / 2-page DB
(created by Python 3.11's bundled SQLite 3.41.2). Table `test(word TEXT,
value REAL)` with 8 rows `testword02..testword09`. Ordinary queries failed with
"database disk image is malformed" because random bit flips had hit three
structural bytes:
  * page-1 (sqlite_master) cell-content-start low byte `0xc5` (should be `0xc1`)
  * sqlite_master record serial type `0x5b` (should be `0x5f`; sql text length)
  * data cell serial type `0x61` (should be `0x21`; a text length)
Fixing those three single bits made `PRAGMA integrity_check` return `ok` and
gave exactly 8 rows: values 10, 25, 42, 50, 75, 99 (int8), 99.99, 0.5 (float64).
The hundreds of other flipped bits lay in already-free space (single-bit
values like 0x01/0x02/0x80 in otherwise-zero regions) and were harmless.
`sqlite3 .recover` recovered nothing; manual parsing recovered everything.

## Running the skill in a fresh evaluation container (read this first)

Inside the isolated `/app` task container:

* The frozen skill package is mounted **read-only at `/skill`**:
  `/skill/SKILL.md`, `/skill/scripts/recover_sqlite.py`,
  `/skill/scripts/self_test.py`.
* The host-workspace path you see with the `read` tool (e.g.
  `.../workspace/skill/sqlite-db-truncate/scripts/recover_sqlite.py`) does
  **NOT exist inside `task_shell`** — invoking it there fails with
  `python3: can't open file ... No such file or directory`. Do not retry;
  use `/skill/...` instead.
* If `/skill` is somehow absent, locate the package with:
  `find / -maxdepth 4 -name recover_sqlite.py 2>/dev/null` (and read
  `SKILL.md` next to it).
* In the host authoring workspace the same files live at
  `skill/sqlite-db-truncate/...` (read/write via host tools only).

## Workflow

1. **Read the task**: DB path, expected output path, and the example JSON
   schema (column names/order, value types). In v01: `/app/trunc.db` ->
   `/app/recover.json`, keys `word`/`value`.
2. **Fast routes first** (cheap wins):
   ```
   file DB; sqlite3 DB ".tables"; sqlite3 DB "PRAGMA integrity_check;"
   sqlite3 DB ".dump"            # writable_schema quirks sometimes read partial data
   sqlite3 DB ".recover"         # built-in CLI recovery (often finds nothing; try anyway)
   ```
   If any route yields rows, still cross-check counts with the parser below.
3. **Header triage** (pure Python / `xxd`):
   offsets (all big-endian): page size @16 (value 1 => 65536), write/read
   versions @18-19, reserved space @20 (usable = page_size - reserved), page
   count @28, freelist trunk @32, schema cookie @40, schema format @44, text
   encoding @56 (1=UTF-8). Compare `page_count * page_size` with file size:
   smaller file => **truncated** (parse only pages physically present; a
   trailing PARTIAL page is still parsed and scanned — its low-offset cells
   can hold whole records); page count != file implies padding.
4. **Run the bundled tolerant parser**:
   ```
   python3 /skill/scripts/recover_sqlite.py DB OUT.json     # in the task container
   python3 /skill/scripts/recover_sqlite.py DB --inspect    # per-page diagnostics
   python3 /skill/scripts/recover_sqlite.py DB --probe      # header diagnostics only
   ```
   The script (stdlib-only) walks b-tree pages (rowid AND WITHOUT ROWID
   tables), decodes records, repairs one/two-bit serial-type flips by length
   re-checking, follows overflow chains, routes TEXT decoding through the
   header's encoding (UTF-8/UTF-16le/BE with byte-order fallback), restores
   INTEGER PRIMARY KEY values from rowids, maps columns from `CREATE TABLE`,
   and falls back to a byte-level record scan when page headers/pointers are
   destroyed. stderr reports rows per table.
5. **Tune for hard cases**:
   `--columns a,b,c` when sqlite_master itself is destroyed (fallback emits
   positional `col0..colN`), `--lenient` to rescue truncated-by-damage text,
   `--min-text 0.6` to relax the printable-text sanity gate. Work through
   `--inspect` output: verify each page type/ncell/pointers against the raw
   hex before trusting the scan.
6. **Cross-check and validate output**:
   * Repair obvious single-bit errors in a COPY and run `sqlite3
     PRAGMA integrity_check` + `SELECT` — if sqlite agrees, your values are
     right. For the v01 anchor the 3 damaged bytes and their file offsets are
     known; patch them in a COPY (never the original) with this canary:
     ```python
     d = bytearray(open('copy.db','rb').read())
     assert d[105:107] == bytes([0x0f, 0xc5]) and d[106] == 0xc5
     d[106] = 0xc1          # page-1 btree content-start low byte: 0x0fc5 -> 0x0fc1
     assert d[4040] == 0x5b
     d[4040] = 0x5f         # sqlite_master sql serial type (cell starts @4033)
     assert d[0x1ff3] == 0x61
     d[0x1ff3] = 0x21       # first data-cell serial type: text len 42 -> 10
     ```
     then `sqlite3 copy.db "PRAGMA integrity_check;"` -> `ok` and
     `SELECT rowid,word,value FROM test;` -> exactly the 8 rows. NOTE the
     offsets are page/encoding-specific: for any OTHER instance, derive them
     from `--inspect` + `xxd` instead of assuming the anchor's numbers (both
     eval solvers lost several steps asserting the wrong byte at 105 vs 106
     — content start is bytes 105-106, the LOW byte is at 106).
   * Every emitted row must decode exactly (declared payload length == header
     + consumed values), dedupe rowid tables by rowid and WITHOUT ROWID
     tables by value tuple, and match the task's key naming (e.g.,
     `testword\d+`).
   * Match the example's JSON format precisely: list of objects, keys in the
     same order; ints where SQLite stored ints, floats where it stored
     floats (Python `10 == 10.0`, but mirror storage anyway).

## SQLite on-disk facts you must know (all verified on 3.41.2/3.46.1)

**File header** (page/btree-relative offsets below are within each page;
page 1's b-tree header starts at byte **100**, other pages at 0).

**B-tree page header** (8 bytes):
```
0   type: 2 interior-index | 5 interior-table | 10 leaf-index | 13 leaf-table
1-2 first freeblock (BE16)         3-4 cell count (BE16)
5-6 cell content start (BE16!)     7 fragmented free bytes
8+  cell pointer array (BE16 each); INTERIOR pages keep the 4-byte
    right-most child page number at 8-11 and start the pointer array at 12.
```
(Pitfall: content start is **2 bytes**, not 3; interior pages shift the
pointer array by 4 bytes. Getting this wrong corrupts every offset.)

**Cells**:
* leaf table (rowid table): `[payload-len varint][rowid varint][record]`
* leaf index / WITHOUT ROWID leaf: `[payload-len varint][record]` (NO rowid,
  and interior cells are `[4-byte left-child page][key RECORD]`; walk only
  needs the child page number)
* interior (5/2): `[4-byte left-child page][key]` (walk children; also push
  the right-most child).
Cells are stored from the page tail downward; the pointer array stays at the
top, so **cells at the end of a page and the pointer array usually survive
even when the page middle is zeroed**.

**WITHOUT ROWID tables**: sqlite_master still lists them with
`type='table'`, but their root pages are index b-trees (2/10) and rows have
no rowid — key recovered rows by their record values, not by rowid or they
collapse to one row. Detect via `WITHOUT\s+ROWID` in the SQL or the root
page type.

**Records**: `[header-size varint][serial types varints][values]`.
Serial types: 0=NULL(0 B); 1/2/3/4/5/6 = int8/16/24/32/48/64 with sizes
**1,2,3,4,6,8**; 7=float64(8 B); 8=integer 0 (0 B); 9=integer 1 (0 B);
10/11 reserved; even >=12 blob `(t-12)/2`; odd >=13 text `(t-13)/2`.
Values are big-endian; int24/int48 sign-extend. NULL has **zero** content
bytes — a parser that treats a `None` decode as "failed" loses every row
with a NULL column (all-NULL records are `[05 00 00 00 00]`).
Text lengths count BYTES in every encoding; only the decode step depends on
header bytes 56-59 (1=UTF-8, 2=UTF-16le, 3=UTF-16be). The length-accounting
repair machinery is therefore encoding-proof, and the text sanity gate must
only consider TEXT-typed values (blob values are hex strings and would fake
it).

**Overflow (records crossing pages)**: when payload R > M = usable-35 (leaf
table), part stays local and the rest is chained through overflow pages
(page = `[4-byte next page][payload bytes]`). Verified rule at usable 4096:
`x = R mod (usable-4)`; local = x if `m <= x <= M` else `m`, where
`m = ((usable-12)*32//255)-23`. **Always verify** by following the chain and
requiring it to supply exactly `R - local` bytes (the bundled script scans
for candidate pointers and validates the chain, so it tolerates formula
differences on other page sizes).

**INTEGER PRIMARY KEY quirk**: the record stores **NULL** for the rowid-alias
column; the real value lives in the cell's rowid varint. Restore it when
serializing (the script does this automatically).

**sqlite_master**: root page 1; rows `(type,name,tbl_name,rootpage,sql)`.
The root page itself can be interior for big schemas — walk it, don't assume
leaf. Filter `type == 'table'`; ignore indexes/triggers for row output.

## Corruption tactics per axis

* **Random bit flips** (v01; most likely official mechanism): the file stays
  structurally coherent; a handful of flips land in critical bytes (page
  headers, serial types) and the rest in free space. Recover by tolerant
  length-consistent parsing: whenever `sum(serial sizes) != payload_len -
  header_size`, try flipping each serial-type byte by one bit (then two, for
  records with <= 16 columns) and accept the first candidate that makes
  lengths exact and text printable. Content flips *inside* text/numbers are
  undetectable (they still parse): emit them as valid rows — nothing better
  is possible.
* **Truncation**: parse only pages present; skip missing children; report the
  header/file page mismatch; rows on surviving pages are still recoverable.
  File-pages arithmetic must be **ceil, not floor**: a file cut MID-page
  still carries a partial final page whose low-offset cells (and usually the
  pointer array, at the page top) survive — floor would silently drop the
  entire partial page. The scan covers the partial tail; cells whose bytes
  were cut away simply fail length checks.
* **Zeroed regions**: pointer array + page tail generally survive; if
  pointers/headers are destroyed, byte-scan each page for self-consistent
  records in BOTH cell layouts (rowid-style and index-style). Skip the first
  100 bytes of page 1 (file header contains plausible garbage).
* **Damaged page structures**: treat unknown page-type bytes as unreadable;
  let the scan recover their cells; use `--inspect` to see which pages fail.
* **Overflow chains (records crossing page boundaries)** — the SCHEMA axis
  "records that cross pages": follow validated overflow chains; for
  partially zeroed chains, `--lenient` salvages the local portion (mark
  partial rows for human review).  This is DIFFERENT from file-level
  fragmentation below.
* **Split fragments (file-level reassembly)** — the CORRUPTION axis
  "split fragments that require reassembly": the artifact arrives as two
  or more byte-range pieces (page-shuffled, page-dropped, or cut
  mid-page), and usually NO file starts with `SQLite format 3\0`.  Rebuild
  before parsing:
  1. **Inventory** (`ls -la` the artifact dir; check magic per file) — a
     fragment case announces itself: multiple files, a "data" file, or a
     concatenation whose page count mismatches its content.
  2. Run the parser — it now never dies with a bare traceback: pass every
     piece as a positional + `--pieces f1 f2 ...` (or just the first file;
     a single shuffled file of whole pages is handled automatically via
     page-bag backtracking).  stderr reports `# piece ...` for each file
     and `# fragment reassembly: page_size=... rows=... missing={...}`.
  3. Internally: the piece with the magic anchors page 1 (its bytes 16-17
     fix page_size); candidate assemblies = orderings of the remaining
     pieces (+ as-given concatenation for mid-page cuts); each candidate
     is scored ONLY by internal consistency — pointer-graph walkability
     (reachable pages with sane b-tree headers of type {2,5,10,13}, capped
     ncell, in-bounds content start, and cells that parse).  For a single
     shuffled file, every page-size window is a physical page and slots
     are assigned by backtracking constrained by the same sanity rules and
     the sqlite_master root types.  Dropped chunks leave holes (missing
     pages reported; surviving physical rows still recovered, exactly like
     truncation).  `missing={...}` names referenced-but-absent pages.
* **WITHOUT ROWID tables**: sqlite_master still says `type='table'`, but the
  root is an index b-tree (types 2/10) and leaf cells have NO rowid varint:
  `[payload-len varint][record]` (interior: `[4-byte child][key record]`).
  Detect via `WITHOUT ROWID` in the SQL **or** root page type 2/10; collect
  rows as a list keyed by value tuple (do NOT key by rowid — every row would
  collapse onto `None`). The byte-scan also tries the index layout, so
  WITHOUT ROWID rows survive destroyed pointers.
* **Text encoding**: header bytes 56-59: 1=UTF-8, 2=UTF-16le, 3=UTF-16be.
  Serial-type lengths count BYTES (encoding-proof); only decoding needs
  routing. Decode all TEXT (records and schema) with the declared codec;
  if the declared order yields unprintable text (e.g., a bit-flipped header
  byte), retry the swapped UTF-16 flavor; a fallback codec is only trusted
  when every decoded text value is ASCII-dominant (real UTF-16 keys/DDL are
  ASCII; UTF-16 mis-decodes of arbitrary bytes yield high-Unicode garbage).
* **Attribution before acceptance (the same-arity rule)**: a scanned
  candidate's arity may *admit* it; it never decides *which table owns* it.
  First map every page to its owner via `tree_pages(root)` (a separate
  traversal that does not depend on cells parsing, so zeroed-pointer
  pages keep their owner). A page reachable from exactly one root is
  owned: its scanned candidates go to that table only (same cell layout,
  same arity, plausible offset >= min(content-start, surviving pointers),
  and highest declared-type-compatibility parse per key). This makes
  same-arity multi-table databases exact even with ZERO corruption — the
  old arity-first code silently appended beta's rows into alpha whenever
  alpha's rowids did not collide.
* **Orphan pages** (unreachable from any root): keep the page's DOMINANT
  (kind, arity) group (shifted over-parses of other arities are noise),
  compute a page-level per-column serial-family signature (union across
  the page), and score candidate tables by declared column types
  (type tokens from CREATE TABLE; NULL fits everywhere; REAL accepts
  {float, int}). Unique perfect match -> attribute the whole page, loudly;
  tie or no match -> warned `orphan-N-col` group, never silent merges.
* **No-schema fallback**: cluster PAGES by (kind, arity, page-level
  signature) and key rows by (page, rowid) so cross-table rowid
  collisions never drop rows; same-arity tables with different value
  shapes (e.g. TEXT+REAL-float vs TEXT+INTEGER) stay separate. Note SQLite
  stores integer-valued REALs (0.0, 1.0) as int serial types, so
  per-COLUMN signatures must be unions (per-candidate signatures
  fragment one table into 'float' and 'int' groups).
* **Multiple/interleaved tables**: recover each table from its root; when
  pointer-walk fails, attribute by page ownership, then by signature;
  if the whole schema is gone, fall back to positional `col0..colN` and
  rename via `--columns`. Verify against known key signatures from the
  task text.
* **Scale**: the parser handles interior pages, hundreds of cells, and
  multiple pages (verified: 600 rows across 6 pages, page sizes
  4096/1024/512, plus an index table, all recovered 100%).

## The audit rule (encode this in every future change)

For every parsing decision ask: *"if the input is a valid member of this
family but violates this assumption, do I emit a wrong answer quietly?"*
If yes, convert the assumption into explicit detection + handling, or a
loud failure on stderr. The failure modes below were exactly such silent
total failures until they were tested: WITHOUT ROWID (all rows collapse to
one), UTF-16 databases (empty output, no diagnostic), reserved-space files
(every overflow read misaligned), pure-integer tables with destroyed
pointers (zero recall), and — the counterexample inside `recover_scan`
itself — arity-first scan attribution, which merged same-arity tables'
rows on a fully INTACT database (two 2-column tables, zero corruption:
beta's rows 11-40 silently appended into alpha under alpha's column
names). Attribution must precede acceptance: page ownership first,
column-type signatures for orphan pages, and (page, key) keys in
no-schema mode so genuine rowid collisions never drop rows. The final
axis — split fragments — had the same shape: a bare `ValueError` traceback
with no next step; it now inventories pieces, tries orderings/page-bags,
scores candidates by pointer-graph consistency, and emits a loud
`missing={...}` report with partial recovery when a chunk is gone. Guard
all of this with the regression suite in `scripts/self_test.py`: the
12-case {rowid, WITHOUT ROWID} x {UTF-8/16le/16be} x {intact, zeroed-ptrs}
grid, same-arity intact / zeroed-ptrs, orphan-page, no-schema clustering,
numeric keys, four fragment cases, each asserting the EXACT expected row
set.

## Evidence & confidence labels

* **v01-direct**: the 3-bit-fix anchor analysis, row values, page layouts,
  sqlite3/.recover behavior, IPK NULL quirk, `(usable-35)` threshold.
* **Empirically verified here**: interior-page pointer offset 12; int48=6 /
  int64=8 sizes; serial 8/9 zero-byte values; the overflow split rule
  (`R mod (usable-4)` clamped with `m`) across R = 4060..100000 at usable
  4096 (SQLite 3.41.2, page sizes 512/1024/4096); multi-page walk, truncation
  (whole-page and mid-page, exact row sets), zeroed pointers, destroyed
  schema, 0.3% random flips (the missing rows had flips in value bytes, i.e.
  genuinely unrecoverable; the rest decode logically valid).
* **Empirically verified via the self-test suite**: all 19 groups pass in
  a fresh container (see `scripts/self_test.py`): 12-case
  {rowid, wr} x {UTF-8/16le/16be} x {intact, zeroed-ptrs} grid; reserved-space
  usable; whole-page and mid-page truncation; 8000-char overflow; NULL/blob/
  bigint/tinyfloat values; two tables; INTEGER PRIMARY KEY; 600-row interior
  b-tree; deterministic free-space + serial-type-bit flips; SAME-ARITY
  two-table intact (the regression that failed on arity-first attribution);
  same-arity with beta's pointers zeroed; orphan-page attribution with a
  warned orphan group; no-schema shape clustering into two groups; pure-
  numeric rowid + WITHOUT ROWID tables under zeroed pointers; and four
  FRAGMENT cases: permuted chunk files via --pieces (700/700), a single
  shuffled file via page-bag reassembly (700/700), a dropped middle chunk
  (surviving rows exact + missing-page report), and a mid-page cut between
  two in-order pieces (500/500).  Every case asserts the EXACT expected
  row set.
* **Reasoned extrapolation (not locally exercised)**: exact overflow constants
  for page sizes other than 512/1024/4096 (mitigated by chain validation);
  STRICT tables (trailing clause handled in column parsing); BOM-prefixed
  UTF-16 text (stripped defensively).

## Failure modes / pitfalls checklist

- [ ] scan prefilter capped at 250: 2-byte payload varints (records >= ~15.7
      KB) start with a byte >= 0xFB and are invisible to the scan; allow
      0..255 and keep the pl <= 300 candidate bound.
- [ ] cross-check repairs applied at guessed offsets: v01's three damaged
      bytes live at file offsets 106 (0xc5->0xc1), 4040 (0x5b->0x5f),
      0x1ff3 (0x61->0x21); any other instance: derive from --inspect/xxd.
- [ ] scan attribution by arity only (a candidate offered to every
      same-arity table): same-arity tables cross-contaminate even on
      INTACT databases; attribute by page ownership first (tree_pages
      must not depend on cells parsing), then type-signature for orphans.
- [ ] per-candidate serial signatures in no-schema mode: integer-valued
      REALs store as int serials, so one table fragments into float/int
      groups; use per-page column-family UNIONS and cluster pages.
- [ ] rows keyed by rowid in no-schema mode: distinct tables sharing a
      rowid drop rows; key by (page, rowid).
- [ ] scan dedupe by first-seen: shifted over-parses can shadow the real
      cell; prefer highest declared-type compatibility, then highest
      offset.
- [ ] skill resources invoked via the host-workspace path inside `task_shell`
      (fails with "can't open file"); inside the container use `/skill/...`,
      in the host workspace use `skill/sqlite-db-truncate/...`.
- [ ] file-pages computed with floor: a mid-page truncation silently drops
      the entire partial last page (use ceil and scan the partial tail).
- [ ] content-start read as 3 bytes (must be 2) / interior pointer array read
      at 8 (must be 12): every offset after that is garbage.
- [ ] WITHOUT ROWID cells keyed by rowid (they have none): all rows collapse
      to one; key index-btree rows by their value tuple and emit every row.
- [ ] text decoded as UTF-8 in a UTF-16 database: schema text turns to ~50%
      NULs, both gates reject it, output is silently empty; route decoding
      from header bytes 56-59 with swapped-order fallback.
- [ ] fallback codec trusted without ASCII-dominance: UTF-16 mis-decodes of
      arbitrary bytes look printable and pollute output.
- [ ] blob values (hex strings) counted as "text" by the sanity gate.
- [ ] reserved-space byte (header offset 20) ignored: usable must be
      page_size - reserved for every overflow body slice.
- [ ] serial type 5 (int48) sized 5 instead of 6; type 6 sized 6 instead of 8.
- [ ] serial 8/9 consume 0 bytes but produce values 0/1.
- [ ] NULL values treated as decode failures (all-NULL rows vanish).
- [ ] scan loop `range(len(page)-9)` skips cells at the page end.
- [ ] unknown-schema scan without a text/float signal gate (free-space/
      header noise) OR known-schema scan with the gate (pure-integer tables
      lost).
- [ ] trusting the classic overflow formula without chain verification.
- [ ] assuming sqlite_master is on a leaf page, or assuming its own text is
      UTF-8.
- [ ] forgetting INTEGER PRIMARY KEY lives in the rowid, not the record.
- [ ] O(n^2) repair passes run on garbage scan offsets: cap type count (64)
      and the two-bit pass (<= 16 types) to keep scans linear-ish.
- [ ] assuming `sqlite3 .recover` will do the job (in v01 it returned an
      empty schema).

## Future verification procedure (unseen cases)

1. Generate a clean DB with the case's schema/rows (sqlite3 CLI or Python).
2. Apply the suspected corruption (truncate file, zero a region, flip `k`
   random bits, destroy page headers) — or just use the damaged file.
3. Run `recover_sqlite.py`; compare recovered JSON against the known rows
   (exact set equality) and confirm every emitted row decodes exactly.
4. Run `scripts/self_test.py` — the self-contained regression suite builds
   its own fixtures and asserts exact row sets for: the 12-case
   {rowid, WITHOUT ROWID} x {UTF-8, UTF-16le, UTF-16be} x {intact, zeroed
   pointer arrays} grid, reserved-space usable, whole-page and mid-page
   truncation, overflow records, NULL/blob/bigint/tinyfloat values, two
   tables, INTEGER PRIMARY KEY, a 600-row interior b-tree, deterministic
   bit flips, same-arity intact / same-arity zeroed-ptrs, orphan-page
   attribution, and no-schema shape clustering. It must pass before
   shipping any parser change.
5. For each spec axis not exercised by the current case, simulate the axis
   locally (e.g., overflow text, NULLs, second table, 1024-byte pages) and
   record the result; if a formula constant differs, update this doc.

## Package layout

- `SKILL.md` — this guide.
- `scripts/recover_sqlite.py` — stdlib-only tolerant parser/recovery tool
  (importable too: `SQLiteReader(DB).recover_tables()`,
  `parse_record(payload)`).
- `scripts/self_test.py` — self-contained regression suite (19 groups,
  exact-set assertions, exits non-zero on any failure; run with
  `python3 /skill/scripts/self_test.py` in a fresh container).