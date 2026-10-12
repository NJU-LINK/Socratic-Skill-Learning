# Iteration 2 Summary: Deterministic Tarball Skill

## Critical Issue Identified

**Test Failure Analysis**: 5 out of 6 tests failed with the same error:
```
zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding.
```

**Root Cause**: The test harness calls `run_build()` multiple times to verify:
1. Reproducibility (build twice, compare checksums)
2. Dynamic exclusion (modify .distignore, rebuild, verify changes)
3. Permission-based exclusion (chmod files to 0600, rebuild, verify exclusion)

The build script failed on the second invocation because `zstd` refuses to overwrite existing output files when reading from stdin by default.

## Solution Implemented

### 1. Build Script Fix (`/app/build.sh`)
Added `--force` flag to the zstd command:
```bash
| zstd -19 --long --no-check --single-thread --force -o "$OUT"
```

### 2. SKILL.md Documentation Updates

**Added "Build script re-runnability" section** in Overview:
- Explains that build scripts must be safely re-runnable
- Emphasizes this is critical for test harnesses and development workflows
- Documents that compression tools (zstd, gzip, xz) refuse to overwrite by default
- Specifies that `--force` (`-f`) flag must always be used

**Updated Phase 4 documentation**:
- Added `--force` to the tar pipeline example
- Created dedicated "Compressor flags for zstd" table with `--force` marked as **CRITICAL**
- Updated compression determinism section to mention `--force` as critical for re-runnability
- Updated adaptation guide to specify `--force` for gzip (`gzip -n -f`) and xz (`xz -f`)

**Updated template build.sh structure**:
- Modified the template to include `--force` in the compressor command

## Verification Results

All 10 comprehensive checks pass:
1. ✅ Initial build succeeds
2. ✅ Re-run succeeds (overwrite existing file)
3. ✅ Bit-for-bit reproducible (identical SHA-256 across runs)
4. ✅ All exclusions honored (.hg/, vendor/js/, scratch/, .state/, __pycache__/, *.tmp, *.pyc, *.pyo, *.o, *.class, 0600 files)
5. ✅ Metadata normalization (owner 0:0, mtime correct)
6. ✅ Line ending normalization (CRLF → LF for text files)
7. ✅ Binary file preservation (null bytes intact)
8. ✅ Symlink preservation (2 symlinks maintained)
9. ✅ Permission normalization (2 executable files at 0755)
10. ✅ build.sh is executable

## Generalization Beyond v01

This fix addresses a **family invariant** rather than a v01-specific issue:

- **Family invariant**: Build scripts must be re-runnable regardless of existing output files
- **Mechanism**: Compression tools have safety features that prevent accidental overwrites
- **Failure mode**: Test harnesses and development workflows call build scripts multiple times
- **Solution**: Always use force-overwrite flags for compression tools when reading from stdin

This applies to all variants in the deterministic-tarball family, not just v01.

## Files Modified

1. `/app/build.sh` - Added `--force` to zstd command
2. `skill/deterministic-tarball/SKILL.md` - Comprehensive documentation of re-runnability requirement
