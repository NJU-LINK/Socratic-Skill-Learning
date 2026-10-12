---
name: html-finance-verify
description: Extract line-numbered financial metrics from HTML reports, discover cross-check relationships (additive, ratio, growth), and identify the single internally inconsistent metric using a two-tolerance relationship discovery approach.
---

# HTML Financial Verification Skill

## Purpose

This skill solves HTML financial report verification tasks where:
- An HTML document contains line-numbered financial values (dollar amounts and/or percentages)
- Values are connected by internal accounting relationships (totals, margins, ratios)
- **Exactly one value** is incorrect while all others are mutually consistent
- The task is to identify the incorrect metric's line number and displayed value

## Family Pattern

Every instance in this family shares:
1. **HTML report** with line-numbered financial values in tables
2. **Internal consistency** — accounting relationships connect the values
3. **Single error** — one value violates a cross-check; all others are correct
4. **Deterministic output** — report the line number and displayed value of the error

Variation dimensions (per spec.yaml):
- **Report structure**: income statement, balance sheet, cash flow, KPI sidebars, different section names and layouts
- **Metric types**: totals, subtotals, margins, YoY changes, per-share values, unit conversions
- **Error types**: wrong total, wrong margin percentage, wrong growth rate, rounding errors
- **Output format**: target file path, numeric precision, comma/whitespace handling

## Core Methodology: Extract → Discover → Cross-Check → Verify → Report

### Step 1: Extract All Labeled Values

Parse the HTML to find every (line_number, label, value, type) tuple:
- **Line numbers**: cells containing pure integers (e.g., `<td class="line">110</td>`)
- **Values**: cells containing numeric financial data with `$` or `%` markers
- **Labels**: text descriptions of metrics (e.g., "Revenue", "Gross margin")
- **Types**: classify as `dollar`, `percentage`, or `plain`

**Robust parsing requirements**:
- Handle various HTML structures (different class names, table layouts)
- Support accounting notation: `$(123.4)` for negatives, commas as thousands separators
- Preserve raw text for exact output formatting

### Step 2: Discover Cross-Check Relationships

Identify three categories of accounting relationships:

#### Additive Relationships (Dollar Values)
- **Pairwise**: `a - b = c` (e.g., Revenue − Cost of Revenue = Gross Profit)
- **Pairwise**: `a + b = c` (e.g., R&D + S&M = Subtotal)
- **Multi-way subset sums**: `a + b + c + ... = total` (e.g., R&D + S&M + G&A = Total OpEx)
  - Handles cases where intermediate subtotals don't exist
  - Checks subsets of size 2-4 to keep computation tractable

#### Ratio Relationships (Dollars → Percentages)
- **Margins**: `a / b × 100 = p` (e.g., Gross Profit / Revenue × 100 = Gross Margin %)

#### Growth Relationships (Dollars → Percentages)
- **YoY Change**: `(a - b) / b × 100 = p` (e.g., (Revenue_2025 - Revenue_2024) / Revenue_2024 × 100)

**Two-tolerance discovery strategy**:
1. **Wide tolerance** (5.0 for dollars, 3.0 for percentages): discover *potential* relationships
   - Catches relationships where one value is wrong but others are correct
   - Example: Gross Profit / Revenue = 61.8% vs reported Gross Margin = 60.8% (diff = 1.0)
2. **Tight tolerance** (0.15 for both): check if relationships hold exactly
   - Accounts for rounding to 1 decimal place
   - Relationships passing tight tolerance are "solid"
   - Relationships failing tight tolerance but passing wide tolerance are "failing"

**Fallback elimination approach**:
If blame assignment is inconclusive:
1. For each candidate value v:
   - Remove v from the dataset
   - Discover relationships among remaining values (tight tolerance)
   - Count passing relationships
   - Check if v violates any relationship among remaining values
2. The candidate whose removal yields maximum consistency + maximum violations is the answer

### Step 3.5: Verify the Candidate

After identifying a candidate wrong value, **verify the answer** before outputting:

**Check 1: Remaining consistency**
- Remove the candidate from the dataset
- Discover all tight-tolerance relationships among remaining values
- Confirm all discovered relationships pass (they should, since tight tolerance was used for discovery)
- Log the count of passing relationships

**Check 2: Violated relationship**
- For percentage candidates: check ratio relationships among remaining dollar values
  - Compute a/b × 100 for all pairs of remaining dollar values
  - Find a ratio that is close to the candidate (within WIDE_PCT) but doesn't match tightly (> TIGHT_PCT)
  - **Critical guard**: verify this ratio isn't already explained by another remaining percentage (the "already_matched" check)
  - If found, the candidate violates this relationship

- For dollar candidates: check additive relationships among remaining values
  - Check if a+b or a-b should equal the candidate
  - Verify no other remaining value already satisfies this relationship
  - If found, the candidate violates this relationship

**Check 3: Recompute correct value**
- The violated relationship reveals what the candidate *should* be
- Log the computed correct value vs the reported value
- This confirms the candidate is genuinely wrong

**Fallback**: If verification fails, try the elimination approach and verify that candidate.

**Why verification matters**:
- Prevents silent failures from coincidental relationships
- Example: if Revenue=500, Cost=250, Gross Profit=250, then Cost/Gross Profit = 100% coincidentally
- Without the "already_matched" guard, this could create false positives
- Verification is cheap (O(n²)) and high-impact

### Step 4: Report the Result

Output format: `line_number,value`
- **line_number**: the line number shown in the HTML (integer)
- **value**: the **incorrect displayed value** (not the corrected value)
- Preserve exact formatting from HTML (decimal places, no percent sign)
- Write to the target file specified in the task instruction

## Implementation: verify.py Script

### Usage

```bash
python3 verify.py <html_file> [output_file]
```

**Arguments**:
- `html_file`: path to the HTML financial report
- `output_file`: optional path to write the result (default: stdout)

**Output**: `line_number,value` (e.g., `210,60.8`)

### Key Features

1. **Robust HTML parsing**: Uses `html.parser.HTMLParser` (standard library, no external dependencies)
2. **Flexible value extraction**: Handles `$`, `%`, parentheses for negatives, comma separators
3. **Two-tolerance relationship discovery**: Wide tolerance for discovery, tight for validation
4. **Multiple relationship types**: Pairwise additive, multi-way subset sums (up to 4 elements), ratio, and growth relationships
5. **Blame-based error identification**: Identifies the value that violates relationships while partners are solid
6. **Post-identification verification**: Confirms the candidate actually violates a computable relationship and that removing it produces a fully consistent remaining set, preventing silent failures from coincidental relationships
7. **Fallback elimination method**: Handles edge cases where blame assignment is ambiguous
8. **Exact output formatting**: Preserves the displayed numeric format from the HTML

### Design Decisions

**Why two tolerances?**
- Single-tolerance approach fails when the wrong value prevents relationship discovery
- Wide tolerance discovers *potential* relationships even when one value is wrong
- Tight tolerance validates which relationships actually hold
- Example: If Gross Margin is wrong (60.8% vs correct 61.8%), the relationship Gross Profit / Revenue ≈ Gross Margin is discovered with wide tolerance (diff = 1.0 < 3.0) but fails tight tolerance (diff = 1.0 > 0.15)

**Why blame assignment instead of elimination?**
- Elimination is O(n⁴) — expensive for large datasets
- Blame assignment is O(n²) — fast and scalable
- Elimination is a fallback for ambiguous cases

**Why preserve raw text for output?**
- Task requires the *displayed* value, not the corrected value
- Different reports may use different precision (1 decimal, 2 decimals, integers)
- Parsing and re-formatting may introduce errors
- Extracting from raw text ensures exact match

## Generalization Strategy

### Handling Structural Variation

The script does **not** hardcode:
- Specific metric names (Revenue, Gross Profit, etc.)
- Specific relationships (which metrics sum to which totals)
- HTML structure (class names, table layout, section organization)

Instead, it:
- Extracts all line-numbered values generically
- Discovers relationships by testing all possible arithmetic combinations
- Identifies the error by finding the outlier in relationship consistency

### Handling Error Type Variation

The script handles:
- **Wrong totals**: detected via additive relationship failures
- **Wrong margins**: detected via ratio relationship failures
- **Wrong growth rates**: detected via growth relationship failures
- **Rounding errors**: handled by tight tolerance (0.15)
- **Large errors**: handled by adaptive wide tolerance (escalates if needed)

### Handling Output Format Variation

The script:
- Extracts the raw displayed value from HTML
- Preserves decimal places and formatting
- Outputs without percent signs (as required)
- Writes to the specified output file

## Testing and Validation

### v01 Test Case

**Input**: `q2_earnings_report.html` (Ridgeway Robotics Q2 earnings)
- 10 dollar values (income statement)
- 3 percentage values (KPI margins)
- Error: Gross margin reports 60.8% but should be 61.8% (520.4 / 842.0 × 100)

**Expected output**: `210,60.8`

**Actual output**: `210,60.8` ✓

**Verification**:
```bash
python3 /skill/scripts/verify.py /app/q2_earnings_report.html /app/value.txt
cat /app/value.txt  # Output: 210,60.8
```

### Relationship Discovery Trace (v01)

```
Potential relationships: 27
Passing (tight): 14
  - Revenue - Cost = Gross Profit ✓ (pairwise)
  - Gross Profit - Total OpEx = Operating Income ✓ (pairwise)
  - Operating Income + Other Income = Net Income ✓ (pairwise)
  - R&D + S&M + G&A = Total OpEx ✓ (subset-sum, 3 elements)
  - Operating Income / Revenue = Operating Margin (28.5%) ✓
  - Net Income / Revenue = Net Margin (29.8%) ✓
  - ... (and reverses/additional subset-sums)

Failing (tight): 13
  - Gross Profit / Revenue = 61.8% vs Gross Margin = 60.8% (diff = 1.0)
  - ... (variants of the same relationship)

Blame assignment:
  - Gross Profit: solid (appears in passing additive + subset-sum relationships)
  - Revenue: solid (appears in passing additive relationships)
  - Gross Margin: NOT solid (only appears in failing ratio relationship)
  → Gross Margin is the incorrect metric

Verification:
  - 12 remaining metrics after removing Gross Margin
  - 6 passing additive, 6 passing subset-sum, 2 passing ratio relationships
  - Violated: Cost of revenue/Gross profit = 61.8% vs reported 60.8%
  - ✓ VERIFIED: Candidate should be 61.8 but reports 60.8
```

## Limitations and Edge Cases

1. **Coincidental relationships**: With many values, some arithmetic relationships may hold by coincidence. The blame-based approach mitigates this by requiring the wrong value to violate relationships while partners are solid. The verification step provides an additional safeguard.

2. **Very large errors**: If the error is larger than the wide tolerance, the relationship won't be discovered. The script escalates tolerances adaptively (5.0 → 10.0 → 20.0 → 50.0).

3. **No percentages**: If the report contains only dollar values, ratio relationships can't be checked. The script falls back to additive and subset-sum relationships only.

4. **Plain numbers**: If percentages lack `%` signs, the script tries treating plain numbers as percentages for ratio checks.

5. **Large subset sums**: The script checks subsets up to size 4. Larger subsets (5+ elements) are not checked to keep computation tractable, but this covers most real-world financial reports.

## Reusability

This skill applies to any HTML financial verification task where:
- Values are line-numbered and tabular
- Internal accounting relationships exist
- Exactly one value is incorrect
- The task requires identifying the error's line number and displayed value

The script is **domain-agnostic** — it works for income statements, balance sheets, cash flow statements, KPI dashboards, and any other financial report structure.
