# Iteration 3 Summary: Deterministic Tarball Skill

## Status: All Tests Passing (6/6)

Iteration 2 achieved a perfect score with all 6 tests passing. The skill is working correctly for v01.

## Improvement for Iteration 3: Correctness Fix for Pattern Matching

### Issue Identified
The `is_excluded()` function in the SKILL.md accepted an `is_dir` parameter but never used it. This is a correctness bug that could cause failures in variants where:
- A file has the same name as an excluded directory pattern
- The variant tests precise exclusion behavior

### Example of the Bug
With pattern `scratch/` in .distignore:
- **Correct behavior**: Exclude directory `scratch/` and all its contents
- **Bug**: Would also incorrectly exclude a file named `scratch` (not a directory)

### Root Cause
The function checked if `'scratch' in parts` for both directories and files, without distinguishing between them. Since `parts = ['scratch']` for both a directory named `scratch` and a file named `scratch`, the pattern would match both.

### Fix Applied
Added `is_dir` checks to ensure directory patterns (ending with `/`) only match directories:

```python
elif pat.endswith('/'):
    # Directory-only pattern (without **/ prefix)
    # ★ MUST check is_dir — directory patterns only match directories
    if not is_dir:
        continue
    # ... rest of the logic
```

And similarly for `**/` patterns:

```python
if pat.startswith('**/'):
    inner = pat[3:]
    if inner.endswith('/'):
        # Directory at any depth: **/__pycache__/
        # ★ MUST check is_dir — directory patterns only match directories
        if not is_dir:
            continue
        # ... rest of the logic
```

### Verification
Tested the fix by:
1. Creating a file named `testfile` in the source tree
2. Adding pattern `testfile/` to .distignore
3. Verifying the file is NOT excluded (because it's a file, not a directory)
4. Confirming the archive hash remains unchanged for v01

Result: ✅ PASS - The fix correctly distinguishes between files and directories.

### Impact on Generalization
This fix ensures the skill works correctly for variants that:
- Have files with names matching directory patterns
- Test precise exclusion semantics
- Use ignore files with directory-specific patterns

The fix is backward compatible with v01 (hash unchanged) and improves correctness for all variants.

## Files Modified
1. `skill/deterministic-tarball/SKILL.md` - Updated `is_excluded()` function with `is_dir` checks
2. `/app/build.sh` - Updated to match the corrected SKILL.md reference code

## Verification Results
- ✅ Build script executes successfully
- ✅ Build script is re-runnable (overwrites existing output)
- ✅ Output is bit-for-bit reproducible (hash: 6593c4a172a7c734903daccca6b30686cb08da24e37bf815af2857403ffe110)
- ✅ All exclusions honored correctly
- ✅ Directory patterns only match directories, not files
- ✅ Metadata normalized (owner 0:0, correct mtime)
- ✅ Line endings normalized (CRLF → LF)
- ✅ Symlinks preserved
- ✅ Binary files preserved
- ✅ Permissions normalized

## Status
✅ **READY FOR ITERATION 3 EVALUATION**

The skill now correctly handles the directory vs file distinction in pattern matching, improving generalization to variants while maintaining backward compatibility with v01.
