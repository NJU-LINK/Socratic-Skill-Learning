# SQLite WAL Recovery Skill

This skill recovers data from SQLite databases where the WAL (Write-Ahead Logging) file has been encoded, obfuscated, or corrupted.

## Quick Start

```bash
# Run the recovery script with default paths
python3 skill/db-wal-recovery/scripts/recover.py

# Or specify custom paths
python3 skill/db-wal-recovery/scripts/recover.py /path/to/database.db /path/to/database.db-wal /path/to/output.json
```

## What It Does

1. **Auto-detects encoding**: Tries XOR (all 256 keys), base64, bitwise NOT, byte swapping
2. **Creates backups**: Safely backs up original files before modification
3. **Decodes WAL**: Applies the detected transformation to recover the original WAL
4. **Validates structure**: Checks WAL header magic, version, and page size
5. **Extracts data**: Opens the database with SQLite and exports all records to JSON
6. **Verifies writes**: Confirms the decoded WAL was written correctly

## Supported Encodings

- **Single-byte XOR**: Any key from 0x00 to 0xFF (e.g., 0x42)
- **Base64**: Text-encoded WAL files
- **Bitwise NOT**: Inverted bytes (XOR with 0xFF)
- **Byte swapping**: 16-bit byte order swaps
- **No encoding**: Valid WAL files used as-is

## Safety Features

- **Automatic backups**: Creates `.bak` files before any modifications
- **Write verification**: Reads back WAL after writing to confirm success
- **SHM cleanup**: Removes stale shared memory files that can cause issues
- **Validation at each step**: Checks magic, version, page size before proceeding

## Output Format

The script produces a JSON file with all records from all tables:

```json
[
  {"id": 1, "name": "item1", "value": 100},
  {"id": 2, "name": "item2", "value": 200},
  ...
]
```

Records are sorted by `id` if present, otherwise by the first column.

## When to Use

Use this skill when you encounter:
- SQLite databases in WAL mode with corrupted/encoded WAL files
- WAL files that don't have the standard magic bytes
- Situations where SQLite only shows base data instead of all records
- Database recovery scenarios involving WAL file manipulation

## Critical Rule

**NEVER open the database with sqlite3 before fixing the WAL.** Opening a database with an invalid WAL causes SQLite to delete the WAL file, making recovery impossible.

This script handles the correct ordering automatically:
1. Diagnose encoding
2. Decode WAL
3. Write decoded WAL
4. Remove SHM file
5. THEN open database

## Files

- `SKILL.md` - Complete methodology and technical documentation
- `scripts/recover.py` - Main recovery script
- `README.md` - This file

## Testing

To verify the skill works:

```bash
# In a fresh environment with original files
python3 skill/db-wal-recovery/scripts/recover.py

# Check output
cat /app/recovered.json

# Verify record count
python3 -c "import json; data=json.load(open('/app/recovered.json')); print(f'Records: {len(data)}')"
```
