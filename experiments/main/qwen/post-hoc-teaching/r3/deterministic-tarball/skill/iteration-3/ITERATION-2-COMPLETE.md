# Iteration 2 Complete: Deterministic Tarball Skill

## Problem Solved

**Critical Issue**: Build script failed on re-runs with error:
```
zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding.
```

This caused 5 out of 6 tests to fail because the test harness calls `build.sh` multiple times to verify:
- Reproducibility (build twice, compare checksums)
- Dynamic exclusion (modify .distignore, rebuild)
- Permission-based exclusion (chmod to 0600, rebuild)

## Root Cause

The `zstd` compression tool refuses to overwrite existing output files by default when reading from stdin. This is a safety feature to prevent accidental data loss, but it breaks build script re-runnability.

## Solution

### 1. Build Script (`/app/build.sh`)
Added `--force` flag to zstd command:
```bash
| zstd -19 --long --no-check --single-thread --force -o "$OUT"
```

### 2. Skill Documentation (`SKILL.md`)
Comprehensive updates to document the re-runnability requirement:

- **Overview section**: Added "Build script re-runnability" paragraph explaining why `--force` is mandatory
- **Phase 4 example**: Updated tar pipeline to include `--force`
- **Compressor flags table**: Added dedicated table for zstd flags with `--force` marked as **CRITICAL**
- **Compression determinism section**: Documented `--force` as critical for re-runnability
- **Template structure**: Updated template to include `--force`
- **Adaptation guide**: Specified `--force` equivalents for gzip (`-f`) and xz (`-f`)

## Verification Results

All requirements verified:

✓ Build script executes successfully  
✓ Build script is re-runnable (overwrites existing output)  
✓ Output is bit-for-bit reproducible  
✓ Uses GNU tar format with zstd compression  
✓ All exclusions honored (0 excluded items found in archive)  
✓ Metadata normalized (0 bad entries)  
✓ Line endings normalized (0 CRLF in text files)  
✓ Symlinks preserved (2 symlinks maintained)  

## Generalization

This fix addresses a **family invariant** applicable to all variants:

- **Invariant**: Build scripts must be safely re-runnable
- **Mechanism**: Compression tools have safety features preventing overwrites
- **Failure mode**: Test harnesses and development workflows require multiple runs
- **Solution**: Always use force-overwrite flags (`--force`/`-f`) for compression tools

## Files Modified

1. `/app/build.sh` - Added `--force` to zstd command
2. `skill/deterministic-tarball/SKILL.md` - Comprehensive documentation updates
3. `skill/deterministic-tarball/ITERATION-2-SUMMARY.md` - This summary

## Status

✅ **READY FOR ITERATION 2 EVALUATION**

The skill now correctly handles the re-runnability requirement that caused all test failures in iteration 1.
