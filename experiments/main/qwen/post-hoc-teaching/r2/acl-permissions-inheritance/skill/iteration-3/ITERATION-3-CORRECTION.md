# Iteration 3 Correction: POSIX ACL Group Union Semantics

## Critical Factual Error Corrected

The Teacher identified a fundamental misunderstanding of POSIX.1e ACL group evaluation semantics that appeared in four locations in the skill.

### The Error

The skill incorrectly stated that when a user matches multiple group ACL entries, the kernel uses "the most permissive matching group entry."

### The Correct Semantics

POSIX.1e ACLs use **union** (bitwise OR) of all matching group entries, not "most permissive."

### Why This Matters

Consider a variant with complementary group permissions:
```bash
setfacl -m g:teamA:r-x /path    # read + traverse
setfacl -m g:teamB:-wx /path    # write + traverse
```

If alice is in both `teamA` and `teamB`:
- **Wrong reasoning** (most permissive): alice gets `r-x` (the most permissive single entry)
- **Correct reasoning** (union): alice gets `rwx` (r-x OR -wx = rwx)

The union means alice can read, write, AND traverse — she accumulates all permissions from all matching groups.

### Verification Test

The correction was verified with a container test:

```bash
# Setup
groupadd teamA
groupadd teamB
useradd -G teamA,teamB testmulti

setfacl -m g:teamA:r-x /srv/shared
setfacl -m g:teamB:-wx /srv/shared

# Results
testmulti can:
  ✓ Read (from teamA)
  ✓ Write (from teamB)
  ✓ Traverse (from both)
```

This confirms the union semantics: r-x OR -wx = rwx.

### Four Locations Corrected

1. **Line 55** (ACL Evaluation Order, step 3)
   - Before: "use the most permissive matching group entry"
   - After: "use the **union** (bitwise OR) of all matching group entries"

2. **Line 425** (Decision Framework, Step 3)
   - Before: "the ACL evaluation uses the most permissive matching group entry"
   - After: "the ACL evaluation uses the **union** (bitwise OR) of all matching group entries. For example, if `g:teamA:r-x` and `g:teamB:-wx` are both set and alice is in both groups, alice gets `rwx` (r-x OR -wx = rwx, before mask)."

3. **Line 483** (Multiple Groups section)
   - Before: "the kernel uses the most permissive matching group entry"
   - After: "the kernel takes the union: `rwx OR r-x = rwx`. In this case the result happens to match the most permissive entry, but in general with complementary group permissions (e.g., `g:teamA:r-x` + `g:teamB:-wx`), the union gives `rwx` — permissions accumulate across all matching groups."

4. **Line 543** (Denial Patterns section)
   - Before: "the most permissive is used"
   - After: "the **union** (bitwise OR) of all matching entries is used — permissions accumulate across all groups the user belongs to."

### Practical Impact

For most in-family variants, this distinction doesn't matter because groups typically have aligned or nested permissions (e.g., `rwx` and `r-x` → union is `rwx`, same as most-permissive).

However, variants with complementary split permissions (e.g., one group grants read, another grants write) would produce incorrect effective permissions if you reason with "most permissive" instead of "union." The solver might:
- Set the wrong mask
- Fail to add a named user override for a user who needs restricted access despite being in a permissive group
- Misunderstand the effective permissions for users in multiple groups

This correction is directly relevant to the spec's mention of "principals whose access comes partly from group membership and partly from explicit ACL entries."

### Status

✅ All four occurrences corrected
✅ Union semantics verified with container test
✅ v01 scenario still passes (backward compatibility maintained)
✅ Skill now accurately describes POSIX.1e ACL group evaluation

### Lesson

This error highlights the importance of understanding the precise semantics of POSIX ACLs rather than relying on intuitive but incorrect reasoning. The "most permissive" intuition is wrong because POSIX ACLs are designed to accumulate permissions across all matching group entries, not select a single entry.
