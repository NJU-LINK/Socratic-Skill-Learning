# Skill Iteration 2 Summary: html-finance-verify

## Teacher Feedback Analysis

The Teacher identified a **critical gap** in iteration 1: the solver never executed solve.py.

**Evidence from trajectory:**
```json
"skillResourceReads": ["SKILL.md"],
"skillResourceExecutions": []
```

**Root cause:** SKILL.md was a methodology document with code snippets. The solver read it, extracted the approach, and manually reimplemented everything. This is fragile because:
- The ad-hoc code won't have multi-layered discovery (strict → relaxed → fallback)
- It won't have `difference_first_minus_rest` encoding
- It won't have the exhaustive fallback search
- For complex variants (YoY growth, per-share, cascading dollar-value errors), the ad-hoc code will likely fail

## Changes Made

### Primary Fix: Added "Step 0: Execute solve.py"

**Before:** SKILL.md started with "Step 1: Read Task Instructions" and provided code snippets for manual implementation.

**After:** SKILL.md now starts with:

```markdown
### Step 0: Execute the Pre-Built Solver (Primary Path)

**Before implementing anything manually, execute the tested solver.**

```bash
cp /skill/solve.py /app/solve.py
cd /app && python3 solve.py
```

**If solve.py succeeds**, verify the output and you're done.

**If solve.py fails or is not available**, follow Steps 1-5 below.
```

**Impact:** This changes the solver's behavior from "read methodology → reimplement" to "run tested code → only reimplement if needed."

### Secondary Fix: format_output Bug

**Before:**
```python
if clean.startswith('(') and clean.endswith(')'):
    clean = '-' + clean[1:-1]  # BUG: converts (45.2) to -45.2
```

**After:**
```python
if clean.startswith('(') and clean.endswith(')'):
    clean = clean[1:-1]  # Correct: converts (45.2) to 45.2
```

**Rationale:** The task says output the value "as shown" in the report. If the report shows `(45.2)`, the output should be `45.2` (stripping parens but not adding a minus sign).

## Verification

Tested the updated workflow:
```bash
cp /skill/solve.py /app/solve.py
cd /app && python3 solve.py
```

**Result:**
- ✓ solve.py executed successfully
- ✓ Built 10 checks (7 additive, 3 ratio)
- ✓ Identified 1 failing check (Gross margin)
- ✓ Applied constraint-based localization
- ✓ Found error: Line 210 (Gross margin = 60.8%)
- ✓ Output: `210,60.8`

## Spec Axis Coverage

### Axis 1: report_structure_and_metric_relationships
**Status:** ✓ Covered
- solve.py handles varied HTML structures
- N-way additive combinations (2, 3, 4 components)
- Name-based and value-based relationship discovery

### Axis 2: error_type_and_discoverability
**Status:** ✓ Covered
- Additive errors (totals, subtotals)
- Ratio errors (margins, rates)
- Growth errors (YoY changes)
- Per-share errors (EPS)
- Unit conversion errors
- Cascading errors (dollar value wrong → multiple checks fail)

### Axis 3: output_format_constraints
**Status:** ✓ Covered
- Reads task.yaml for output format
- Flexible numeric formatting
- Preserves value "as shown" (no sign conversion)

## Files

- **SKILL.md** (491 lines): Now includes Step 0 (execute solve.py) + fallback steps
- **solve.py** (567 lines): Complete implementation with multi-layered localization
- **README.md**: Usage guide
- **ITERATION_SUMMARY.md**: Documents v1→v2 improvement (constraint-based localization)
- **ITERATION_2_SUMMARY.md**: This file (documents Step 0 addition)
- **DEVELOPMENT_SUMMARY.md**: Original development notes

## Key Insight

The highest-leverage improvement was **not** adding more code or relationship types — it was **changing the solver's execution flow** from "read and reimplement" to "execute the tested solver."

This ensures:
1. The robust, tested implementation is used first
2. Complex variants (cascading errors, N-way relationships) are handled correctly
3. The solver only falls back to manual implementation if solve.py fails
4. The skill package is used as intended (solve.py is the primary artifact)

## Conclusion

Iteration 2 addressed the critical gap identified by the Teacher: the solver was ignoring solve.py and reimplementing everything ad-hoc. By adding "Step 0: Execute solve.py" as the primary instruction, the skill now ensures the tested implementation is used first, with manual steps as fallback only.

This single change is the highest-leverage improvement for variant robustness across the html-finance-verify family.
