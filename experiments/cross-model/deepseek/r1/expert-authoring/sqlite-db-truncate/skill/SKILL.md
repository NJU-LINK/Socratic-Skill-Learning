---
name: sqlite-db-truncate
description: Recover as many structurally valid rows as possible from a damaged
  SQLite database file (truncation, zeroed regions, random bit flips, broken
  page structures, fragmented records) by parsing pages, btrees, cells,
  varints, serial types and IEEE-754 values at the byte level, prove the
  recovery by regenerating the database from it and byte-diffing, then write
  the rows in the JSON schema given by the task.
---

# Recovering rows from damaged SQLite storage

The task hands you a `*.db` file that sqlite tooling cannot read and asks you
to write the surviving rows as JSON in the shape given by the instruction
(v01: `/app/trunc.db` → `/app/recover.json`, `[{"word": ..., "value": ...}]`).
The rows are logically intact; only the *encoding of storage* is damaged.
Extract — never invent — records. Damage mechanism, schema/encoding, key
style and scale vary per case (see `spec.yaml`); one procedure below covers
all of them.

The skill package ships two tools and one reference:

- `scripts/sqlite_raw.py` — raw reader with modes `verify` (recover + prove),
  `info`, `dump`, `scan`. `-h/--help` prints the mode docs.
- `scripts/regen_check.py` — hypothesis verification (used inside `verify`).
- `references/sqlite-format.md` — byte-level format tables.
- In the eval container the package is mounted **read-only at `/skill`**: run
  `python3 /skill/scripts/sqlite_raw.py ...` directly. Do **not** try to
  `read /skill/...` with the host file tool (it fails with a workspace
  boundary) and do not `cat` the scripts in the container — the modes and
  flags you need are documented here and in the scripts' own `-h` output.

## Default fast path — one command does the whole task

```bash
python3 /skill/scripts/sqlite_raw.py /app/trunc.db verify \
    --flat word,value --out /app/recover.json
```

`verify` recovers the schema and every table, rebuilds the database from the
recovered rows, byte-diffs the rebuild against the damaged file, prints a
classified verdict, and (with `--out`, `--flat`) writes the deliverable. Its
exit code is the verdict: `0` = proven, `1` = something unexplained, `2`/`3` =
file not readable / no usable schema.

Reading the report:

- `--- table test: 8 rows / 2 columns / root page 2` — what was recovered.
- `single-bit flips: N (of which M are zero->single-bit noise)` + `0
  unexplained multi-bit diffs` + `VERDICT: ... proven byte-exact modulo
  single-bit flips and the version stamp` — the recovery is byte-level
  correct for flips-style damage (what v01 is). Done: exit 0.
- `UNEXPLAINED 0xNNNNN` lines list problem offsets. Multi-bit diffs mean
  zeroed content, truncation, or a wrong value/type/order — see "When the
  verdict is not clean" below. Lost content cannot be recovered; ship what
  survived (`--out` was still written).
- A size-mismatch verdict is **expected** for truncation cases (the damaged
  file keeps its dead pages while the rebuild only has the living rows).
- `[note] ... <- repaired(0ff3)`: a cell needed a one-bit repair and was
  accepted; this is normal and does not change the verdict.

Only if `verify` reports problems do you open the manual steps. `info`,
`dump`, and `scan --contains <key-prefix>` are for investigating, and the
official tooling (`sqlite3 .schema` / `.recover`) is normally a dead end for
this family — try it once, don't fight it.

## Budget discipline (the rules that keep this task from spiraling)

Observed failure mode: an agent re-derived cell byte layouts by hand from
`xxd`, burned its entire budget in one mega-turn on arithmetic it got wrong
(the record's first byte is the *header size*, not a serial type), and hit a
provider quota error, forcing interruptions. Follow these rules instead:

1. **Never hand-parse bytes to double-check an accepted row.** The walker
   already gates every row on two oracles — declared payload size equals the
   record size exactly, and the cell ends exactly at the next boundary — and
   reports repairs on stderr. Rows in the output are self-consistent by
   construction. If your mental arithmetic disagrees with the tool, your
   arithmetic is wrong; move on.
2. **The independent check is `verify` itself** (regeneration + byte-diff),
   not `xxd`. Do not re-derive; verify.
3. **Keep turns short.** One command per turn along the fast path. If the
   session is interrupted, just re-run the same `verify` command — it is
   idempotent and reconstructs everything from `/app` + `/skill`.
4. A record is `varint(header-size H) + H-1 serial-type varints + payload`;
   e.g. `03 21 07` = header 3 bytes, serials `0x21` (TEXT of (33-13)/2=10
   chars) and `0x07` (float64). A cell's `rowid` counts insertion order; the
   stored text ("testword09") need not equal it.

## When the verdict is not clean

- **No usable schema** (exit 3): `dump --root N --columns a,b,c` using column
  order from the task's JSON keys, then feed rows to the hypothesis checker:
  `regen_check.py DB rows.json --create "<CREATE TABLE .…>" --table name`
  (rows.json = list of row lists in table-scan order; it also accepts the
  `dump`/`verify` JSON shapes).
- **Unexplained diffs inside cell regions** with the right row count: check
  the listed offsets against `info` + `dump` notes; a `partial(zeroed-values?)`
  note means headers survived but values were zeroed — keep the row (the task
  asks for "as many rows as possible") and accept the verdict.
- **Missing rows entirely** (e.g. a page whose btree header is zeroed):
  `scan --contains <key-prefix>` finds surviving records and loose fragments
  without headers; accept only hits whose *full* key matches the family
  pattern (spurious mid-cell parses exist); feed reassembled rows to
  `regen_check.py` before finalizing.
- **Damaged record headers**: infer column widths from sibling rows (text
  lengths follow the key pattern; REALs are 8 bytes) and require the
  payload-size oracle to close.
- **Ambiguous repairs**: prefer the candidate consistent with the
  schema-row shape for page 1 (`type` ∈ table/index/view/trigger, sane
  rootpage, SQL starting with `CREATE`, balanced parentheses) or with the
  task's JSON keys for data rows.

## Pitfalls

- Varints are big-endian 7-bit groups, most significant first — a
  little-endian loop silently corrupts everything ≥ 128 (text ≥ 64 chars).
- Serial types 1..6 are signed; 7 float64; ≥13 odd TEXT, ≥12 even BLOB;
  8→0, 9→1; 10/11 invalid.
- Page-1 btree header starts at offset 100; interior pointer arrays at 12
  (offset 8 = rightmost child page); leaf arrays at 8.
- `content_start` may itself be flipped — the real cell boundary is the next
  pointer or the page end.
- Never emit the `sqlite_schema` row or `sqlite_sequence` as data.
- `INTEGER PRIMARY KEY` = rowid alias: its value is the cell rowid, not a
  payload column (explicit NULLs may appear in the payload; `verify` excludes
  such rows from regeneration with a `[warn]`).
- Zeroed regions can spuriously parse as NULL records — validate against the
  column shape and key pattern.
- UTF-16 files (encoding field 2/3 in the 4-byte header field at offset 56)
  decode TEXT accordingly; their NUL bytes are normal. `verify` skips the
  byte-level rebuild verdict for them (a rebuild would change the storage
  encoding) and keeps the oracle-gated rows.
- Deliverable types: integers stay JSON integers (never `10.0`), REALs use
  shortest round-trip repr, NULL → `null`, table-scan order preserved,
  schema keys byte-for-byte (`word`, not `Word`).

## Evidence boundary

Observed in v01 (2×4096-byte pages, one table `test(word TEXT, value REAL)`,
8 rows): exactly three structural single-bit flips (page-1 content-start
byte, schema-cell SQL-length serial, one data-cell text-length serial) plus
~87 zero→single-bit noise bytes; the regeneration byte-diff proved the 8
recovered rows exact and keeps doing so: `verify` exits 0 (2 stamp bytes +
90 one-bit diffs, 0 unexplained). Also observed across iterations: solvers
that hand-audit bytes instead of trusting the oracle-gated tools spiral into
token exhaustion — hence the Budget discipline section. Extrapolated from
`spec.yaml` axes and validated on synthetic files: truncation/zeroed
regions, destroyed page headers, multi-table databases, records crossing
page boundaries (overflow chains, interior pages), scan-mode fragment
reassembly, 120+-row/table scales.