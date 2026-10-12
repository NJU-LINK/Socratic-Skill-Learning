---
name: sqlite-db-truncate
description: Recover data from corrupted SQLite databases using payload-length validation and ranked repair.
---

# SQLite Database Recovery Skill

## Quick Start

```bash
# Find the recovery tool
SCRIPT=$(find /skill -name "recover_sqlite.py" 2>/dev/null | head -1)
cp "$SCRIPT" /app/recover_sqlite.py

# Run with auto-detection
python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json

# Or with explicit column mapping
python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json '{"0":"word","1":"value"}'
```

## Recovery Process

### Step 1: Extract Records
```python
import sys
sys.path.insert(0, '/app')
from recover_sqlite import recover_sqlite_data

# Returns list of value lists: [['testword02', 10], ['testword03', 25], ...]
records = recover_sqlite_data('/app/trunc.db', '/app/raw.json')
```

### Step 2: Map to Output Schema
```python
import json

# Map by column position
column_map = {0: 'word', 1: 'value'}
results = []
for values in records:  # values is a list like ['testword02', 10]
    mapped = {}
    for col_idx, key in column_map.items():
        if col_idx < len(values):
            val = values[col_idx]
            if isinstance(val, str):
                val = val.strip()
            mapped[key] = val
    results.append(mapped)

# Save
with open('/app/recover.json', 'w') as f:
    json.dump(results, f)
```

## Core Principle: Payload-Length Equation

```
payload_len == header_size + Σ(size of each serial type's data)
```

**Uses:**
- **Bound**: Never read past payload boundaries
- **Detect**: Flag corrupted records
- **Repair**: Find bit-flip repairs that balance equation
- **Rank**: Score by semantic plausibility

**Limitation**: Validates sizes, not content. Data-byte corruption invisible.

## Repair Ranking

When validation fails, generate single-bit-flip repairs and rank by:

| Signal | Score |
|--------|-------|
| Valid UTF-8 TEXT | +50 |
| Printable TEXT | +30 |
| SQL identifier | +20 |
| Reasonable integer (0-1M) | +20 |
| Valid int range | +10 |
| 2-10 columns | +20 |
| Per-column penalty | -2 |

## SQLite Format Reference

### Database Header
| Offset | Size | Description |
|--------|------|-------------|
| 0-15 | 16 | Magic "SQLite format 3\0" |
| 16-17 | 2 | Page size (1=65536) |
| 28-31 | 4 | Database pages |
| 56-59 | 4 | Encoding (1=UTF-8, 2=UTF-16le, 3=UTF-16be) |

### Page Layout
- **Page 1**: DB header (100 bytes) + b-tree at offset 100
- **Page 2+**: b-tree at offset 0

### B-tree Leaf Page (type 0x0d)
| Offset | Size | Description |
|--------|------|-------------|
| 0 | 1 | Page type (0x0d) |
| 3-4 | 2 | Cell count |
| 5-6 | 2 | Content start |
| 8+ | 2*N | Cell pointers |

### Cell Format
```
[payload_len: varint]
[rowid: varint]
[payload]
```

### Payload Format
```
[header_size: varint]
[serial_type_1: varint]
[serial_type_2: varint]
...
[value_1]
[value_2]
...
```

### Serial Types
| Type | Meaning | Size |
|------|---------|------|
| 0 | NULL | 0 |
| 1-6 | INT8-64 | 1,2,3,4,6,8 |
| 7 | FLOAT | 8 |
| 8 | Integer 0 | 0 |
| 9 | Integer 1 | 0 |
| 12+2n | BLOB(n) | n |
| 13+2n | TEXT(n) | n |

## Implementation Notes

### Structured Parsing vs Carving
- **Structured**: Uses page headers and cell pointers - allows repair
- **Carving**: Scans raw bytes - STRICT validation (no repair)

### Filtering Strategy
1. Extract all records from all pages
2. Merge structured + carved, dedup by offset
3. Filter: keep 2-10 columns, exclude sqlite_master pattern
4. Map to output format

### sqlite_master Pattern
5 columns: `(TEXT, TEXT, TEXT, INTEGER, TEXT)`
- type, name, tbl_name, rootpage, sql

## Handling Corruption

| Mechanism | Strategy |
|-----------|----------|
| Bit flips in serial types | Payload validation + ranked repair |
| Bit flips in data | Invisible to validation - cross-check siblings |
| Damaged page headers | Skip page, rely on carving |
| Zeroed regions | Skip all-zero pages |

## Limitations

1. Data-byte corruption invisible (payload-length only checks sizes)
2. UTF-16 edge cases possible
3. Multi-table databases need post-filtering by signature

## Function Reference

### recover_sqlite_data(db_path, output_path=None, column_map=None, encoding=None)
Main recovery function. Returns list of value lists, or mapped dicts if column_map provided.

### parse_page(data, page_num, page_size, encoding='utf-8')
Parse single page. Returns list of record dicts with keys: cell_offset, page_num, rowid, values, num_columns, was_repaired.

### carve_records(data, page_size, encoding='utf-8')
Carve from raw bytes. Returns record dicts (no repair allowed).

### classify_records(records)
Group records by signature. Returns dict {(num_cols, (type1, type2)): [records]}.

### get_signature(record)
Get structural signature: (num_columns, (type1, type2, ...)).
