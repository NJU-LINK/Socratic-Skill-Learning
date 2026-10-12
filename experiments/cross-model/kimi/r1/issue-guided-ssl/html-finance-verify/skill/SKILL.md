---
name: html-finance-verify
description: Verify HTML financial reports by checking internal consistency of additive and ratio relationships, identifying the single incorrect metric using label-guided coverage analysis and deterministic selection.
---

# HTML Financial Report Verification

This skill verifies HTML earnings reports by parsing displayed values and checking internal consistency through recomputation. It handles cascading failures where a single wrong value causes multiple dependent checks to fail.

## When to Use

Use when instructed to find an incorrect metric in an HTML financial report where:
- Values are displayed with line numbers in the markup
- Exactly one metric violates internal consistency
- Answer requires line number and displayed value
- The wrong value may be a dollar total, subtotal, percentage, or per-share value (axis 2)
- Section names and metric families may vary (axis 1)

## Core Pipeline

1. **Parse HTML** → Extract records with line numbers, labels, raw values
2. **Normalize** → Strip $, %, commas; handle K/M/B unit suffixes; keep raw strings
3. **Recompute relations** → Check additive (totals), ratio (percentages), and per-share consistency
4. **Identify root cause** → Find record participating in ALL failed checks using label-guided involvement
5. **Emit result** → Parse output contract from instruction and write accordingly

## Key Invariants

- Line numbers are *displayed* in markup (`<td class="line">210</td>`), not file line indices
- Exactly one value violates an internal-consistency relation
- Verification is findable by recomputation alone (no external knowledge)
- Both additive (totals) and ratio (percentages) relations must be checked
- A single wrong value may cause multiple dependent checks to fail (cascading)

## Root Cause Selection (Cascading Failures)

When a dollar total is wrong, derived values (operating income, margins) may also appear wrong:

1. **Track involvement**: Each check records which line numbers it involves
2. **Label-guided involvement**: Ratio checks include resolved numerator/denominator based on label
3. **Find root cause**: The line that participates in ALL failed checks
4. **Deterministic fallback**: If no full coverage, prefer: (1) target lines over operands, (2) highest participation, (3) lowest line number

Example: Corrupting line 170 (Total OpEx: 280.6→290.6) with consistent margins:
- Total OpEx check fails (involves 140,150,160,170)
- Operating Income check fails (involves 130,170,180)
- Root cause: 170 (appears in both via full coverage)

## Output Contract Rules (CRITICAL)

**Polarity Rule**: Output the *reported (incorrect)* value as displayed in the document, NOT the corrected calculation.

- Example: If gross margin shows 60.8% but should be 61.8%, output `60.8` not `61.8`
- Do not include the % sign in the output value

**Parse at Runtime**:
- Read the instruction to determine: target file path, field order, separator
- Default when instruction is silent: `line_number,value` to `/app/value.txt`
- Validate written output against instruction format

**Numeric Format**:
- Preserve precision as displayed (e.g., `60.8` not `60.80`)
- Strip formatting symbols ($, %, commas) from output value only

## Traps to Avoid

1. **Polarity**: Output the wrong value as displayed, not the corrected calculation
2. **Example decoy**: Instruction examples are illustrative, not answers
3. **Overfitting**: Don't assume error is always a percentage; check dollar totals too
4. **Cascading misidentification**: Use label-guided coverage, not just counting failures
5. **Expense misclassification**: Exclude "cost of revenue/sales" and "total" from expense lists
6. **Nondeterminism**: Sort all selections; don't rely on set/dict ordering

## Verification Results (Single-Error Mutations)

| Test | Description | Expected | Result |
|------|-------------|----------|--------|
| v01 | Original report (gross margin wrong) | 210,60.8 | ✓ PASS |
| Rename | Revenue→"Total net sales" | 210,60.8 | ✓ PASS |
| Opex | Line 170: 280.6→290.6, margins consistent | 170,290.6 | ✓ PASS |
| Net-income | Line 200: 251.0→261.0, margins consistent | 200,261.0 | ✓ PASS |
| Cascade | Line 130: 520.4→510.4 | 130,510.4 | ✓ PASS |

**Determinism verified**: Net-income mutation produces identical output across 5+ consecutive runs.

## Usage

```bash
python3 scripts/verify_report.py /app/report.html
```

Or programmatically:
```python
from verify_report import find_incorrect_metric
line, value = find_incorrect_metric('/app/report.html')
# Write to output file per instruction contract
with open('/app/value.txt', 'w') as f:
    f.write(f"{line},{value}")
```

## Rounding Tolerance

Use `Decimal` with `ROUND_HALF_UP`. Accept if `|reported - expected| ≤ 0.5 × 10^-d` where d = decimals displayed. Material errors (>0.5 point for 1-decimal percents) separate cleanly from rounding noise.

## Label Synonyms

The script uses synonym matching to handle renamed sections:
- Revenue ≈ `revenue`, `total revenue`, `net sales`, `total net sales`
- Cost of Revenue ≈ `cost of revenue`, `cost of sales`, `cogs`
- See `references/relations.md` for complete list

## Per-Share Values

EPS and per-unit values are checked by searching for explaining pairs (numerator/denominator). Keywords: `eps`, `per share`, `per unit`.
