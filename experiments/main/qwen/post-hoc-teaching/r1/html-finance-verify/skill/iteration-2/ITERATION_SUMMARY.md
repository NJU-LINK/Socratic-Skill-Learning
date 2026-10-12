# Skill Iteration Summary: Constraint-Based Error Localization

## Problem Identified by Teacher

The original v1 solver used a **heuristic approach** for error localization:
```python
# If there's a ratio violation, assume the ratio metric is wrong
for detail in violation_details:
    if detail['type'] == 'ratio':
        return detail['ratio']  # WRONG ASSUMPTION
```

This breaks when dollar values (not percentages) are the error. Example:
- If "Total operating expenses" is wrong, it causes cascading failures in additive checks
- A downstream ratio check might also fail
- The heuristic sees "ratio violation" and returns the margin percentage — but the root cause is the dollar value

## Solution: Constraint-Based Single-Fault Localization

### Key Insight

If metric S is the **only** wrong value, then:
1. **ALL checks involving S must FAIL** (S's wrong value propagates to every check it participates in)
2. **ALL checks NOT involving S must PASS** (they're independent of S)

This distinguishes the error from metrics that merely participate in a failing check as inputs.

### Example: v01 Seed Task

**Error**: Gross margin (line 210) = 60.8% (should be 61.8%)

**Check analysis**:
- Line 210 (Gross margin): involving(pass=0, fail=1), unrelated(pass=9, fail=0)
  - All checks involving it fail ✓
  - No checks involving it pass ✓
  - All unrelated checks pass ✓
  - **→ This is the error**

- Line 110 (Revenue): involving(pass=5, fail=1), unrelated(pass=4, fail=0)
  - Has 5 PASSING checks involving it
  - **→ Revenue is correct** (if it were wrong, those 5 checks would fail)

### Example: Dollar-Value Variant

**Error**: Total operating expenses (line 170) = $285.6 (should be $280.6)

**Check analysis**:
- Line 170 (Total OpEx): involving(pass=0, fail=2), unrelated(pass=8, fail=0)
  - Both additive checks involving it fail ✓
  - No checks involving it pass ✓
  - All unrelated checks pass ✓
  - **→ This is the error**

- Line 140 (R&D): involving(pass=0, fail=1), unrelated(pass=8, fail=1)
  - Has 1 unrelated failure (the Total OpEx check)
  - **→ R&D is correct** (the unrelated failure is caused by Total OpEx being wrong)

## Algorithm Implementation

```python
def find_incorrect_metric(metrics):
    checks = gather_all_checks(metrics)
    failing = [c for c in checks if not c.passes]
    
    if not failing:
        return exhaustive_search(metrics)
    
    # For each candidate line, classify checks
    for suspect_line in all_lines:
        involving_pass = checks involving suspect that PASS
        involving_fail = checks involving suspect that FAIL
        unrelated_fail = checks NOT involving suspect that FAIL
        
        # Strict single-fault: no unrelated failures, all involving checks fail
        if unrelated_fail == 0 and involving_fail > 0 and involving_pass == 0:
            return find_metric_by_line(suspect_line)
    
    # Relaxed fallback: allow involving passes
    # Weighted vote fallback
    # Majority vote fallback
```

## Additional Improvements

### 1. N-Way Additive Discovery

Original v1 only checked pairs summing to a total. Real income statements have 3+ component sums:
- Total OpEx = R&D + S&M + G&A (3-way)
- Total Revenue = Product Revenue + Service Revenue + Other Revenue (3-way)

Fixed by extending `_try_combinations()` to check 2, 3, and 4-way sums.

### 2. Fixed Additive Pattern Key Mismatches

Original v1 had typos in `additive_patterns`:
- `'totaloperatingexpense'` (singular) vs actual `'totaloperatingexpenses'` (plural)
- Missing component patterns

Fixed by correcting keys and adding comprehensive pattern coverage.

### 3. Better Relationship Encoding

Added explicit encoding for difference-based relationships:
- `gross_profit = revenue - cost_of_revenue`
- `operating_income = gross_profit - total_operating_expenses`
- `net_income = pretax_income - income_tax`

This ensures all standard income statement relationships are checked.

## Testing Results

### v01 Seed Task (Percentage Error)
- **Input**: Ridgeway Robotics Q2 report with wrong Gross margin
- **Expected**: Line 210, value 60.8
- **Result**: ✓ Correct

### Dollar-Value Variant
- **Input**: Modified report with wrong Total operating expenses ($285.6 vs $280.6)
- **Expected**: Line 170, value 285.6
- **Result**: ✓ Correct

## Why This Matters for the Family

The spec axis `error_type_and_discoverability` states:
> "Variants may use totals, subtotals, margins, year-over-year changes, per-share values, unit conversions, or rounded figures"

The constraint-based approach handles **all** these error types uniformly:
- **Totals/Subtotals**: Detected via additive relationship failures
- **Margins**: Detected via ratio relationship failures
- **YoY changes**: Detected via growth calculation failures
- **Per-share values**: Detected via EPS calculation failures
- **Unit conversions**: Detected via cross-unit relationship failures

The algorithm doesn't assume error type — it finds the unique metric whose correction resolves all violations.

## Files Updated

1. **solve.py** (v2): Complete rewrite with constraint-based localization
2. **SKILL.md**: Updated documentation explaining the algorithm and why heuristics fail
3. **README.md**: Added explanation of the improvement

## Key Takeaway

**Don't use heuristics for error localization.** Use constraint satisfaction: find the unique metric whose wrong value explains all failures without causing independent checks to fail. This works for any error type and any report structure.
