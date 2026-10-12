---
name: sqlite-db-truncate
description: >-
  Recover logically valid rows from damaged or truncated SQLite database
  files by parsing the on-disk btree format, validating structural
  invariants, repairing minimal bit-level damage, cross-checking with
  sqlite3, and serializing the recovered records to the case-specific JSON
  schema.
---

# SQLite DB Truncate / Corruption Recovery

Recover logically valid rows from damaged SQLite storage when ordinary queries
fail ("database disk image is malformed"), and serialize the recoverable
records using the case-specific public JSON schema.

## When to use

- sqlite3 / python sqlite3 fails to open or read a `.db` file (malformed,
  truncated, or corrupt), but the file (or a prefix of it) still contains the
  original pages.
- The task asks to "recover rows" / "repair the database" / "extract
  records".  Damage may be truncation, zeroed regions, random bit flips,
  damaged page structures, or split fragments (overflow chains).

## Quick start (task container)

The skill package is mounted **read-only at `/skill`** inside the task
container (this must not be assumed — check `ls /skill` first):
`/skill/SKILL.md`, `/skill/references/`, `/skill/scripts/recover_sqlite.py`.
The host `read` tool cannot open `/skill` paths (container-only mount) — do
not try to read the script or references from the host side; the interface
is documented here.  Execute the tool with `task_shell`.

```bash
# one-shot recovery with repair + sqlite3 oracle in a single run:
python3 /skill/scripts/recover_sqlite.py /app/trunc.db \
    --out /app/recover.json --repair-file /app/fixed.db
# success looks like: "decoded N rows, 0 unresolved cells",
# "sqlite3 oracle on repaired copy: OK", and a SELECT listing every row.
```

If `/skill` is empty or missing (e.g. authoring workspace), get the script
into the container another way: read it from the host skill package and
recreate it under /app with a heredoc, or run it from the host path if the
host filesystem is directly executable.  Output default: when `--out` is
omitted the script writes `recover.json` next to the database file — so
running `python3 /skill/scripts/recover_sqlite.py /app/trunc.db` from any
cwd still produces `/app/recover.json`.

Multiple user tables: the tool recovers **one table per run** — by default
the first user table, and it prints a WARNING listing all tables when more
than one exists.  Pick with `--table NAME`; run once per table and merge
per the case schema.

## Pipeline (always in this order)

1. **Triage.** Byte size of the file vs declared page count (header offset
   28 — offset 36 is the freelist count, unrelated to file size).  Run
   `file` and `sqlite3 db "PRAGMA integrity_check;"` to get
   sqlite's own failure text.  Count nonzero bytes per 512-byte region for a
   damage census.
2. **Header.** Parse the 100-byte database header: page size (bytes 16–17,
   1 ⇒ 65536), reserved bytes (20), schema format (44–47), encoding (56–59).
3. **Schema.** Page 1's btree header starts at byte **100** (not 0 — the
   database header sits in front).  Read type/cell-count/content-start, then
   cell pointers; decode sqlite_master cells (type, name, tbl_name, rootpage,
   sql).
4. **Walk the target table btree** from its rootpage: interior pages (0x05)
   → children via 4-byte child pointers in each cell + the right-child field;
   leaf pages (0x0D) → cell pointers.
5. **Decode cells.** varint(payload len) + varint(rowid) + payload; payload =
   varint(header size) + per-column serial-type varints + bodies.  Follow
   overflow chains when the payload spills.
6. **Validate every structural invariant** (see below).  Repair minimal bit
   damage by enumeration; re-check; verify with the `sqlite3` binary.
7. **Emit rows as JSON** in the case's schema (keys = column names from the
   CREATE TABLE statement), ordered by rowid.  Grade per row: never fail-fast
   on one bad record — keep every decodable neighbor.

## Verified format facts (full tables: references/sqlite-file-format.md)

| item | rule (all verified on v01 bytes unless noted) |
|---|---|
| varint | big-endian 7-bit groups, MSB set = more bytes; 9th byte uses 8 bits |
| serial types | 0 NULL; 1–6 signed ints of 1/2/3/4/6/8 bytes; 7 float64 big-endian; 8=0; 9=1; even ≥12 blob (N−12)/2; odd ≥13 text (N−13)/2 |
| storage vs affinity | **affinity is not storage**: a REAL column stores a 1-byte int if an int was inserted (v01: `value REAL` held serial type 1 for 10,25,42,50,75,99; typeof() turned them real on read) |
| table-leaf cell | varint(P) varint(rowid) [payload] (+4-byte overflow ptr if spilled) |
| overflow | U=usable; X=U−35; if P>X: M=((U−12)*32)//255−23; local=M+((P−M)%(U−4)); rest on overflow pages: 4-byte next + up to U−4 bytes (extrapolated; verified with a 9000-char synthetic insert) |
| interior page | 4-byte right child after btree header; each cell: 4-byte child + varint(P) + varint(rowid) |
| rowid alias | `INTEGER PRIMARY KEY` column occupies a payload **slot holding NULL**; real value = cell rowid varint; take rowid regardless of slot (verified on a 12k-row db) |

## Invariants — check all of these; any violation flags damage

1. **Cell count agreement**: `cell_count == len(pointers) == len(decoded cells)`.
   A configuration with zero cells is never "repaired to" — *a hypothesis
   that erases evidence is not a repair*.
2. **Cell spans**: cells pack contiguously from content_start upward.  Cell 0
   (first pointer, smallest key) sits at the highest address and must end at
   the usable page end: `cell_len == usable − ptrs[0]`.  Every later cell i
   spans `[ptrs[i], ptrs[i−1])`: `cell_len_i == ptrs[i−1] − ptrs[i]`.
   (Skipped when `freeblock != 0` or `fragmented != 0` — gaps are then
   legitimate.)
3. **Lowest cell**: `ptrs[-1] == content_start`.
4. **Length bookkeeping**: `payload_len == header_size + Σ body sizes`, and
   the header's varint size equals the sum of the serial-type varint lengths.
5. **Anchors**: type / freeblock / cell-count / fragmentation bytes are
   structural anchors; repair candidates may never range over them.

## Repair methodology (bit flips, damaged fields)

1. **Two-phase, mutually exclusive predicates.**  Cell-internal repair is
   accepted on *cell-internal + physical-edge* evidence only
   (payload-length arithmetic + cell fits its slot via the usable-end rule,
   which does not reference content_start).  Page-field repair (content-start,
   pointer array, interior right-child) is accepted only when *all* cells then
   decode and the full tiling holds.  This ordering converges for v01's
   damage pattern (serial-type flip + content-start flip in the same page)
   and avoids the deadlock where each repair is judged while the other field
   is still broken.
2. **Enumerate, don't guess.**  For a failing cell, try 1..2 bit flips over
   its structural prefix (payload-len/rowid varints + record header, ~30
   bytes).  Keep candidates that satisfy every invariant *and* a plausibility
   predicate (printable text; schema cells: type in
   {table,index,view,trigger}, printable name/sql, rootpage in [1, 65536);
   data rows: optional `--key-regex` on the first text column).  Prefer the
   minimum flip count; among ties prefer the configuration that decodes the
   most rows (that is also the task's own metric).
3. **Cross-field damage** (e.g. content_start and a serial type both flipped)
   is handled by the two-phase order: fix cells first, then fields; re-run
   until no new repairs.
4. **Rate census.**  When a replica/original reference exists (or can be
   constructed: same schema, same values, same write pattern — v01's original
   laid out identically to a fresh replica), diff bit-by-bit: bits set in the
   damaged file where the replica has 0 = 0→1 flips; replica has 1 where the
   damaged file has 0 = 1→0 flips.  v01: 89 added vs 1 cleared, p01 ≈ 1.4e-3,
   predicted cleared = 842×p01 ≈ 1.16 vs observed 1 → **closure**: the entire
   file is explained by one symmetric per-bit flip rate and the repairs you
   made; residue ≈ 0.
   Production notes (all observed in practice):
   - **Writer-dependent header bytes differ between replica and target**
     (change counter 24–27, version-valid-for 92–95, sqlite version 96–99:
     container sqlite is 3.46.1, a seed-written file may be 3.41.2).  Skip
     bytes 0–99 in the diff, or patch 96–99 in the replica to the target's
     value, before counting.
   - **Post-repair comparison arithmetic**: remaining flips = census flips −
     repaired flips, per direction.  v01: 89 set − 2 repaired (0x6A bit2,
     0x1FF3 bit6) = 87; 1 cleared − 1 repaired (0x0FC8 bit2) = 0 — landing
     exactly on this (or within a few bits) confirms the repair set.
   - The census is **confirmatory**; the sqlite3 integrity/SELECT oracle is
     the authoritative check.  A small Poisson deviation is not a failure.
5. **Residual uncertainty.**  A 1→0 flip inside a value byte is invisible to
   every structural check (the value just reads differently).  v01: 22 value
   bytes ⇒ ≈0.25 expected flips ⇒ "read as-is" wins; state the ~20% chance
   as a stated uncertainty — *state it, don't fix it*.

## Verification / oracle

- After repairs, write the repaired copy and run
  `sqlite3 fixed.db "PRAGMA integrity_check;"` plus `SELECT` of the target
  table: sqlite's strict parser is an independent decoder — if it reads the
  file, your structure is right.
- Synthetic oracles for branches v01 never exercised: (a) overflow —
  insert `'x'*9000`, assert recovered length 9000 and byte-equality with
  `SELECT hex(value)`; (b) interior walk — insert ~12k rows and assert
  count and first/last values equal sqlite3's.  (Both pass with the shipped
  script; run them again on any new environment.)
- **Truncation oracles** (the family's namesake axis — run whenever
  `parse_page` touches EOF handling): `head -c 4096` of the damaged file
  → WARNING + 0 rows + exit 0 (no crash); `head -c 8096` → the 2 intact
  bottom cells recovered, 6 UNRESOLVED; `head -c 8176` → 7 rows, 1
  UNRESOLVED; intact file → all rows.  Files shorter than 100 bytes fail
  with "file too short for a sqlite header — truncated?", not "bad magic".
- Compare value-wise, not just row counts (a count can pass while column
  alignment is wrong).

## Family variation map (spec.yaml axes → strategy)

| axis | invariants (same everywhere) | expected variation | handling |
|---|---|---|---|
| corruption_mechanism | page/btree/cell structure, invariants above | truncation, zeroed regions, random flips, damaged structures, split fragments | truncation: header-declared pages > actual file pages ⇒ WARNING; pages beyond EOF become note pages, surviving leaf cells are still decoded, missing cells reported UNRESOLVED (oracle: cut at 4096 → 0 rows; 8096 → 2; 8176 → 7; intact → 8); zeroed regions: undecodable cells → per-row loss; flips: enumeration repair; split records: overflow reassembly |
| schema_and_value_encoding | varints, serial types, record layout | table count, column order, NULLs, int/float/text mixes, cross-page records | decode driven by sqlite_master (all schema objects parsed; the selected table's rootpage is walked per run, see recovery_scale); affinity ≠ storage class; overflow machinery for big values |
| record_identification | rowid order, cell order, key pattern in first TEXT column | textual/numeric keys, multiple interleaved table signatures, damaged headers | `--key-regex` filter; per-table key patterns; header repair by enumeration + plausibility |
| recovery_scale | pointer-gap and tiling invariants | 2 rows … hundreds / several tables | same pipeline; per-record isolation; interior-page walking for large tables; several tables: run once per table via `--table` (the tool warns when >1 user table exists and recovers the first by default) |

## Evidence ledger

- **Directly verified on v01 bytes**: header fields; page-1 btree header at
  byte 100; leaf/cell decoding incl. a damaged serial-type byte
  (0x5B→0x5F) recovered by arithmetic (payload len 61 = 6 + 5+4+4+1+41);
  content-start flip (0x0FC5→0x0FC1) found by tiling; 1-byte-int storage in
  a REAL column; the 3-flip census closure (89 added, 1 cleared, p≈1.4e-3);
  sqlite3 roundtrip on the repaired copy returning all 8 rows.
- **Teacher-taught, cross-checked against bytes**: full on-disk format rules;
  pointer-gap/serial-type checksum idea; rowid-alias NULL-slot rule (also
  verified empirically on a 12k-row db); flip-census method; "test every
  repair against sqlite3".
- **Extrapolated (not exercised by v01), with verification procedures**:
  overflow spill constants (verified via synthetic 9000-char insert);
  interior btree walking (verified via synthetic 12k-row insert); truncated
  files, zeroed regions, multi-table schemas, index pages (see Limitations).

## Limitations (stated, not hidden)

- **One table per run**: the tool recovers the first user table by default
  and WARNINGs when >1 exists; use `--table NAME` for multi-table cases and
  merge the outputs per the case schema.
- **WITHOUT ROWID tables** and index pages (types 0x02/0x0a) are not decoded:
  their cells carry the key in the payload, no rowid varint, and a different
  spill rule.  The tool reports 0 rows for them; sqlite_master's index rows
  are read but ignored.  (Secondary indexes of a rowid table do not affect
  table-row recovery.)
- **Damaged cell-count/type/freeblock/frag bytes** are anchors, deliberately
  not repaired: misdetecting them corrupts the whole page.  Report and
  inspect manually if the anchor itself is flipped.
- **Invisible value flips**: a flipped bit inside an int/float body passes
  every check (see residual-uncertainty rule).
- **Rowid alias slot omitted** by a nonstandard writer: handled (rowid wins),
  but verify against sqlite3 output when unsure.

## Package

- `SKILL.md` — this file.
- `references/sqlite-file-format.md` — tested format facts and layouts.
- `scripts/recover_sqlite.py` — parser + repair + emit tool
  (`--table`, `--key-regex`, `--repair-file`, `--replica`, `--census`,
  `--out`); run with `python3 /skill/scripts/recover_sqlite.py damaged.db
  --out out.json` (with no `--out`, it writes `recover.json` next to the
  database; `--out -` prints JSON to stdout).