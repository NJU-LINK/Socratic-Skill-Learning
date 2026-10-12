# Iteration 2 Final Summary: Deterministic Tarball Skill

## Issues Fixed

### 1. Critical: Build Script Re-runnability (from test feedback)
**Problem**: 5 out of 6 tests failed with:
```
zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding.
```

**Root Cause**: The `zstd` compression tool refuses to overwrite existing output files by default when reading from stdin.

**Fix**: Added `--force` flag to zstd command in `/app/build.sh`:
```bash
| zstd -19 --long --no-check --single-thread --force -o "$OUT"
```

**Documentation**: Updated SKILL.md to document re-runnability requirement and `--force` flag in multiple sections.

### 2. Latent Bug: Pattern Matching Precedence (from Teacher review)
**Problem**: SKILL.md's `is_excluded()` reference code had incorrect pattern matching order that would cause `**/__pycache__/` patterns to fail.

**Root Cause**: The code checked `pat.endswith('/')` before `pat.startswith('**/')`, so patterns like `**/__pycache__/` would enter the wrong branch and never match correctly.

**Fix**: Reordered the checks to test `**/` prefix FIRST:
```python
if pat.startswith('**/'):      # ← Check FIRST
    ...
elif pat.endswith('/'):        # ← Check SECOND
    ...
```

**Documentation**: Updated SKILL.md's pattern matching section with corrected code and added precedence rule to edge cases list.

## Verification Results

### Build Script Tests
✓ Build script executes successfully  
✓ Build script is re-runnable (overwrites existing output)  
✓ Output is bit-for-bit reproducible  
✓ Uses GNU tar format with zstd compression  
✓ All exclusions honored (0 excluded items in archive)  
✓ Metadata normalized (owner 0:0, correct mtime)  
✓ Line endings normalized (CRLF → LF)  
✓ Symlinks preserved (2 symlinks)  
✓ Binary files preserved (null bytes intact)  
✓ Permissions normalized (executables 0755, others 0644)  

### Pattern Matching Tests
✓ `.hg/` pattern excludes `.hg/` directory and contents  
✓ `vendor/js/` pattern excludes specific path prefix  
✓ `**/__pycache__/` pattern excludes `__pycache__` at any depth  
✓ `*.tmp` pattern excludes files ending in `.tmp`  
✓ `*.class` pattern excludes files ending in `.class`  
✓ 0600 files excluded regardless of ignore patterns  
✓ Non-matching files correctly included  

## Files Modified

1. `/app/build.sh` - Added `--force` to zstd command
2. `skill/deterministic-tarball/SKILL.md` - Comprehensive updates:
   - Added "Build script re-runnability" section
   - Updated Phase 4 tar pipeline with `--force`
   - Added zstd flags table with `--force` marked CRITICAL
   - Fixed pattern matching precedence in `is_excluded()` reference code
   - Added precedence rule to edge cases list
   - Updated template structure with `--force`
   - Updated adaptation guide for gzip/xz force flags

## Status

✅ **READY FOR ITERATION 2 EVALUATION**

Both critical issues have been fixed and verified. The skill package correctly handles:
- Re-runnability (test harness requirement)
- Pattern matching precedence (correctness requirement)
- All deterministic archive building requirements (family invariants)
