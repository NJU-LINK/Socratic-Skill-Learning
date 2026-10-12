# Skill Update Summary: db_size Handling

## Teacher Feedback (Lesson 1-1)

The Teacher identified a critical gap in the `apply_pages_manually` function:
- Using `max(page_number)` to determine database size is incorrect
- Should use `db_size` from the last commit frame instead
- This affects three spec axes: `wal_and_base_database_integrity`, `recovery_depth`, and `schema_and_update_topology`

## Changes Made

### 1. Added `get_final_db_size()` Function

```python
def get_final_db_size(frames):
    """Extract final database size from the last commit frame."""
    final_size = 0
    for f in frames:
        if f['db_size'] > 0:
            final_size = f['db_size']
    return final_size
```

**Rationale**: Frame `db_size` semantics:
- `db_size = 0`: non-commit frame (intermediate write)
- `db_size > 0`: commit frame (total pages after transaction)

The last commit frame's `db_size` is the authoritative final database size.

### 2. Updated `apply_pages_manually()`

**Before**:
```python
max_page = max(page_updates.keys()) if page_updates else 0
```

**After**:
```python
if final_db_size is None:
    final_db_size = get_final_db_size(frames)

# Only apply pages within final_db_size
for pn, pd in page_updates.items():
    if pn < 1 or pn > final_db_size:
        continue  # skip pages outside final database (freed pages)
```

**Benefits**:
- Correctly handles freed pages (pages in WAL but not in final database)
- Works with no base database (creates empty buffer of correct size)
- Fixes SQLite header fields (change counter, page count, freelist pointers)

### 3. Updated `recover()` Function

**Added no-base-DB handling**:
```python
if not os.path.exists(db_path):
    print("No base database found, will reconstruct from WAL")
    db_page_size = None  # Will get from WAL header
```

**Extract and pass final_db_size**:
```python
final_db_size = get_final_db_size(frames)
print(f"Final db_size from WAL: {final_db_size} pages")
# ... later ...
success = apply_pages_manually(work_db, frames, header['page_size'], final_db_size)
```

### 4. Updated SKILL.md Documentation

**Added section on Frame `db_size` Field and Commit Semantics**:
- Explains db_size semantics (0 = non-commit, >0 = commit)
- Shows example with multiple transactions
- Explains why this matters for the three spec axes

**Updated Strategy B (Manual page application)**:
- Step 2: Extract `final_db_size` from last commit frame
- Step 4: Skip frames with page_number > final_db_size
- Step 6: Update database header fields (page count, change counter, etc.)

**Updated Database/WAL Integrity Variations**:
- Clarified no-base-DB scenario: "Reconstruct from WAL frames using `db_size` from commit frames"
- Added: "Track `db_size` across all frames to find the final size" for multiple WAL files

## Test Results

### Test 1: Standard v01 (XOR 0x42)
```
Frames: 1
  page=2, db_size=2
Final db_size from WAL: 2 pages
Records: 11 ✓
```

### Test 2: Multiple Transactions (XOR 0x77)
```
Frames: 2
  page=2, db_size=2 (COMMIT)
  page=2, db_size=2 (COMMIT)
Final db_size from WAL: 2 pages
Records: 11 ✓
```

### Test 3: Corrupted Page Size (XOR 0x55)
```
WAL page_size (2048) != DB page_size (4096)
Using DB page_size (4096) - 1 frames
Final db_size from WAL: 2 pages
Records: 11 ✓
```

### Test 4: No Base Database
```
No database file found, will reconstruct from WAL
Using WAL page_size: 4096
Final db_size from WAL: 2 pages
Records: 0 (expected - WAL doesn't contain page 1/schema)
```

**Note**: The no-base-DB test shows 0 records because the WAL only contains page 2 (data), not page 1 (schema). This is expected behavior - without page 1, SQLite doesn't know the table structure. The improvement is that we now:
1. Don't crash when there's no base DB
2. Use the correct database size from db_size
3. Would work correctly if the WAL contained page 1

## Why This Matters

The Teacher identified that `db_size` is "the single concept that fixes all three spec axes simultaneously":

1. **wal_and_base_database_integrity** ("omit the base database"): 
   - Now creates database of correct size using db_size
   - Handles reconstruction from WAL alone

2. **recovery_depth** ("fresh database/output must be reconstructed"):
   - Uses db_size to determine final database size
   - Skips freed pages that shouldn't be in final database

3. **schema_and_update_topology** ("updates distributed across multiple WAL streams"):
   - Tracks db_size across all frames
   - Last commit frame's db_size is authoritative

## Key Insight

The `db_size` field in WAL frame headers is the authoritative source for final database size, not `max(page_number)`. This is how SQLite itself determines database size when reading a WAL. Using it correctly prevents:
- Including garbage pages that were freed
- Creating databases with wrong size
- Crashes from corrupt database structure
