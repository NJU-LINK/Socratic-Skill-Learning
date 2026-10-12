---
name: sqlite-db-truncate
description: Recover logically valid rows from damaged SQLite database files (truncated, bit-flipped, zeroed, structurally damaged, or fragmented) when ordinary sqlite3 queries fail, using staged intact-SQLite fallbacks, raw b-tree page/record parsing with strict validation, and signature carving; then serialize the recovered records to the case-specific JSON output schema.
---

# Recover rows from a damaged SQLite database

## Mission shape (invariant)

- Input: a damaged SQLite file at a path given by the instruction. Output: a JSON file at a path given by the instruction, in the instruction's exact schema (key names, nesting).
- Everything case-specific — file paths, table/column names, JSON keys, row signature (a recognizable key prefix/pattern), expected row count — comes from the **instruction text, not from this skill**. Extract those first and keep them in front of you.
- Recovery may use intact SQLite behavior plus raw analysis of pages, varints, record headers, serial types, and overflow fragments. Corruption mechanism, schema shape, key type, and scale all vary per case; the staged method below does not.

## Ground rules

1. **Never modify the original DB.** Work on copies: `cp file.db work.db`. Forensic tools and repair attempts go against copies.
2. **Every structural field is suspect.** Damage often hits b-tree headers, cell counts, pointer arrays, and record headers. Cross-validate before trusting any single field; treat inconsistencies as damage signals, not truth.
3. **Every output row must trace to bytes you decoded.** Never invent or interpolate values. If a row is half-destroyed, output only values you actually validated.
4. Keep the JSON schema from the instruction exactly: same keys, same types. A perfect recovery in the wrong schema scores zero.
5. **Prefer executing the packaged script over writing your own parser.** Hand-rolled parsers routinely drop exactly the strict-validation, single-bit-repair, and overflow logic that recovers the marginal rows.

## Running the packaged script (read before first use)

The path your file-reading tool shows for `scripts/sqlite_recover.py` is a host-workspace path; it is usually **not visible inside the task shell**. Resolve the real path inside the shell first, then copy it next to your work:

```sh
REC=$(find / -name sqlite_recover.py -type f 2>/dev/null | head -1); echo "$REC"
# common mounts: /skill/scripts/sqlite_recover.py, /opt/..., or the skill base dir
cp "$REC" /app/sqlite_recover.py        # mounts may be read-only; work on a copy
python3 /app/sqlite_recover.py --help   # sanity: it runs
```

If `find` locates nothing, recreate the script in the shell by writing out the **exact, complete** file content you read (single quoted heredoc), then `python3 -m py_compile` it. Do not paraphrase, simplify, or retype from memory — a transcription that drops the repair stage will silently return fewer rows (observed: 7 of 8).

## Fast triage (do this first, ~2 minutes)

```sh
ls -l DB; file DB
xxd DB | head -10                      # magic "SQLite format 3\0"? page size @16-17 (BE u16, 1=>65536)
xxd DB | tail -20                      # tail often holds the newest cells; note row signatures
grep -abo 'SIGNATURE' DB | head        # byte offsets of recognizable keys; proves data survives
grep -ao 'SIGNATURE' DB | wc -l        # occurrence count = your minimum row-count target
python3 -c "import os; s=os.path.getsize('DB'); print(s, 'bytes')"   # size % page_size != 0 => truncated tail
```

Minimal environments may lack `strings`, `xxd`, or even `sqlite3`. Python fallbacks:

```sh
# strings replacement: printable runs of length >= 4
python3 -c "import re;print(b'\n'.join(re.findall(rb'[ -~]{4,}', open('DB','rb').read())))" | sort | uniq -c | sort -rn | head
# xxd replacement: od -A d -t x1z DB | head
# sqlite3 replacement: python3 -c "import sqlite3" is guaranteed; the CLI may not be
```

Header fields worth reading even from a damaged file: page size @16-17, write/read versions @18-19, reserved bytes @20 (usually 0), page count @28-31 (may be stale or flipped — cross-check against actual file length), text encoding @56-59 (1=UTF-8, 2=UTF-16le, 3=UTF-16be).

## Staged recovery decision tree

Stop when you can account for all rows the evidence says exist — but always run Stage C as a cross-check on Stage B when scale permits.

### Stage A — intact-SQLite paths (cheap; try on a copy)

```sh
sqlite3 work.db '.tables'                          # may already work if damage is off the read path
sqlite3 work.db 'SELECT * FROM t;'                 # query each table directly
sqlite3 work.db '.dump' > dump.sql                 # salvages what it can, marks corruption errors
sqlite3 work.db '.recover' > rec.sql               # skips bad pages, but needs a readable schema page
```

- If queries work, verify row counts against raw evidence (`grep -ao 'SIGNATURE' DB | wc -l`) before trusting them — silent damage can hide rows without erroring.
- `.recover` can succeed yet recover nothing when the sqlite_master page is damaged (observed: it emits only pragmas and COMMIT). Do not treat its output as ground truth.
- Do **not** hand-patch bytes and re-query as your primary strategy: flips in payload bytes are silently accepted by SQLite (no checksums), so a "successful" query can return corrupted values. Hand-patch only to cross-check what you recovered structurally.

### Stage B — structural page scan (primary)

First make the script runnable inside the shell (see "Running the packaged script" above), then:

```sh
python3 /app/sqlite_recover.py DB
# overrides when header fields are damaged: --page-size 1024 --encoding utf-16-le
```

The script scans **every page independently** as a potential table-leaf (0x0d) — it does not need the file header, interior pages, or freelist links to be intact — and strictly validates each cell. It also emits sqlite_master rows (5-column records whose 5th value starts with `CREATE`), which give you table names, root pages, and exact column names/order.

Output is JSON lines: `{src, offset, rowid, types, values, repaired, repair_status}`.
- `repair_status`: `null` = strict-valid; `"ok"` = unique plausible single-bit header repair; `"AMBIGUOUS"` = several repairs validate — inspect by hand (`xxd -s offset`), pick the parse consistent with sibling rows and the schema; `"partial"` = only leading values survived (truncation), trailing values are absent, not zero.
- Records with `"error"` are cells that failed validation — revisit them manually; they may hold rows no other path recovers.

### Stage C — signature carving (mandatory cross-check; sole path for some damage)

```sh
python3 /app/sqlite_recover.py DB --carve 'testword'      # regex over raw bytes
```

Carving finds every regex occurrence (including free space, freelist pages, truncated tails, and pages whose b-tree headers were zeroed) and walks backwards to a record start that strictly validates with a text field covering the match. Cell fetch is page-aware: overflow chains are followed, so records spanning pages still decode fully.

Use carving when: page structures are damaged/zeroed, the file is truncated, rows may have been deleted, or you need an independent count to cross-check Stage B. Prefer the key prefix from the instruction as the pattern; for numeric-only keys, rely on Stage B and carve on the record-header structure instead (or carve on any constant text column).

### Merge and dedupe

- Group candidate rows by their natural key (instruction's JSON key field) or rowid. Dedupe identical rows produced by both stages.
- On conflict for the same key: prefer strict-valid over repaired, full over `partial`, page-referenced over free-space carve. If the strict and repaired versions differ in a value, trust strict.
- Multiple tables: group records by serial-type signature + key pattern; map each group to a table using the recovered sqlite_master rows (column count/order from the `CREATE TABLE` text).

## SQLite format cheat sheet (enough to verify or hand-parse)

- **Varint**: big-endian, 7 bits per byte, MSB = continue; a 9th byte contributes all 8 bits.
- **Pages**: page 1 carries the 100-byte file header, so its b-tree header starts at offset 100; other pages at offset 0. Types: 0x05 interior table, 0x0d leaf table, 0x02/0x0a index. Leaf header: type(1), first-freeblock(2), ncells(2), cell-content-start(2), fragmented-free(1); then ncells × 2-byte cell pointers (offsets relative to page start; may themselves be damaged).
- **Table-leaf cell**: varint payload-len, varint rowid, payload, optional 4-byte overflow page no.
- **Record**: varint header-len (counts itself), then one varint serial type per column, then values concatenated.
- **Serial types**: 0=NULL, 1..6 = signed big-endian int of 1/2/3/4/6/8 bytes, 7 = 8-byte big-endian IEEE-754 float, 8 = integer 0, 9 = integer 1, 10/11 invalid, N≥12 even = blob of (N−12)/2 bytes, N≥13 odd = text of (N−13)/2 bytes.
  - SQLite stores integral REAL values as int serial types on disk: a REAL column can hold 10 (int) in one row and 0.5 (float) in the next. Both decode to the same JSON number; do not "fix" the type.
- **Overflow**: usable size U = page_size − reserved(@20). Leaf max local X = U−35; min local M = ((U−12)*32)//255 − 23. If payload P > X: K = M + (P−M) % (U−4); local = K if K ≤ X else M; remainder lives in a chain of overflow pages (4-byte next-page pointer, then U−4 data bytes).
- **Strict-validation invariants** (use them to accept/reject candidate parses): header-len lands exactly after the last serial type; header-len + Σ serial sizes == payload-len; serial types never 10/11; text decodes in the file encoding; cell does not overrun its page (unless legitimately overflowing); text columns rarely contain NUL/control bytes.

## Playbook by observed damage (match the case; several can combine)

- **Random bit flips**: most bytes survive; strict validation isolates the few bad cells. Single-bit repair recovers records whose header/serial-type byte flipped; beware coincidental false repairs (rank by printable text + common int widths 1/2/4/8; investigate AMBIGUOUS). Flips inside payload values are undetectable structurally — flag rows only when implausible against siblings.
- **Truncated file** (size % page_size ≠ 0 or header page-count > actual pages): Stage B recovers all intact pages; Stage C covers the partial tail; expect `partial` rows near the cut — output their validated leading values only if the schema tolerates missing fields, else omit and note.
- **Zeroed regions / destroyed page headers**: leaves with zeroed type bytes are invisible to Stage B; Stage C carves their cells directly (cell parse is page-aware and needs only page size). A zeroed page 1 loses only the schema, not table data — rebuild column names from the instruction and record shapes.
- **Damaged page structures** (ncells/pointer array/content-start inconsistent): Stage B skips the page; carve every cell offset linearly (Stage C), or hand-parse with the invariants above.
- **Split fragments**: carve each fragment independently; order/reassemble by rowid or key. Overflow chains crossing a fragment boundary yield `partial` leading values.
- **Interleaved tables**: never assume one record shape per page — group by `(len(types), types)` signature plus key pattern before mapping to output schema.

## Assemble, serialize, and self-verify (before declaring done)

### Assemble the output programmatically — never hand-type values

The script emits JSON lines so the final file can be built by code, not by copying values out of tool output. Hand-transcribing values into a literal silently drops or typo-es rows (observed in practice) and is infeasible past a few dozen rows. Adapt only the marked spots of this template:

```python
import json, re, subprocess

DB, OUT = '/app/DB', '/app/OUT.json'     # <-- REQUIRED: paths from the instruction
SIG = 'PREFIX'                           # <-- REQUIRED: key prefix/pattern from the instruction
KEYS = ['col1', 'col2']                  # <-- REQUIRED: JSON keys, in record column order

def recover():
    out = subprocess.run(['python3', '/app/sqlite_recover.py', DB, '--carve', SIG],
                         capture_output=True, text=True).stdout
    best = {}
    for line in out.splitlines():
        r = json.loads(line)
        vals = r.get('values')
        if not vals or len(vals) != len(KEYS):
            continue                     # schema rows, errors, partials, other tables
        if r.get('repair_status') == 'AMBIGUOUS':
            continue                     # resolve by hand first (xxd the offset)
        key = vals[0]                    # <-- natural key column position
        if not isinstance(key, str) or not re.fullmatch(SIG + r'.*', key):
            continue                     # <-- row-shape predicate for THIS case
        rank = (bool(r.get('repaired')), r.get('repair_status') == 'partial')
        if key not in best or rank < best[key][0]:
            best[key] = (rank, vals)     # prefer strict over repaired, full over partial
    return [dict(zip(KEYS, vals)) for _, vals in sorted(best.values(),
            key=lambda kv: kv[1][0])]    # <-- deterministic order (or rowid)

rows = recover()
print(len(rows), 'rows assembled')
json.dump(rows, open(OUT, 'w'), allow_nan=False)
```

Adapting: change the row-shape predicate to the case (column count/types, key regex); for numeric keys use `isinstance(key, (int, float))` and scan output only; for several tables, assemble each group (serial-type signature) into its own list per the instruction's schema; if `repair_status == 'partial'` rows are included, ensure missing trailing keys are handled the way the instruction expects.

### Serialize

1. Write JSON to the **exact path** in the instruction, with the **exact key names** from the instruction's example (e.g. `[{"word": ..., "value": ...}]`). Arrays of flat objects are typical; match any shown ordering if specified, else use a deterministic order (rowid or sorted key).
2. Types: JSON numbers for int/float, strings verbatim (no added whitespace), `null` for NULL. Guard against `NaN`/`Infinity` floats (`json.dump(..., allow_nan=False)` catches them) — decode floats from bytes instead of emitting them.

### Verify

   - `python3 -c "import json; d=json.load(open('OUT')); print(len(d))"` — parses, expected count.
   - Count cross-check (**stop condition, not optional**): recovered count must equal or explain at least two independent estimates — `grep -ao 'SIGNATURE' DB | wc -l`, max rowid seen, sum of per-page ncells fields. If your count is lower, rows are missing: revisit `error` records, run the carve, inspect AMBIGUOUS repairs. Do not stop while counts disagree (this check is what caught a 7-of-8 transcription loss in practice).
   - Spot-check 2–3 rows against raw bytes at the offsets the script reported (`xxd -s OFFSET -l 48 DB`, or the `od` fallback).
   - No control characters in strings, no empty keys, no duplicate keys unless the instruction implies a multiset.

## Observed anchor evidence (v01; do not assume for other cases)

In the anchor case the file was bit-flipped: only ~3 flips landed in live bytes (one schema serial type, one b-tree content-start field, one record's serial type), the rest in free space. `sqlite3`, `.dump`, and `.recover` all failed; the raw scan and the carve each independently recovered all rows, including the header-repaired one. Values mixed int and float storage under a REAL column. Other cases may truncate, zero regions, damage page structures, split fragments, use different schemas/keys/scales — run the staged method and let validation, not this anecdote, decide what is recoverable.

## Common pitfalls

- Editing the original DB in place (hex editor, `sqlite3` repair attempts) — always copy first.
- Trusting `.dump`/`.recover` output as complete — they can silently drop tables/rows.
- Assuming file size is a multiple of page size, or that the header page-count is honest.
- Forgetting page 1's b-tree header starts at offset 100, not 0.
- Reading overflow records as contiguous file bytes — they are chained pages; follow pointers.
- Accepting the first bit-flip repair that validates — check plausibility and ambiguity first.
- Retyping or "simplifying" the packaged script from memory — transcription drops the repair/validation logic and silently costs rows. Execute the packaged file; if unreachable, reproduce it byte-for-byte.
- Hand-transcribing recovered values from tool output into the output JSON — the same transcription-risk class at one remove, and infeasible at hundreds of rows. Pipe the script's JSONL through an assembler (template above) and let the count cross-check judge the result.
- Running the script at the host path your read tool displayed — that path does not exist inside the task shell; `find` the mounted copy first.
- Assuming `strings`/`xxd`/`sqlite3` exist — check, and use the Python fallbacks above.
- Emitting near-right JSON: wrong key casing, ints as strings, missing output path — match the instruction literally.
