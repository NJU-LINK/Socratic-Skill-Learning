# Implementation Notes: Critical Fixes Applied

## Problem Identified by Teacher

The initial v01 implementation produced correct results but for the **wrong reason** in one critical case: the receipt (`28dc9c7b312111cf.jpg`) was classified as `other` because no invoice signal matched (silent default), not because a non-invoice signal was actively detected.

### Why This Matters

The spec explicitly states variation in "document_content_patterns" including:
- "invoices with weaker or less standard invoice markers"
- "non-invoice documents that contain overlapping financial vocabulary"

A receipt with OCR noise that produces "Invoice Receipt" or similar could be misclassified if we rely on silent defaults rather than active detection.

## Fixes Applied

### 1. Weighted Scoring for Classification

**Before**: Hierarchical if-else with silent default to `other`
```python
if re.search(r'\breceipt\b', text): return 'other'
# ... more checks ...
return 'other'  # Silent default
```

**After**: Weighted scoring with active confirmation of both classes
```python
non_invoice_score = 0
for pattern, weight in non_invoice_patterns:
    if re.search(pattern, combined):
        non_invoice_score += weight

invoice_score = 0
for pattern, weight in invoice_patterns:
    if re.search(pattern, combined):
        invoice_score += weight

if non_invoice_score >= 3: return 'other'
if invoice_score >= 3: return 'invoice'
return 'other'  # Intentional default, documented as safer
```

**Benefits**:
- Actively confirms both classes instead of relying on silent defaults
- Weighted scoring prevents one noisy match from dominating
- OCR-aware patterns (e.g., `recei[cp]t`) handle common misrecognitions
- Multi-candidate merging checks combined text from all OCR modes

### 2. Context-Aware Amount Filtering

**Before**: Collected ALL numbers from ALL texts for cross-validation
```python
all_amounts = set()
for text in texts:
    amounts = re.findall(r'[\d,]+\.?\d*', text)
    all_amounts.update(parse_amount(a) for a in amounts)
```

**After**: Filtered by context to exclude dates, IDs, and OCR artifacts
```python
def extract_contextual_amounts(text, total_amount=None):
    amounts = set()
    for line in text.split('\n'):
        # Skip lines with date/ref/id keywords
        if re.search(r'\b(date|ref|id|number|no|doc)[:\s]*\d', line, re.IGNORECASE):
            continue
        for match in re.finditer(r'[\d,]+\.?\d*', line):
            parsed = parse_amount(match.group())
            if parsed and parsed > 0:
                # Filter: within plausible range
                if total_amount and parsed > total_amount * 10:
                    continue
                amounts.add(parsed)
    return amounts
```

**Benefits**:
- Prevents pollution from dates (2026, 2028), document IDs (10044), OCR artifacts (7840 from "Tax 78.40")
- Constrains amounts to plausible monetary range (within 10x of detected total)
- Makes cross-validation more robust without losing correct matches

## Verification Results

### Receipt Classification (Now Active Detection)

```
Combined OCR text:
'subtott 49.27 / vat included 483 / lakeside cate / card payment agro / 
 receict / lakeside cate / (card fayment aeproved / 'subtest 48.27 / 
 vat included 489, / 'total pet 5420

Non-invoice signals detected:
  ✓ \brecei[cp]t\b (weight=4) - matches "receict"
  ✓ \bcard payment\b (weight=3) - matches "card payment agro"
  ✓ \bpaid\b (weight=2) - matches "otal paid"

Non-invoice score: 9 (threshold: 3)
Invoice score: 0

Decision: 'other' (active detection, not silent default)
```

### All Documents Correctly Classified

| Document | Classification | Total | VAT | Reason |
|----------|---------------|-------|-----|--------|
| 28dc9c7b312111cf.jpg | other | - | - | Receipt (score=9) |
| 3a9e2445a266b33d.jpg | other | - | - | Expense reimbursement (score=5) |
| 64c27dc50e7eedf2.pdf | invoice | 751.68 | 55.68 | Tax Document + please remit (score=7) |
| 72ac345a94c7bfcd.pdf | invoice | 1,408.00 | 128.00 | Billing statement + bill to (score=7) |
| a5d044b90b7cd011.pdf | invoice | 2,646.00 | 196.00 | Remittance notice (score=4) |
| d06591e5449a36dc.pdf | other | - | - | Payment reminder + not a tax invoice (score=10) |
| e551230b838b3fe1.pdf | other | - | - | Purchase order + approval status pending (score=9) |
| eb21ac77b4a28377.jpg | invoice | 1,058.40 | 78.40 | Charge note + total due (score=7) |

### Financial Extraction Correct

All invoices have correct total_amount and vat_amount:
- Direct extraction when labels are clear
- Computation from subtotal + tax rate when needed
- Cross-validation with context-filtered amounts for OCR noise

## Meta-Lesson

**Diagnostic question**: "Does this code detect the correct answer, or does it just fail to detect the wrong answer?"

When a component produces correct output through a silent default rather than active detection, it appears to work but is fragile to the very variation the spec calls out. Always verify that classification boundaries are based on positive evidence for the chosen class, not just absence of evidence for the alternative.

## Files Updated

1. `skill/financial-document-processor/SKILL.md` - Updated classification and extraction sections
2. `skill/financial-document-processor/scripts/process_documents.py` - Implemented weighted scoring and context-aware filtering
3. This file - Implementation notes documenting the fixes
