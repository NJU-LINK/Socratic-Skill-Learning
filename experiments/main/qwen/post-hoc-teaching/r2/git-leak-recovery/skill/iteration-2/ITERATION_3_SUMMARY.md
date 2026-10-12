# Git Leak Recovery — Iteration 3 Summary

## Teacher Feedback Addressed

### Gap 1 (Critical): Verification only checked blobs in packs
**Problem**: Phase 4 verification used `grep ' blob '` filter on packed objects, missing secrets in packed commits and tags.

**Fix**: Replaced the three-part verification (loose + packed + unreachable) with a single re-run of the unified scan from Phase 2. This:
- Checks ALL object types (blobs, commits, tags) regardless of storage location
- Is simpler and more maintainable (one command instead of three)
- Reuses the same mental model from Phase 2
- Guarantees full coverage

### Gap 2 (Important): No working examples for commit-message secrets
**Problem**: Phase 3e only showed `--index-filter` (for files) and `--blob-callback` (for blob content). If the unified scan found a secret in a commit message, the agent had no working code to clean it.

**Fix**: Added concrete examples for both tools:
- **filter-repo**: `--message-callback` with regex substitution
- **filter-branch**: `--msg-filter` with sed

Also expanded Phase 3d to explain when to use it (tag objects vs lightweight tags).

## Changes Made

### Phase 3d: Annotated tags
- Added explanation of when to use (unified scan reports `FOUND in tag <hash>`)
- Clarified distinction between annotated tags (have tag object) and lightweight tags (point to commit)

### Phase 3e: Reachable history
- **Option A (filter-repo)**: Added `--message-callback` example with regex
- **Option B (filter-branch)**: Added `--msg-filter` example with sed

### Phase 4: Verification
- Replaced three-part verification with unified scan re-run
- Simplified from ~40 lines to ~25 lines
- Now covers all object types automatically

### Key Principles
- Added principle 9: Match cleanup tool to object type
- Updated principle 10: Verify with unified scan (not separate checks)
- Renumbered to 11 principles total

### Decision Flowchart
- Updated verification step to say "re-run unified scan" instead of "sentinel-file approach"

## Coverage Matrix

| Secret Location | Recovery | Cleanup | Verification |
|----------------|----------|---------|--------------|
| Unreachable blob | ✓ Unified scan | ✓ 3a + 3h | ✓ Unified scan |
| Reachable blob (committed) | ✓ Unified scan | ✓ 3e + 3h | ✓ Unified scan |
| Commit message | ✓ Unified scan | ✓ 3e (msg-filter) + 3h | ✓ Unified scan |
| Tag annotation | ✓ Unified scan | ✓ 3d + 3h | ✓ Unified scan |
| Stash | ✓ Unified scan | ✓ 3b + 3h | ✓ Unified scan |
| Reflog-only commit | ✓ Unified scan | ✓ 3f + 3h | ✓ Unified scan |
| Replace ref | ✓ Unified scan | ✓ 3c + 3h | ✓ Unified scan |
| Submodule | ✓ Per-location diag | ✓ 3g + 3h | ✓ Unified scan |

## Key Improvements

1. **Unified scan for both recovery and verification**: Single source of truth, covers all object types
2. **Complete cleanup examples**: File content, blob content, commit messages, tag annotations
3. **Clearer decision tree**: Object type from unified scan → appropriate cleanup tool
4. **More maintainable**: Fewer moving parts, consistent approach throughout

## Testing Status

- ✓ All 6 v01 tests pass
- ✓ Unified scan verified to find secrets in blobs, commits, and tags
- ✓ Verification now covers packed commits and tags (previously missed)
- ✓ Commit-message cleanup examples provided for both filter-repo and filter-branch

## Final Skill Stats

- **Lines**: 530
- **Phases**: 4 (Reconnaissance, Recovery, Cleanup, Verification)
- **Recovery methods**: 11 (unified scan + per-location diagnostics)
- **Cleanup strategies**: 8 (3a-3h)
- **Key principles**: 11
