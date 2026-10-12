# Deterministic Tarball Skill - Implementation Summary

## What Was Built

A complete, tested implementation of deterministic release packaging that creates bit-for-bit reproducible tar.zst archives from source trees.

## Key Components

### 1. `/app/build.sh` (Working Implementation)
- Executable script that produces `/app/release.tar.zst`
- Implements all requirements from the task specification
- Handles all edge cases in the v01 test case

### 2. `skill/deterministic-tarball/SKILL.md` (Reusable Knowledge)
- Comprehensive documentation of the staging-area architecture
- Step-by-step implementation guide with code examples
- Explanation of critical mechanisms and pitfalls
- Verification procedures
- Adaptation guidance for variations

### 3. `skill/deterministic-tarball/references/build.sh` (Reference Implementation)
- Template script that can be adapted for different projects
- Demonstrates the complete workflow

## Verified Requirements

✓ **Exclusion rules**: Parses .distignore with gitignore-style patterns including `**` wildcards
✓ **0600 file exclusion**: Removes files with mode exactly 0600 (sensitive files)
✓ **Permission normalization**: 
  - Directories → 0755
  - Files with shebang or execute bit → 0755
  - All other files → 0644
✓ **Line ending normalization**: Converts CRLF to LF for text files only (detected via `file --mime-encoding`)
✓ **Binary preservation**: Binary files remain unchanged
✓ **Timestamp normalization**: Uses SOURCE_DATE_EPOCH or default 946684800 (2000-01-01)
✓ **Owner/group normalization**: Sets to 0:0 with numeric storage
✓ **Deterministic ordering**: Uses `--sort=name` for consistent entry order
✓ **GNU tar format**: Handles long filenames natively
✓ **Deterministic compression**: zstd with `-19 --long --no-check --single-thread`
✓ **Symlink preservation**: Maintains symlinks as symlinks, never follows them
✓ **Bit-for-bit reproducibility**: Verified with sha256sum across multiple runs
✓ **Special character handling**: Correctly handles spaces, `$`, `\`, `!`, and very long filenames
✓ **Deep nesting**: Handles 40+ levels of directory nesting

## Critical Mechanisms Documented

1. **Staging-area pattern**: Never modify source in-place
2. **`**` pattern handling**: Strip prefix before matching (not literal directory)
3. **Permission check order**: Detect shebang/exec BEFORE chmod
4. **Text/binary detection**: Use `file --mime-encoding -b`
5. **Tar determinism flags**: `--sort=name`, `--single-thread`, `--mtime="@EPOCH"`
6. **zstd overwrite**: Use `-f` flag to overwrite existing files

## Test Results

All 10 verification checks pass:
1. ✓ Build script executes successfully
2. ✓ Excluded paths not in archive
3. ✓ 0600 files excluded (empty directories remain)
4. ✓ Permissions normalized correctly
5. ✓ Symlinks preserved
6. ✓ Line endings normalized (CRLF→LF for text, binary unchanged)
7. ✓ Timestamps set correctly
8. ✓ Bit-for-bit deterministic
9. ✓ build.sh is executable
10. ✓ SOURCE_DATE_EPOCH handling works

## Reusability

The skill package is designed to adapt to:
- Different source tree structures
- Different exclusion rule syntaxes
- Different permission schemes
- Different compression settings
- Different archive formats
- Different timestamp sources

The core pattern (staging → exclude → normalize → deterministic tar → compress) remains constant across all variations.
