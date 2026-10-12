---
name: sqlite-db-truncate
description: Recover logically valid rows from damaged SQLite storage (bit flips, zeroed regions, truncation, damaged b-tree/record structures, overflow splits) when ordinary queries fail, using a self-validating decoder of the SQLite on-disk format, and serialize the recoverable records to JSON per the case's public schema.
---

# SQLite damaged-database recovery

**Family invariant:** the input is a SQLite database file whose storage is
damaged (bits flipped, regions zeroed, file truncated, page/record structures
broken, records split across overflow pages) so that `sqlite3`/`sqlite3.connect`
fail ("database disk image is malformed"), but *recoverable rows still exist as
bytes*.  The job: recover as many logically valid rows as possible and write
them as JSON matching the case-specific public schema stated in the task (e.g.
`[{"word": "testwordXY", "value": M}, ...]`).

**What transfers between cases is not the row pattern — it is the self-validating
format decoder.**  Never just regex-hunt for expected strings; a string hunt
passes one case and dies on the next (numeric keys, interleaved tables, damaged
headers, floats, cross-page records).

---

## 1. The SQLite on-disk contract (all multi-byte values big-endian)

- **File header (100 bytes, offsets 0x00–0x63).** `"SQLite format 3\0"` @0;
  page size @16 (value 1 means 65536; otherwise a power of two 512..65536);
  write/read versions @18/19; reserved bytes per page @20; max/min/leaf payload
  fractions @21/22/23; file change counter @24; page count @28; schema cookie
  @40; schema format @44; text encoding @56 (1=UTF-8, 2=UTF-16le, 3=UTF-16be);
  bytes @96–99 (version-valid-for) and the reserved region @64–95 may contain
  junk after corruption — **ignore everything except page_size, page count,
  reserved, encoding** (and even those may need verification/forcing).
- **Page layout.** Page N occupies file bytes `[(N-1)*page_size, N*page_size)`.
  *Page 1 is special: its 100-byte b-tree header starts at file offset 100,
  not 0.*  Usable size `U = page_size - reserved`.
- **B-tree page header (8 bytes):** page type @0 (`2` interior index, `5`
  interior table, `10` leaf index, `13` leaf table); first freeblock @1 (2B);
  cell count @3 (2B); cell-content start @5 (2B); fragmented free bytes @7.
  **cell-content start is a hint, never a trust boundary** — a flipped
  content_start must not cause valid cells to be rejected (v01 had exactly
  this: content_start 0x0fc5 vs valid cell pointer 0x0fc1, one bit apart).
  Interior pages add a 4-byte right-most child pointer at offset 8; the cell
  pointer array (2-byte page-relative offsets, one per cell) follows the header
  (offset 8 for leaf, 12 for interior).
- **Table-leaf cell:** `varint(payload_length)` then `varint(rowid)` then the
  record.  **Table-interior cell:** 4-byte left-child page number + `varint(rowid)`;
  no record (recurse into children, plus the right-most pointer).
- **Record:** `varint(header_length)` — **the header length counts ITSELF**, so
  the header region (length varint + serial-type varints) ends at
  `record_start + hlen` and the packed values begin there.  An off-by-one here
  silently corrupts every record parse (this bit the original scaffold too and
  was caught by exact-length validation on the schema record: hlen=6 with five
  serial types).
- **Serial types:** `0`=NULL; `1..4`=signed big-endian int of 1/2/3/4 bytes;
  `5`=6-byte int; `6`=8-byte int; `7`=8-byte IEEE-754 big-endian float;
  `8`=constant 0, `9`=constant 1 (zero payload bytes); even `n>=12`=BLOB
  `(n-12)/2` bytes; odd `n>=13`=TEXT `(n-13)/2` bytes.  Negative values are
  sign-extended from the raw bytes.
- **Overflow (records crossing page boundaries):** for a table leaf,
  `X = U - 35`; `M = ((U-12)*32//255) - 23`.  If `P <= X`, the payload is fully
  local.  Otherwise compute `K = M + (P - M) % (U - 4)`; the local size is
  **`K` if `K <= X`, else `M`** (the X-cap — this is btree.c
  `btreeParseCellPayload`: `surplus = minLocal + (nPayload-minLocal) %
  (usableSize-4); nLocal = surplus <= maxLocal ? surplus : minLocal`).  The
  local size never exceeds X; the valid range is **[M, X]** (not [M, M+U-5)).
  The cell then holds `L` payload bytes plus a 4-byte next-overflow-page
  number at `payload_start + L`; each overflow page = 4-byte next pointer + up
  to `U-4` payload bytes.  Reassemble, then parse the record from the
  reassembled payload (the record header starts the payload).  For
  interior/index pages use `X = ((U-12)*64//255) - 23` with the same `M` and
  the same cap.
  - **Divergence-band symptom:** a decoder that omits the X-cap reads the
    overflow pointer at `payload_start + K` instead of `payload_start + M` for
    payloads in the bands where `K > X` (U=512: P in [986,1054]+508k; U=4096:
    P in [8154,8672]+4092k), hitting zeros/garbage or EOF and dropping
    *perfectly healthy* rows with "failed exact decode"/"overflow payload too
    short" NOTES.  If healthy large-text rows vanish, suspect the local-size
    rule and re-check with the pointer-position oracle: at `payload_start +
    candidate_L` there must be a 4-byte valid page number whose page continues
    the payload text, and the reassembled record must parse exactly.
- **Value-encoding gotchas observed in practice:**
  - A column declared `INTEGER PRIMARY KEY` is the rowid: the record stores
    **NULL** (serial 0) in that column — the real value lives in the cell's
    rowid varint.  `recover_sqlite.py` repopulates such columns from the cell
    rowid so the emitted JSON matches what `SELECT *` returns (this also makes
    the L3 dump-equality rung compare equal).
  - `REAL`-affinity columns store integral values as **INTEGER serial types**
    (an optimization) but `typeof()` still reports `real` when read.
  - SQLite stores the constant 0 as serial type 8 and 1 as serial type 9, not
    as 1-byte ints.
  - `sqlite_master` rows are invariantly 5 values with kinds
    `[text, text, text, int, text]`; the sql column starts with `CREATE`; for
    tables it parses as `CREATE TABLE name (col TYPE, ...)` and rootpage is a
    small page number in `[1, max_page]`.  These invariants are powerful
    tie-breakers when several single-bit repairs fit.

## 2. What varies across the family (spec axes)

| Axis | Expected variation | Handling |
|---|---|---|
| corruption mechanism | bit flips, zeroed regions, truncation, damaged page structures, split fragments | intact-first + structural decode + byte-offset carving; truncation = stop at EOF; zeroed regions = cells simply fail exact validation and are skipped |
| schema & value encoding | table count, column order, serial types, NULL/int/float/text, cross-page records | schema from sqlite_master; column-order mapping via CREATE TABLE parse; overflow reassembly; `--columns` fallback when schema is destroyed |
| record identification | textual keys, numeric keys, interleaved table signatures, damaged headers | schema-aware walks per rootpage; `--key-regex col:pattern` validation; single-bit header repair with layered picking |
| recovery scale | 2-column pairs to hundreds of rows / several tables | linear scans, per-row exact validation, dedup by full value tuple |

## 3. Workflow

1. **Try intact behavior first:** `sqlite3 FILE ".recover"` — the CLI forensic
   dumper.  Harvest whatever it prints (often nothing when the schema page
   itself is damaged, as in v01).
2. **Read the task's public JSON schema** (column names/order/types) — it tells
   you the target shape and usually a key pattern (e.g. `word=^testword\d+$`).
3. **Structural decode** (schema-first): run the decoder
   `python3 /skill/scripts/recover_sqlite.py FILE --repair-bits --out recover.json --out-patches patches.json`
   (in the task container the read-only package is mounted at `/skill`; scripts
   live in `/skill/scripts/`).  It walks page 1's sqlite_master b-tree (with
   single-bit repair + invariant picking), obtains `CREATE TABLE` column lists
   + rootpages, walks each declared root b-tree, decodes every leaf cell with
   exact self-validation (serial-type widths must sum to payload length,
   record must end inside the page, text must look like text), and emits only
   fully-decoded rows.
4. **Inspect the `NOTE:` lines and the patch manifest**: every applied repair
   is reported — data-row repairs, sqlite_master-record repairs, and inferred
   `content_start` fixes (page whose smallest cell lies above its
   content_start; the repair is the smallest cell offset, emitted only when
   that cell itself decodes).  Note the guard's precise scope: the decode
   check only rejects pointers into zeroed/unparseable regions; a flipped
   pointer landing in stale record bytes can still pass — evidence, not
   proof — which is why the engine-oracle search (step 5) exists.  Cells are
   validated independently, so a false patch never corrupts recovered rows.
   `--out-patches patches.json` collects all of them as `{"offset": newbyte,
   ...}`, and `Recovered N row(s)` tells you the count.
5. **Hypothesis-test the story engine-side — with an else-branch:**
   `python3 /skill/scripts/verify_with_sqlite.py FILE patched.db patches.json --json recover.json`
   runs the ladder: L1 open (`sqlite_master` readable) → L2 `PRAGMA
   integrity_check == 'ok'` → L3 rows read back equal `recover.json`.
   When L1/L2 fail, the tool AUTOMATICALLY runs an engine-oracle single-bit
   search over structural bytes only (per-page b-tree headers incl. both
   content_start bytes — which also covers down-flipped content_start —
   cell-pointer arrays, interior child pointers, plus file-header fields
   16–31), accepting only load-bearing flips (a failing rung turns passing),
   and re-runs the ladder on the patched copy.  v01: the 3-byte manifest alone
   passes all rungs (search adds nothing).  If L3 still fails, the difference
   is payload data or previously-unreachable pages: rerun the decoder on the
   patched copy (`python3 recover_sqlite.py patched.db --repair-bits --out
   r2.json --out-patches p2.json`) — pages the decoder skipped (e.g. a
   flipped page-type byte) become readable — then re-verify with `--json
   r2.json`.  Junk in header bytes @64–95 / @96–99 (version-valid-for) need
   NOT be patched — SQLite ignores them for a rollback-journal database (v01
   bytes 0x61–0x63 stay junk in the copy that passes integrity_check).
6. **If the schema page is unrecoverable:** fall back to
   `--columns col1,col2,... --carve --key-regex col:^pattern$`.
   The column list must match the **full record arity**, including the
   `INTEGER PRIMARY KEY` column that stores NULL in-record (products fixture:
   6 record values incl. the id column).  Carving sweeps every byte offset for
   self-consistent table-leaf records and merges rows whose key matches the
   pattern; use a *specific* key regex (e.g. `^testword\d+$`), otherwise the
   sqlite_master row itself can sneak in as a false positive.
7. **Emit only rows you fully decoded** — dedup by the full value tuple (or key
   column), sort stably, serialize: ints as JSON numbers, floats as numbers
   (99.99 and 0.5 must survive exactly), NULL as `null`, BLOBs as
   `{"$blob_b64": "..."}` (adjust to the case's schema).  Never pad with junk
   rows: precision beats recall for these graders.

## 4. Tooling (`scripts/`; in the task container: `/skill/scripts/`)

- `recover_sqlite.py` — the decoder.  Flags: `--out FILE.json`, `--repair-bits`
  (single-bit record-header repair with layered candidate picking), `--carve`
  (byte-offset sweep), `--columns a,b,c` (fallback schema), `--tables t1,t2`,
  `--key-regex col:^pat$`, `--page-size N` (force page size when the header is
  damaged), `--schema-only`, and **`--out-patches patches.json`** which writes
  the complete repair manifest (record-header repairs from the schema, data
  and carve walks, plus inferred `content_start` fixes) for the engine-verify
  step.  Repair picking is layered: exact-parse candidates always beat repaired
  ones; among repaired candidates the sqlite_master walk prefers
  sql-parses-as-CREATE + small rootpage + kind shape
  `[text,text,text,int,text]`, and data walks prefer fewest repairs then most
  text-plausible values.
- `verify_with_sqlite.py` — verification with an else-branch.  Applies byte
  patches (inline JSON, or a JSON file such as decoder `--out-patches` output)
  to a copy, then runs the ladder: L1 open, L2 `PRAGMA integrity_check`, L3
  (`--json recover.json`) row-set equality with the recovered JSON.  L3 is
  multiset (Counter) equality over canonical rows (frozensets of
  (column, value) pairs), restricted to tables whose column signature appears
  among the recovered dicts (out-of-scope tables can neither pass nor fail
  it), with per-table counts as diagnostics — identical rows across
  same-shaped tables keep their multiplicity (a missing duplicate FAILs) and
  an empty recover.json FAILs explicitly.  If L1/L2 fail it automatically runs
  the engine-oracle single-bit search over structural bytes (b-tree page
  headers incl. both content_start bytes, cell-pointer arrays, interior child
  pointers, file-header fields 16–31), accepting only load-bearing flips,
  re-patches and re-runs the ladder — no more hand hexdump-derivation for
  page-header damage.

## 5. Evidence from this run (v01 + fixtures)

- **v01 (`/app/trunc.db`, 8192 B, 2 pages, bit-flipped):** 3 structural single-bit
  flips — page-1 `content_start` 0x0fc5→0x0fc1 (cell pointer 0x0fc1 was intact
  and the record decoded exactly, proving the pointer right and content_start
  wrong), sqlite_master sql serial type 0x5b→0x5f (serial widths must sum to
  the 61-byte payload: 41-char sql needs serial 95=0x5f), data-row word serial
  type 0x61→0x21 (10-char text).  Plus junk in header bytes 0x61–0x63 and ~86
  single-bit flips in zero padding.  Recovery: **8/8 rows
  (testword02..09; values 10, 25, 42, 50, 75, 99, 99.99, 0.5)** — identical to
  the rows returned by SQLite from the 3-byte-patched copy.
- **Pristine multi-type fixture** (NULL, negative ints, 8-byte ints, floats
  incl. 1.5e300, Unicode text, empty text, small/empty BLOBs, an 8000-char
  overflow row, two tables): **8/8 rows round-trip** through the decoder.
- **Overflow X-cap discriminating fixtures** (rows that the un-clamped rule
  dropped): page_size=512 with a ~1000-char text (payload P=1003 inside the
  U=512 band [986,1054]; pointer oracle: engine stores local=39=M and the page
  number at payload_start+39) and page_size=4096 with a ~8200-char text
  (P=8204 inside the U=4096 band [8154,8672]; engine stores local=489=M and
  the page number at payload_start+489): both rows round-trip through the
  decoder and byte-match `sqlite3 SELECT`, which fails with the X-cap missing.
- **Fresh-solver trajectory (iteration-2, reset v01):** a one-shot solver using
  only the frozen package recovered 8/8 rows and passed all 5 grader tests
  (schema, complete word set, per-value match, format).  The trajectory exposed
  a real package weakness: the NOTE lines then listed only the data-row repair
  (sqlite_master-record repairs were applied silently and the corrupt
  `content_start` was never flagged), so the first engine-verify with "the
  reported repairs" failed with *database disk image is malformed* and the
  solver had to hand-derive the other two flips.  Fixed by `--out-patches`
  (complete manifest incl. schema repairs + decode-guarded `content_start`
  inference) and `verify_with_sqlite.py` accepting the manifest file;
  re-verified end-to-end on the same file: manifest = {106:193, 4040:95,
  8179:33}, patched copy passes `integrity_check`, `.dump` equals
  `recover.json` (8/8).  Also recorded that the task container mounts the
  package at `/skill`, so run `python3 /skill/scripts/...`.
- **Page-type-flip discriminating fixture (engine-oracle search):** flipping
  ONE bit of page 2's type byte (0x0d→0x0c, healthy two-table fixture) makes
  the decoder skip the page ("unknown page type"), leaves the manifest empty,
  and makes the engine refuse the table — the exact case the manifest cannot
  see.  `verify_with_sqlite.py ... --search`-style ladder finds the flip via
  the integrity rung (open still succeeds because sqlite_master lives on page
  1; integrity fails), the patched copy passes `integrity_check`, and after
  rerunning the decoder on the patched copy (previously-skipped page becomes
  readable) L3 dump-equality passes for all rows.  Down-flipped content_start
  is covered the same way (both content_start bytes are search candidates).
- **Multi-table same-shape fixture (L3 multiset+scope semantics):** two tables
  with identical columns (`t1/t2 (word TEXT, value REAL)`) recover 6/6 rows
  into one untagged JSON list and verify L1/L2/L3 all-ok.  Two follow-on
  discriminating fixtures hardened L3's equality rule: (1) multiplicity —
  t1=[('x',5),('y',6)], t2=[('x',5)] with recover.json missing one 'x'
  duplicate FAILs L3 (plain set-union previously passed it) while the complete
  three-row JSON passes; (2) scope — a DB with covered table `a(word,value)`
  plus out-of-schema table `b(dump TEXT)` passes L3 with only `a`'s rows in
  the JSON (previous all-tables union false-failed it); an empty recover.json
  fails instead of passing vacuously.  Prev-iteration checks re-affirmed: v01
  manifest ladder 8/8, pristine 8/8 with blob/IPK L3, empty manifests on
  healthy files, type-flip search (exactly one patch), overflow band
  round-trips (U=512 P=1003 local=39; U=4096 P=8204 local=489).
- **Fresh-solver trajectory (iteration-3, reset v01):** a one-shot solver on
  the frozen iteration-2 package completed in 9 tool calls with ZERO friction:
  task+skill read → env check (found `/skill/scripts/` immediately, per the
  SKILL note) → `.recover` (empty) → decoder (`--repair-bits --out
  --out-patches`, 8/8 rows, 3 NOTE lines, manifest {106:193, 4040:95,
  8179:33}) → verify ladder L1/L2/L3 all ok → grader 5/5.  The trajectory
  exercised no search/fallback legs, which is why the L3 multi-table
  attribution defect (found by probing the "several related tables" axis) is
  this iteration's revision.
- **Search hygiene:** a pristine fixture and the v01 manifest both pass all
  ladder rungs with zero search patches (acceptance is strictly load-bearing:
  a failing rung must turn passing); 8KB files cost a few seconds of in-process
  sqlite connects.
- **Manifest hygiene:** a pristine fixture yields an *empty* manifest (no
  false-positive patches), and the overflow band fixtures (U=512 P=1003,
  U=4096 P=8204) also yield empty manifests while round-tripping
  byte-identically — the content_start inference never fires on healthy pages
  or on pages whose cells fail to decode.
- **Full-residue oracle sweep:** the clamped rule `K if K<=X else M` was
  checked against the engine's actual pointer placement for **every residue in
  one full (U-4) cycle** at U=512 (525 overflow records) and U=4096 (4101
  overflow records): 0 mismatches.
- **Corruption battery:** 40 random single-bit flips → all 8 rows still decoded;
  7/8 exactly matched ground truth, the 8th's payload had 15 flips inside its
  text (data itself changed — impossible to recover pristine bytes without
  redundancy).  Zeroed cell-pointer array → structural walk lost 5 product
  rows; carving recovered the intact one; rows whose cell bytes were wiped are
  gone for any decoder.  Truncation at 75% → all rows on surviving pages
  recovered; the cut page's rows legitimately gone.  Zeroed page-1 b-tree
  header → schema lost; `--columns`+`--carve`+`--key-regex` recovered the
  key-able rows.

## 6. Failure modes and boundaries (be honest about them)

- **Bit flips inside payload bytes change the data itself.**  The decoder
  returns what the file now contains; if the grader compares against pristine
  values, such rows count as lost.  Detect via cross-check count, not panic.
- **Zeroed/erased cell bytes are unrecoverable by any tool** — carving still
  needs the cell start (payload varint) to exist.
- **Record-header repair assumes single-bit flips** and requires the repaired
  record to be *exactly* length-consistent AND text-plausible; multi-bit header
  corruption drops the row.  Several candidates can fit — that is why picking
  is layered (schema invariants) and why `verify_with_sqlite.py` exists.
- **The engine-oracle search is bounded, not magic.**  It covers structural
  bytes (page headers, pointer arrays, interior child pointers, file-header
  fields 16–31) under the family's single-bit damage model; multi-bit
  structural damage, damage to several interacting fields, or payload-byte
  flips are outside it — the search reports exhaustion and the ladder stays
  red, and the residual fallback is manual hexdump of the failing rung.
  Payload-data flips are *deliberately* not searched: they open fine and the
  L3 dump-equality rung would exclude them anyway.
- **content_start may be wrong while pointers are right (and vice versa)** —
  never gate cell acceptance on content_start; validate each cell's decode
  exactly.  v01's discriminating test: decode the schema record at both
  candidate offsets (0x0fc1 and 0x0fc5); only 0x0fc1 produces a record whose
  serial widths sum to the payload and whose sql parses as CREATE TABLE.
- **Header fields beyond page_size/reserved/encoding/page_count may be junk**
  (v01 had corrupted reserved/version-valid-for bytes); if page_size itself is
  suspect, scan candidate sizes and keep the one where byte 100 is a valid page
  type (2/5/10/13).
- **Carve false positives** are controlled with `--key-regex` + exact column
  arity; without them, expect junk rows (e.g. the sqlite_master cell decoded
  against your fallback column list).