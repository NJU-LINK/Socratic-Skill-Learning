# Iteration 3: Critical Pattern Fixes

## Overview

Iteration 3 addresses two concrete gaps identified by the Teacher that could cause failures on unseen variants:
1. **VAT Rate Pitfall**: SKILL.md description was too vague, causing solvers to capture percentage instead of amount
2. **Overly Broad Non-Invoice Patterns**: Three patterns risked false positives on invoices

## Gap 1: VAT Rate Pitfall (Demonstrated Failure)

### The Problem

The Teacher observed that a solver reading SKILL.md wrote:
```python
# WRONG: "VAT 10%: 128.00" → captures "10" (the rate, not the amount)
r'(?:VAT|sales\s+tax|GST)[^\d]*?([\d,]+\.?\d*)'
```

This produced **vat_amount = 10.0** instead of 128.00 for the billing statement.

### Root Cause

The non-greedy `[^\d]*?` stops at the first digit (the "1" in "10%"), capturing the percentage instead of the monetary amount.

### The Fix

Added explicit "CRITICAL PITFALL" section to SKILL.md with WRONG vs RIGHT examples:

```python
# RIGHT: explicitly consumes the optional percentage before capturing
r'(?:VAT|sales\s+tax|GST)[:\s]*(?:\d+%)?[:\s]*[€$£]?\s*([\d,]+\.?\d*)'
                                        ^^^^^^^^
                                   This group is essential.

# WRONG: captures "10" from "VAT 10%: 128.00" instead of "128.00"
r'(?:VAT|sales\s+tax|GST)[^\d]*?([\d,]+\.?\d*)'
```

The `(?:\d+%)?` explicitly skips over "10%" before the capture group runs.

### Why This Matters

Solvers typically read SKILL.md and write their own code; they rarely execute process_documents.py directly. The SKILL.md must make critical pitfalls impossible to miss.

## Gap 2: Three Overly Broad Non-Invoice Patterns

### Pattern 1: `\bP\.?O\.?\b` (weight 3)

**Problem**: Matches "P.O. Box 12345" in invoices, which appears in many billing addresses. A legitimate invoice from "Acme Corp, P.O. Box 500" would get +3 non-invoice score — dangerously close to the threshold of 3.

**Fix**: Changed to `\bp\.?o\.?\s*(number|no|#|\d)` to require PO-specific context:
- ✓ "P.O. Number: 12345" → matches
- ✓ "PO No: 789" → matches
- ✗ "P.O. Box 500" → does NOT match (no "number/no/#/digit" after P.O.)

### Pattern 2: `\bestimate\b` (weight 3)

**Problem**: Matches "Estimated Tax: 180.00" or "Estimated delivery: 5 days", both of which can appear in invoices. The Purchase Order in v01 has "Estimated Tax" but is already correctly classified by the stronger `\bpurchase order\b` (weight 5). If an unseen invoice contains "Estimated Tax" without a stronger non-invoice signal, `\bestimate\b` could push it over the threshold.

**Fix**: Narrowed to `\b(cost|price|budget)\s+estimate\b` — contexts where "estimate" genuinely signals a non-invoice document:
- ✓ "cost estimate" → matches
- ✓ "price estimate" → matches
- ✗ "Estimated Tax" → does NOT match

### Pattern 3: `\bpaid\b` (weight 2)

**Problem**: While word boundaries prevent matching "prepaid", it does match "Paid by check", "Paid in cash", or "Amount Paid" in contexts where these phrases appear on documents that might otherwise look like invoices (e.g., a "Paid" stamp on an invoice copy). Weight 2 combined with `\bcard payment\b` (3) could reach threshold on a receipt that also has weak invoice signals.

**Fix**: Reduced weight from 2 to 1, making it insufficient alone:
- Before: `\bpaid\b` (2) + `\bcard payment\b` (3) = 5 → exceeds threshold
- After: `\bpaid\b` (1) + `\bcard payment\b` (3) = 4 → still exceeds threshold, but less likely to combine with other weak signals

## Verification Results

All 8 documents still correctly classified with improved patterns:

| Document | Classification | Non-Invoice Score | Invoice Score | Notes |
|----------|---------------|-------------------|---------------|-------|
| 28dc9c7b312111cf.jpg | other | 8 | 0 | Receipt (ni reduced from 9→8 due to paid weight change) |
| 3a9e2445a266b33d.jpg | other | 5 | 0 | Expense reimbursement |
| 64c27dc50e7eedf2.pdf | invoice | 0 | 7 | Tax Document + please remit |
| 72ac345a94c7bfcd.pdf | invoice | 0 | 10 | Billing statement |
| a5d044b90b7cd011.pdf | invoice | 0 | 7 | Remittance notice |
| d06591e5449a36dc.pdf | other | 10 | 0 | Payment reminder (negation handling) |
| e551230b838b3fe1.pdf | other | 12 | 0 | Purchase order (still correctly classified) |
| eb21ac77b4a28377.jpg | invoice | 0 | 3 | Charge note |

**Financial Extraction**: All VAT amounts correct, especially 72ac345a94c7bfcd.pdf:
- Text: "VAT 10%: 128.00"
- Extracted: vat_amount = 128.00 ✓ (not 10.0)

## Meta-Lesson: SKILL.md as Implementation Guide

The Teacher's key insight: **SKILL.md is not just a design document; it's an implementation guide**. Solvers read SKILL.md and write their own code. Every critical extraction pattern should have:

1. **An explicit "WRONG vs. RIGHT" example** showing the common mistake
2. **The exact regex with annotations** on the non-obvious parts
3. **A note about *why* the non-obvious part matters** (the concrete failure case)

The classification section already does this well (the negation handling is clearly explained with rationale). The financial extraction section now follows the same standard, especially the VAT rate pitfall.

## Files Updated

1. **SKILL.md** - Added VAT rate pitfall warning, narrowed three overly broad patterns
2. **scripts/process_documents.py** - Updated patterns to match SKILL.md
3. **ITERATION_3_FIXES.md** - This documentation

## Conclusion

Iteration 3 successfully closes the gap between "the script handles this correctly" and "the solver writes correct code from the SKILL.md description". The skill is now more robust to unseen variants and less likely to cause solver implementation errors.
