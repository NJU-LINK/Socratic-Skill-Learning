---
name: html-finance-verify
description: Verify internal consistency of HTML financial reports containing income statements and KPI metrics, identify the single incorrect metric, and output its line number and value.
---

# HTML Finance Verify

## Quick Recipe

1. **Extract metrics from HTML** using `html.parser.HTMLParser` (standard library only)
2. **Classify columns by content**: integers → line numbers, `$`/`%` → values, else → names
3. **Verify income statement**: check gross profit, operating expenses, operating income, net income
4. **Verify KPI percentages**: check margins = (metric / revenue) × 100
5. **Output the single inconsistent metric** as `line_number,value`

### Decision Guide: Manual vs. Script

**Use manual computation when:**
- Report has ≤20 metrics (like v01)
- You can extract all values quickly
- You're confident in the arithmetic

**Use `verify_financials.py` when:**
- Report has >20 metrics
- Multiple tables or complex structure
- You want automated verification
- Time is limited

The script is at `/skill/verify_financials.py` and can be run as:
```bash
python3 /skill/verify_financials.py /app/q2_earnings_report.html /app/value.txt
```

## Step-by-Step Methodology

### 1. Parse HTML Tables

Use `html.parser.HTMLParser` to extract all table rows generically:

```python
from html.parser import HTMLParser
import re

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.current_row = []
        self.current_cell = ""
        self.rows = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            self.in_td = True
            self.current_cell = ""
    
    def handle_endtag(self, tag):
        if tag == 'td':
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == 'tr' and self.current_row:
            self.rows.append(self.current_row)
            self.current_row = []
    
    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data
```

### 2. Classify Columns by Content

For each row, identify which cell is which by testing content patterns:

```python
for row in parser.rows:
    line_num_cell = None
    value_cell = None
    name_cell = None
    
    for cell in row:
        if re.match(r'^\d+$', cell):
            line_num_cell = cell  # Pure integer → line number
        elif '$' in cell or '%' in cell:
            value_cell = cell  # Contains $ or % → value
        elif cell and not cell.replace('.', '').replace('-', '').isdigit():
            name_cell = cell  # Everything else → metric name
    
    if line_num_cell and value_cell and name_cell:
        # Extract metric...
```

**Why content-based:** Immune to class name variations (`class="line"` vs `class="lineno"` vs no classes) and column ordering.

### 3. Extract Numeric Values

Strip currency symbols, commas, percent signs. Handle accounting notation (parentheses for negatives):

```python
def extract_numeric(text):
    cleaned = text.replace('$', '').replace(',', '').replace('%', '').strip()
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    return float(cleaned)
```

### 4. Verify Income Statement Relationships

Apply standard accounting relationships with tolerance ±0.01:

- **Gross profit** = Revenue − Cost of revenue
- **Total operating expenses** = Σ(R&D + S&M + G&A + ...)
- **Operating income** = Gross profit − Total operating expenses
- **Net income** = Operating income + Σ(all non-operating items between operating income and net income)

**Note:** Non-operating items include interest expense, interest income, tax, gains/losses, etc. The script identifies these by line number position (items between operating income and net income in the statement).

### 5. Verify KPI Percentages

Margins are typically calculated as % of revenue with tolerance ±0.05 (for rounding):

- **Gross margin** = (Gross profit / Revenue) × 100
- **Operating margin** = (Operating income / Revenue) × 100
- **Net margin** = (Net income / Revenue) × 100

### 6. Identify the Error

The single metric that fails its consistency check is the incorrect one. Output as `line_number,value` (without $ or % symbols).

## Critical Implementation Notes

### Standard Library Only

**NEVER use third-party packages** (bs4, pandas, lxml). Task environments are minimal containers without pip/network. Use only:
- `html.parser` for HTML parsing
- `re` for pattern matching
- `sys`, `os`, `json`, `csv` for data handling

### Metric Name Matching — Prefer Exact Matches

When searching for metrics, use this logic:

```python
def find_metric(by_name, *keywords):
    """Find a metric, preferring exact matches over substring matches."""
    for key, metric in by_name.items():
        for kw in keywords:
            if key == kw:
                return metric  # Exact match wins immediately
    # If no exact match, prefer shortest substring match
    best = None
    for key, metric in by_name.items():
        for kw in keywords:
            if kw in key:
                if best is None or len(key) < len(best[0]):
                    best = (key, metric)
    return best[1] if best else None
```

**Why:** If "Other revenue" appears before "Revenue" in the table, substring matching would return the wrong metric. Exact match prevents this silent bug.

### Keyword Specificity

Use specific keywords to avoid false matches:
- ✓ `'general and'` instead of `'general'` (avoids matching "General revenue")
- ✓ `'cost of revenue'` or `'cogs'` instead of just `'cost'`

## Handling Variations

### Report Structure
- Different class names, column orders, or no classes → content-based classification handles this
- Multiple tables → parser extracts all rows, classifier identifies metrics
- Different section names → keyword-based metric lookup is flexible

### Error Types
- Dollar amount errors → caught by income statement verification
- Percentage errors → caught by KPI verification
- Rounding errors → use tolerance ±0.05 for percentages

### Output Formats
- Read task instructions for exact format requirements
- Preserve the value as shown in the report (without symbols)

## Common Pitfalls

1. **Floating-point precision:** Use tolerance-based comparisons (±0.01 for dollars, ±0.05 for percentages)
2. **Rounding:** Percentages may be rounded; verify within tolerance
3. **Negative values:** Operating expenses are typically positive in reports but subtracted
4. **Metric name collisions:** Prefer exact matches over substring matches
5. **Keyword ambiguity:** Use specific keywords like 'general and' not 'general'
6. **Multiple errors:** Task guarantees exactly one error; if you find multiple, recheck logic
7. **Non-operating items:** Net income verification must account for all items between operating income and net income (interest, tax, gains/losses), not just "other income/expense". Use line number position to identify these items.

## Verification Checklist

Before submitting:
- [ ] All dollar values in income statement are internally consistent
- [ ] All KPI percentages match their calculations (within rounding tolerance)
- [ ] Identified exactly one inconsistent metric
- [ ] Output format matches requirements exactly
- [ ] Line number and value match the HTML report exactly
