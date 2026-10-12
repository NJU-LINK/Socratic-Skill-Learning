---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when standard
  queries fail due to corruption (truncation, bit flips, zeroed regions,
  damaged page structures, or split fragments). Parse the raw SQLite file
  format — headers, B-tree pages, record headers, varints, serial types —
  to extract and serialize recoverable records into JSON.
---

# Corrupted SQLite Row Recovery

## When to Use This Skill

The database file exists at the expected path and `file` recognises it as
SQLite, but `sqlite3 <db> ".schema"` or `SELECT` statements return
`database disk image is malformed`. The task requires recovering as many
rows as possible and writing them to a JSON file.

## High-Level Strategy

```
1. TRY STANDARD TOOLING
   sqlite3 <db> "SELECT * FROM <table>;" 2>/dev/null
   → If it succeeds, just dump to JSON. Stop here.

2. IF STANDARD TOOLING FAILS — go raw:
   a. Read file header → page size, page count, encoding.
   b. Parse page-1 sqlite_master to recover CREATE TABLE statements
      (schema, column names, column affinities, root page numbers).
   c. For each data page referenced by the schema:
      - Read B-tree page header (type, cell count, content offset).
      - Walk the cell-pointer array.
      - For each cell: decode payload-size varint, rowid varint,
        then the record-format body.
   d. VALIDATE every serial type against the remaining payload budget.
      If a type is invalid, attempt single-bit-flip correction (the most
      common corruption pattern) and accept the correction only if the
      total body size matches exactly.
   e. If B-tree headers / cell-pointer arrays are themselves corrupted,
      fall back to scanning raw bytes for recognisable record patterns
      (known text prefixes, plausible header-size bytes, valid serial-type
      sequences whose body sums to the declared payload size).
   f. Collect recovered rows and serialise to the required JSON format.
```

## SQLite File Format Quick Reference

| Offset | Size | Meaning |
|--------|------|---------|
| 0      | 16   | Header string `SQLite format 3\0` |
| 16     | 2    | Page size (big-endian; 1 means 65536) |
| 18     | 1    | File format write version |
| 19     | 1    | File format read version |
| 20     | 1    | Reserved space per page |
| 28     | 4    | File change counter |
| 32     | 4    | Database size in pages |
| 100    | …    | Page-1 B-tree content (sqlite_master) starts here |

### B-Tree Page Header (at start of each page, or offset 100 for page 1)

| Offset | Size | Meaning |
|--------|------|---------|
| 0      | 1    | Flags: `0x02`=interior index, `0x05`=interior table, `0x0a`=leaf index, **`0x0d`=leaf table** |
| 1      | 2    | First freeblock offset (0 = none) |
| 3      | 2    | Number of cells |
| 5      | 2    | Cell content area start offset |
| 7      | 1    | Fragmented free bytes |
| 8      | (interior only) 4 | Right-most pointer |

Cell pointer array follows immediately: `num_cells × 2` bytes, each a big-endian page-relative offset.

### Record Format (inside each cell)

Cell layout: `payload_size_varint | rowid_varint | record_bytes`

Record layout: `header_size_byte | serial_type_varints… | column_values…`

**Serial types:**

| Value      | Meaning |
|------------|---------|
| 0          | NULL |
| 1–6        | Signed int, 1/2/3/4/6/8 bytes |
| 7          | IEEE-754 float64 (8 bytes, big-endian) |
| 8, 9       | Constant 0, 1 (no body bytes) |
| ≥12, even  | BLOB of `(N-12)/2` bytes |
| ≥13, odd   | TEXT of `(N-13)/2` bytes |

### Varint Encoding

Each byte: high bit = continuation; lower 7 bits = data. Up to 9 bytes.
For the 9th byte all 8 bits are data.

## Corruption Patterns & Countermeasures

### Random Bit Flips (most common in this family)
- **Symptom**: Most of the file is intact; isolated bytes differ by one or
  a few bits. Typical target: serial-type bytes in record headers.
- **Detection**: A serial type whose implied body size exceeds the
  remaining payload, or that doesn't match the schema column affinity.
- **Correction**: Try XOR-ing each bit (up to 8 candidates for a
  single-byte type). Accept the candidate whose body size plus the
  remaining columns' body sizes exactly equals the remaining payload.

### Zeroed Regions / Truncation
- **Symptom**: A contiguous region of the file is all `0x00`.
- **Strategy**: The cell-pointer array and B-tree header may survive even
  if cell content is partly zeroed. Extract whatever cells are intact.
  For partially zeroed cells, recover the columns that precede the zero
  boundary and mark the rest as NULL.

### Damaged Page Structures
- **Symptom**: B-tree flags byte is wrong, or cell count is implausible.
- **Strategy**: If the page-size is known from the file header, scan each
  page for `0x0d` at offset 0 (leaf table flag). If the header is
  corrupted but cell content survives, scan for plausible cell starts
  (small varint followed by another small varint followed by a record
  header byte in 2–20 range).

### Fragment Reassembly
- **Symptom**: Record data is split across non-contiguous regions.
- **Strategy**: Look for text prefixes (e.g. known key patterns), then
  read forward until the declared payload size is satisfied. Validate
  using the serial-type/body-size consistency check.

## Validation Checklist

Before writing the JSON output, verify:

- [ ] Every serial type in a recovered record is a legal value (0–9, or
      ≥12 with correct parity).
- [ ] The sum of body bytes implied by all serial types equals
      `payload_size - header_size` exactly.
- [ ] Text columns decode as valid UTF-8.
- [ ] Integer and float values are within plausible ranges (no NaN, no
      extreme exponents for float64 unless expected).
- [ ] Rowids are positive and monotonically reasonable.
- [ ] Column count matches the schema from sqlite_master.

## Output Serialization

- Match the JSON schema given in the task instruction exactly
  (key names, nesting, types).
- Integers stored as SQLite integer serial types → emit as JSON integers.
- Floats stored as serial type 7 → emit as JSON floats.
- NULL → `null`.
- BLOB → hex string or base64 (follow the task instruction).
- Write to the path specified in the task (typically `/app/recover.json`).

## Recovery Script

A ready-to-use Python recovery script is provided at
`scripts/recover_sqlite.py`. Run it as:

```bash
python3 scripts/recover_sqlite.py /app/trunc.db /app/recover.json \
  --schema-hint 'CREATE TABLE test (word TEXT, value REAL)'
```

The `--schema-hint` flag is optional; if omitted the script attempts to
parse sqlite_master from page 1. If page 1 is too damaged, provide the
schema manually (the task instruction or test file often reveals it).
