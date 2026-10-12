# SQLite Database Truncate Recovery - Implementation Summary

## What Was Built

A comprehensive skill for recovering data from corrupted SQLite database files by
parsing the binary format directly, bypassing standard library integrity checks.

## Key Features Implemented

### 1. B-tree Traversal (Critical Addition)
- **Interior page parsing** (type 0x05): reads child pointers and separator rowids
- **Recursive tree walk**: traverses from rootpage to collect all leaf pages
- **Rightmost child handling**: correctly processes the special rightmost pointer
- **Cycle detection**: visited set prevents infinite loops
- **1-indexed page numbers**: all offset calculations use `(page_num - 1) * page_size`

### 2. Multi-Table Support
- Extracts `rootpage` from sqlite_master (column 3)
- Each table's B-tree is traversed independently
- Pages are correctly assigned to their owning table

### 3. Overflow Page Handling
- Detects when payload exceeds page boundaries
- Follows 4-byte page number chain through overflow pages
- Reassembles full record from local + overflow portions

### 4. Corruption Detection and Repair
- **Serial type validation**: detects when declared sizes exceed available data
- **Bit-flip repair**: infers correct serial type from remaining space
- **Truncated SQL handling**: parses partial CREATE statements
- **Schema record repair**: fixes corrupted sqlite_master entries

### 5. Fallback Strategies
- **Raw byte scanning**: when page structures are too damaged
- **Linear page scan**: when B-tree traversal fails
- **Pattern matching**: uses known text patterns to filter false positives

## Testing Results

### v01 Database (2 pages, corrupted serial type)
- Standard access: FAILED (database disk image is malformed)
- Binary recovery: **8/8 rows recovered**
- Corruption: serial type 0x21 → 0x61 (bit flip), correctly repaired

### Synthetic Multi-Table Database (8 pages, interior nodes)
- 2 tables: `users` (rootpage=2) and `scores` (rootpage=3)
- Both have interior B-tree pages pointing to multiple leaf pages
- Random byte corruption applied
- Recovery: **199/200 rows recovered** (1 lost to corruption)
  - users: 99/100 rows from leaf pages 4,5
  - scores: 100/100 rows from leaf pages 6,7,8

## Files Delivered

1. **SKILL.md** - Comprehensive documentation covering:
   - SQLite binary format (headers, pages, records, varints, serial types)
   - B-tree structure (interior vs leaf pages, cell formats)
   - Corruption detection and repair strategies
   - Overflow page handling
   - Implementation notes and pitfalls

2. **recover.py** - Standalone Python script implementing:
   - Standard access attempt
   - Schema extraction with rootpage tracking
   - B-tree traversal with interior page parsing
   - Record decoding with corruption repair
   - Overflow page chain following
   - Multi-table support
   - JSON output

## Critical Lessons Learned

1. **SQLite page numbers are 1-indexed** - Page 1 = offset 0, Page 2 = offset page_size
2. **Interior pages have different structure** - 4-byte rightmost pointer at offset 8,
   cell pointers start at offset 12 (not 8)
3. **Interior cells have no payload** - only [child_page:4][rowid:varint]
4. **rootpage is essential** - without it, you can't associate leaf pages with tables
5. **read_varint returns (value, bytes_consumed)** - not absolute offset
6. **Schema SQL may be truncated** - parse what's available, handle missing closing paren

## Usage

```bash
python3 recover.py <db_path> <output.json> [--columns col1,col2,...]
```

The script automatically:
1. Tries standard sqlite3 access
2. Falls back to binary B-tree traversal
3. Repairs corrupted records
4. Outputs JSON array of row objects
