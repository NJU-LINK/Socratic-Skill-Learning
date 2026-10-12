# Git Leak Recovery — Revision Notes

## Iteration 2 Improvements

### Most Consequential Weakness Addressed
**Fragmented search strategy**: The original skill had many separate per-location search steps (2a-2i), requiring the agent to try each sequentially. For complex repos or unexpected secret locations, this was slow and error-prone.

### Key Changes

#### 1. Unified Scan as Primary Recovery Method (Phase 2.0b)
- **What**: A single command that checks ALL objects (reachable + unreachable) in one pass
- **Why**: 
  - Faster: Single pass instead of multiple sequential searches
  - More robust: Finds the secret regardless of location
  - Covers all object types: blobs, commits (messages), tags (annotations)
- **How**: Union of `git rev-list --all --objects` (reachable) and `git fsck --unreachable --no-reflogs` (unreachable) = ALL objects

#### 2. Working Tree/Index Quick Check (Phase 2.0a)
- **What**: Check if secret is still in a file before scanning git objects
- **Why**: Simplest case first — if the secret is in the working tree or index, no need for complex object scanning
- **How**: `grep -r` on working tree, `git diff --cached` for index

#### 3. Verification Improvements (Phase 4)
- **Fixed**: Loose object check now uses regex `/objects/[0-9a-f]{2}/[0-9a-f]{38}$` to exclude pack/info files
- **Why**: Old approach would produce invalid hashes from pack files (e.g., `packpack-XXX.pack`)
- **Also**: Unreachable object check now covers all types (not just blobs) using `awk '/unreachable/{print $3}'`

#### 4. Updated Decision Flowchart
- Reflects new structure: Quick check → Unified scan → Per-location diagnostics → Cleanup → Verification
- Shows cleanup strategy based on object type found by unified scan

#### 5. Enhanced Key Principles
- Added principles 2-3: Unified scan first, scan covers all object types
- Principle 9: Updated to mention regex filtering for loose objects

### Coverage of Spec Axes

#### secret_location (where the secret is)
- ✓ Unified scan covers ALL locations in one pass
- ✓ Explicitly handles: blobs, commit messages, tag annotations, unreachable objects
- ✓ Per-location diagnostics available for complex cases

#### repo_complexity (size and topology)
- ✓ Unified scan is O(n) single pass, efficient for large repos
- ✓ Handles: multiple branches, tags, merges, dozens of commits
- ✓ Submodule support in per-location diagnostics

#### cleanup_scope (which refs/objects keep the leak recoverable)
- ✓ Universal cleanup (3h) handles all ref types
- ✓ Deletes: replace refs, backup refs (refs/original/), expires reflogs
- ✓ Aggressive gc with --prune=now

### Testing
- Verified unified scan finds secrets in:
  - Blobs (file content) ✓
  - Commits (commit messages) ✓
  - Tags (tag annotations) ✓
  - Unreachable objects ✓
- Verified regex filtering correctly excludes pack/info files ✓
- All 6 v01 tests pass ✓

### Backward Compatibility
- All original per-location searches retained as diagnostic tools (Phase 2.1)
- All cleanup strategies unchanged
- Teacher's iteration-1 gaps (backup refs, subshell bug, filter-branch fallback) still addressed

## Iteration 1 Improvements (from Teacher feedback)

### Gap 1: Backup refs from filter-branch
- Added `refs/original/` deletion to Phase 3h (universal cleanup) BEFORE gc
- Added explicit backup ref cleanup in Phase 3e (filter-branch fallback)

### Gap 2: Subshell variable-scope bug in verification
- Replaced piped `while read` loops with `for ... in $(...)` loops
- Used sentinel file `/tmp/secret_still_found` instead of shell variable

### Gap 3: filter-branch fallback
- Added complete `git filter-branch` implementation in Phase 3e
- Includes immediate `refs/original/` cleanup after filter-branch
