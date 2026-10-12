---
name: html-finance-verify
description: >
  Verify internal consistency of an HTML financial report containing line-numbered
  metrics (dollar values and/or KPI percentages), identify the single incorrect metric,
  and output its line number and displayed value. Handles arbitrary income statement
  structures, diverse KPI ratios, varied HTML layouts, and cascading errors.
---

# HTML Finance Verify

## Quick Start

**Run the automated solver:**

1. Read `solve.py` from the skill package (path shown when you loaded the skill):
   ```
   read(<skill-package-path>/solve.py)
   ```

2. Write it to `/app/solve.py` using the `write` tool OR a heredoc in task_shell:
   ```bash
   cat > /app/solve.py << 'EOF'
   [paste the content of solve.py here]
   EOF
   ```

3. Execute the solver:
   ```bash
   python3 /app/solve.py
   ```

4. Verify the output:
   ```bash
   cat /app/value.txt
   ```

**Important:** The skill package files exist on the host filesystem, NOT inside the `/app` container. You cannot use `cp` to copy them. You must read the file content and recreate it in `/app`.

The solver automatically:
- Parses the HTML to extract line-numbered metrics
- Cross-checks dollar arithmetic (gross profit, OpEx, operating income, net income)
- Verifies KPI percentages against dollar values
- Resolves cascading errors using "max checkable relationships" tiebreaker
- Writes the incorrect metric's line number and value to `/app/value.txt`

**Use the solver on every variant**, even if the report looks simple. Manual computation works for v01 but fails on harder variants with cascading errors or unfamiliar KPI names.

## Task Summary

Given an HTML financial report with line-numbered metrics, exactly one metric is
incorrect while all others are internally consistent. Find the wrong metric and write
`line_number,value` to the designated output file.

## Core Algorithm

### Phase 1: Parse the HTML

Extract all line-numbered metric rows from the HTML. Each row contains:
- A **line number** (explicitly shown in the report, NOT raw file line numbers)
- A **metric name** (label text)
- A **value** (dollar amount or percentage)

**Parsing strategy:**
- Use Python's `html.parser.HTMLParser` (stdlib) or BeautifulSoup if available
- Look for table rows (`<tr>`) containing cells with line numbers, labels, and values
- Line numbers may be in `<td class="line">`, `<span>`, or other elements — search for
  cells containing small integers (typically 3-digit numbers like 100, 110, 120...)
- Distinguish dollar values (contain `$`) from percentages (contain `%`)
- Handle formatting: `$1,234.5`, `(56.7)` for negatives, `60.8%`, etc.

**Robustness patterns:**
- Case-insensitive metric name matching
- Normalize whitespace and special characters
- Handle commas as thousands separators: remove them before parsing numbers
- Handle parentheses as negative indicators: `(123.4)` → `-123.4`
- Look for notes in the HTML about rounding precision and denominator conventions

### Phase 2: Define Relationships

Build two sets of checkable relationships:

**Dollar arithmetic relationships:**

| Relationship | Formula |
|---|---|
| Gross profit | Revenue − Cost of revenue |
| Total operating expenses | Sum of individual OpEx items (R&D, S&M, G&A, etc.) |
| Operating income | Gross profit − Total operating expenses |
| Pre-tax income | Operating income + Other income − Other expenses |
| Net income | Pre-tax income − Income tax expense |
| Net income (alt.) | Operating income + Other income, net (if combined) |

**KPI percentage relationships:**

| KPI name pattern | Formula | Denominator |
|---|---|---|
| Gross margin | Gross profit / Revenue × 100 | Revenue |
| Operating margin | Operating income / Revenue × 100 | Revenue |
| Net margin / Net profit margin | Net income / Revenue × 100 | Revenue |
| R&D (as % of revenue / intensity / ratio) | R&D / Revenue × 100 | Revenue |
| S&M (as % of revenue / intensity / ratio) | S&M / Revenue × 100 | Revenue |
| G&A (as % of revenue / intensity / ratio) | G&A / Revenue × 100 | Revenue |
| OpEx (as % of revenue) | Total OpEx / Revenue × 100 | Revenue |
| COGS (as % of revenue) | COGS / Revenue × 100 | Revenue |
| EBITDA margin | EBITDA / Revenue × 100 | Revenue |
| Free cash flow margin | FCF / Revenue × 100 | Revenue |
| Current ratio | Current assets / Current liabilities | Current liabilities |
| Debt-to-equity | Total debt / Total equity | Total equity |
| EPS / Earnings per share | Net income / Shares outstanding | Shares outstanding |

**Brute-force fallback for unknown KPIs:** When a KPI name doesn't match any known pattern, try dividing every dollar item by revenue and see which produces a match. This catches novel KPI names like "Research intensity" or "Marketing efficiency ratio".

**Alias mapping for common line items:**

| Canonical name | Common aliases |
|---|---|
| Revenue | Total revenue, Net revenue, Net sales, Sales |
| Cost of revenue | COGS, Cost of goods sold, Cost of sales |
| Gross profit | Gross margin (dollar amount) |
| R&D | Research and development, Research & development |
| S&M | Sales and marketing, Sales & marketing, Selling expenses |
| G&A | General and administrative, General & administrative |
| Total OpEx | Total operating expenses, Operating expenses |
| Operating income | Operating earnings, EBIT, Income from operations |
| Other income | Other income/expenses net, Non-operating income |
| Net income | Net earnings, Net profit, Profit for the period |
| Tax expense | Income tax, Provision for income taxes |

### Phase 3: Cascading Error Resolution (Root Cause Finding)

**Critical insight:** The error might cascade. If Revenue is wrong, it cascades to gross
profit (wrong), operating income (wrong), net income (wrong), AND all margins (wrong).
You'd see ~4 dollar mismatches and ~3 KPI mismatches. Simply "taking the first mismatch"
gives the wrong answer.

**The correct algorithm:** For each candidate item, hypothesize it's the single error.
Remove it and check if all remaining items are internally consistent. The item whose
removal leaves zero remaining inconsistencies is the root cause.

```
for each candidate in all_items:
    mismatches, checked = check_all_relationships(exclude_line=candidate.line)
    if mismatches == 0 and checked > best_checked:
        best_candidate = candidate
        best_checked = checked
```

**Why "max checkable" works as a tiebreaker:**

When you remove the TRUE error:
- All other items are correct → 0 mismatches
- The number of checkable relationships is relatively high because removing a KPI
  (or a leaf dollar item) doesn't cascade into making other checks impossible

When you remove a CORRECT item:
- The actual error is still present → at least some relationships fail
- The rare exception: removing the correct item makes the error's dependent relationship
  uncheckable. But this always reduces the total checkable count, which is exactly
  why "max checkable" breaks the tie.

**Example:** If Gross margin KPI is wrong (line 210):
- Remove line 210 → 6 relationships checkable, 0 mismatches ✓
- Remove line 130 (Gross profit) → 4 relationships checkable, 0 mismatches (fewer)
- The algorithm picks line 210 because it has more checkable relationships

### Phase 4: Report the Error

Write the output in the required format:
- `line_number` is the number shown in the HTML next to the incorrect metric
- `value` is the incorrect value as displayed, stripped of `%` or `$` signs
- Format: `line_number,value` (e.g., `210,60.8`)

## Rounding and Precision

- Check the HTML for notes about rounding (e.g., "rounded to one decimal place")
- If no explicit note, infer precision from the displayed values themselves
- Compare `round(computed, precision)` vs `round(displayed, precision)`
- Use tolerance of 0.001 after rounding to handle floating-point edge cases

## HTML Structure Variations

The report may use different layouts:
- **Two-panel layout**: Income statement on left, KPI sidebar on right
- **Single table**: All metrics in one table, mixed dollar and percentage values
- **Multiple sections**: Separate tables for income statement, balance sheet, cash flows
- **Nested tables**: Sub-tables within sections

**Structural invariants to rely on:**
- Line numbers are always explicitly displayed (in some cell/element per row)
- Each metric has a label and a value in the same row
- Dollar values and percentages are visually/formatting-distinguishable
- Notes about precision/denominators are typically in a `<p>` or footnote element

## Error Type Variations

The single error could be:
1. **Wrong KPI percentage** — displayed value doesn't match recomputed ratio
2. **Wrong subtotal** — dollar value doesn't match sum of components
3. **Wrong line item** — a raw dollar figure is incorrect, breaking downstream totals
4. **Wrong margin** — percentage computed from correct dollars but displayed wrong
5. **Wrong YoY change** — growth rate doesn't match current vs. prior values
6. **Wrong per-share value** — EPS doesn't match net income / shares
7. **Unit conversion error** — value in wrong units (thousands vs. millions)

## Verification Checklist

Before writing output, confirm:
- [ ] All line numbers are extracted from HTML elements, not raw file lines
- [ ] The root cause algorithm found exactly one candidate with 0 mismatches
- [ ] Rounding precision matches the report's stated or implied precision
- [ ] Output value matches exactly what's displayed (minus % or $ sign)
- [ ] No external knowledge was needed — error is purely from internal consistency
