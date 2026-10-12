---
name: html-finance-verify
description: Parse HTML financial reports to identify a single incorrect metric through identity-based consistency verification. Cross-checks financial identities to isolate the unique erroneous value.
---

# HTML Financial Report Verification

## Quick Start

```bash
python3 scripts/verify_report.py <input.html> <output.txt>
```

**Input**: HTML file with line-numbered financial metrics  
**Output**: `line_number,value` (no `$`, `%`, or `,`; preserve decimal precision)

## Shipped Script Verification

**SHA256**: `d43794dbbf31f3156bffd688cbbec8b8cd718795e97ed9cb94cf4bb8ef0ca1b6`

Verify before use:
```bash
sha256sum scripts/verify_report.py
python3 -m py_compile scripts/verify_report.py
```

## Test Results (against shipped script)

| Test | Command | Expected | Result |
|------|---------|----------|--------|
| v01 original | `verify_report.py q2_earnings_report.html out.txt` | `210,60.8` | ✓ |
| Wrong total (invariant-preserving) | opex=$290.6, margin=61.8 | `170,290.6` | ✓ |
| Strip CSS | `sed 's/ class="[^"]*"//g'` | `210,60.8` | ✓ |
| Decimal precision | `60.80%` | `210,60.80` | ✓ |
| Synonyms | R&D, S&M, G&A, etc. | `210,60.8` | ✓ |
| Multi-column guard | 3+ value columns | Warning + use first | ✓ |

## How It Works

### 1. Parse HTML

Content-based parsing with multi-column guard:
- Validates: first cell = line number, second = name
- Falls back to content scan if validation fails
- **Multi-column guard**: Warns and uses first column only

### 2. Normalize Names

Synonym mapping (ORDER MATTERS):

```python
SYNONYMS = [
    ('cost_of_revenue', ['cost of revenue', 'cogs', ...]),
    ('sm', ['sales and marketing', 's&m', ...]),  # Before 'revenue'
    ('revenue', ['revenue', 'revenues', ...]),
    ('gross_margin', ['gross margin']),  # Requires '%' in value
    ...
]
```

### 3. Check Identities

**Tolerance derivation** (from display precision):
```python
# Margins: single division
tolerance = 0.6 * 10^(-decimals)

# Additive: error accumulates per term
tolerance = 0.5 * 10^(-decimals) * n_terms * 1.2

# Subtractive: similar to additive with 2 terms
tolerance = 0.5 * 10^(-decimals) * 2 * 1.2
```

### 4. Blame Intersection

```python
# Culprit is in intersection of all failed identities
intersection = set.intersection(*failed)

# Filter out metrics appearing in passed identities
candidates = intersection - passed_metrics

if len(candidates) == 1:
    return candidates.pop()  # Found via intersection

# Fallback: score by (failed_count - passed_count)
return max_score_metric(failed, passed, intersection)
```

## Debug Mode

```bash
python3 scripts/verify_report.py --debug <input.html> <output.txt>
```

Outputs:
- Parsed metrics with canonical names
- Per-identity discrepancy vs tolerance  
- Failed intersection and candidates

## Known Limitations

- **Multi-period tables**: Guarded - warns and uses first column only
- **YoY/Per-share identities**: Parser supports; identities not yet in `build_identities()`
- **EPS calculations**: Not implemented

## Mutation Test Design

**Invariant-preserving wrong total**:
```python
# WRONG: opex=290.6 (creates 2 errors: opex AND margin)
# RIGHT: opex=290.6 AND margin=61.8 (single error: opex)
```

A correct mutation must leave exactly one metric inconsistent with the rest.
