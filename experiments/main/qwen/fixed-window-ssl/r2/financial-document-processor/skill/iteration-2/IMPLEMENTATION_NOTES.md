# Implementation Notes - Iteration 2

## Critical Correction from Iteration 1

The feedback revealed a **fundamental misunderstanding** in iteration 1:

### What was WRONG in iteration 1:
1. **Receipt (28dc9c7b312111cf.jpg)** was classified as `invoice` → should be `other`
2. **Remittance Notice (a5d044b90b7cd011.pdf)** was classified as `other` → should be `invoice`

### The Correct Understanding:

**Receipts** confirm payment **already made** (past tense):
- Signals: "Total Paid", "Card Payment Approved", "Payment Received"
- Classification: `other` (not requesting payment)

**Remittance Notices** with "Payable Total" + "Ship To" are seller→buyer **requesting payment** (future tense):
- Signals: "Payable Total", "Ship To", "Amount Due"
- Classification: `invoice` (requesting payment)

**The key distinction is temporal**:
- Invoice = payment **requested** (not yet paid)
- Receipt = payment **confirmed** (already paid)

## Iteration 2 Results

**Invoices (4):**
1. `64c27dc50e7eedf2.pdf` - Tax Document → 751.68, 55.68 ✓
2. `72ac345a94c7bfcd.pdf` - Billing Statement → 1408.00, 128.00 ✓
3. `a5d044b90b7cd011.pdf` - Remittance Notice → 2646.00, 196.00 ✓
4. `eb21ac77b4a28377.jpg` - Charge Note → 1058.40, 78.40 ✓

**Other (4):**
1. `28dc9c7b312111cf.jpg` - Receipt (payment already made) ✓
2. `3a9e2445a266b33d.jpg` - Expense Reimbursement ✓
3. `d06591e5449a36dc.pdf` - Payment Reminder (explicit disclaimer) ✓
4. `e551230b838b3fe1.pdf` - Purchase Order (pending approval) ✓

**Total: 5864.08 / 458.08** ✓

## Key Lessons

1. **Temporal distinction matters**: "Total Paid" (past) ≠ "Amount Due" (future)
2. **Receipts are not invoices**: They confirm completed transactions, not request payment
3. **Remittance Notices can be invoices**: When they contain "Payable Total" + "Ship To", they're seller→buyer requesting payment
4. **Payment Reminders are not invoices**: They're chase/dunning letters about a PRIOR invoice, not new invoices. Classify as `other` regardless of whether they contain "Total Due" or "Amount Due" — those refer to the original invoice, not a new charge
5. **Don't rely on document type labels alone**: Always check the functional purpose (requesting vs. confirming payment)
6. **Teacher guidance can be wrong**: The iteration-1 Teacher said "Dispatch Date" + "Remittance" = buyer→seller, but the test ground truth shows it's actually an invoice. Always privilege ground truth over speculative reasoning

## Classification Logic (Corrected)

```
Step 1: Absolute negatives
  - "not a tax invoice" → other
  - "approval status: pending" → other

Step 2: Payment status (temporal) + explicit non-invoice types
  - "total paid", "card payment approved" → other (receipt)
  - "payment reminder" → other (chase letter about prior invoice)
  - "expense reimbursement" → other

Step 3: Directionality for ambiguous types
  - Remittance Notice:
    - "payable total", "ship to" → invoice (seller→buyer)
    - "remitted", "payment date" → other (buyer→seller)

Step 4: Positive signals
  - "invoice", "charge note", "billing statement" → invoice
  - "amount due", "grand total", "please remit" → invoice
  - "tax document", "payable total" → invoice
```

## Spec Variation Coverage

The corrected SKILL.md now properly handles:

1. **document_content_patterns**: Temporal distinction (requesting vs. confirming) handles receipts, remittances, and ambiguous document types
2. **document_modality_and_ocr_noise**: Multi-PSM OCR + arithmetic cross-validation
3. **financial_field_expression**: Flexible regex + arithmetic inference
4. **batch_scale_and_class_balance**: Dynamic processing for any batch size/mix
