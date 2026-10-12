#!/usr/bin/env python3
"""
HTML Finance Verify - Complete General Solver
Finds the single incorrect metric in an HTML financial report by:
1. Parsing HTML tables to extract line-numbered metrics
2. Classifying metrics via keyword matching
3. Discovering additive and ratio relationships
4. Computing expected values from all relationships
5. Identifying the error via relative consensus clustering
"""
import re, sys, glob, itertools
from html.parser import HTMLParser

###############################################################################
# 1. Find HTML file and output path
###############################################################################
html_files = sorted(glob.glob('/app/*.html') + glob.glob('/app/**/*.html', recursive=True))
if not html_files:
    print("ERROR: No HTML file found in /app/"); sys.exit(1)
html_file = html_files[0]
output_file = '/app/value.txt'

# Check task.yaml for custom output path
for ty in glob.glob('/app/task.yaml') + glob.glob('/app/**/task.yaml', recursive=True):
    try:
        with open(ty) as f:
            content = f.read()
        m = re.search(r'output_file:\s*(\S+)', content)
        if m:
            output_file = m.group(1)
    except Exception:
        pass

print(f"HTML: {html_file}")
print(f"Output: {output_file}")

###############################################################################
# 2. Parse HTML tables
###############################################################################
class TableParser(HTMLParser):
    """Extract table rows from HTML, skipping thead."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.in_td = False
        self.in_table = False
        self.in_thead = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self.in_table = True
            self.current_table = []
        elif tag == "thead":
            self.in_thead = True
        elif tag == "tbody":
            self.in_thead = False
        elif tag == "tr" and self.in_table:
            self.current_row = []
        elif tag in ("td", "th") and self.in_table:
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == "tr" and self.in_table and self.current_row:
            if not self.in_thead:
                self.current_table.append(self.current_row)
            self.current_row = []
        elif tag == "table":
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = []
        elif tag == "thead":
            self.in_thead = False

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data

with open(html_file) as f:
    html_content = f.read()

parser = TableParser()
parser.feed(html_content)

###############################################################################
# 3. Extract metrics and parse values
###############################################################################
def parse_number(s):
    """Parse a financial value string to float. Returns None for non-numeric."""
    s = s.strip().replace('$', '').replace(',', '').replace('%', '').strip()
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    s = s.strip()
    if not s or s in ('—', '-', 'N/A', 'nm', 'n/a'):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def extract_display_value(s):
    """Get numeric part for output (strip $ and %)."""
    s = s.strip().replace('$', '').replace(',', '').strip()
    if s.endswith('%'):
        s = s[:-1].strip()
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    return s.strip()

# metrics: list of (line_num, name, float_value, display_value, is_percentage, raw_value)
metrics = []

for table in parser.tables:
    for row in table:
        if len(row) < 3:
            continue

        line_num = None
        value_str = None
        value_float = None

        # First pass: find line number and value
        for cell in row:
            stripped = cell.strip()
            # Line number: 2-4 digit integer
            if re.match(r'^\d{2,4}$', stripped) and line_num is None:
                line_num = int(stripped)
            elif '%' in cell and parse_number(cell) is not None:
                value_float = parse_number(cell)
                value_str = cell
            elif parse_number(cell) is not None and value_str is None:
                # Make sure it's not the line number itself
                try:
                    if int(stripped) == line_num:
                        continue
                except (ValueError, TypeError):
                    pass
                value_float = parse_number(cell)
                value_str = cell

        if line_num is not None and value_str is not None:
            # Collect name from remaining cells
            name_cells = []
            val_matched = False
            for cell in row:
                stripped = cell.strip()
                if stripped == str(line_num):
                    continue
                try:
                    if int(stripped) == line_num:
                        continue
                except (ValueError, TypeError):
                    pass
                if not val_matched and stripped == value_str.strip():
                    val_matched = True
                    continue
                if stripped:
                    name_cells.append(stripped)

            name = ' '.join(name_cells).lower() if name_cells else 'unknown'
            is_pct = '%' in value_str
            display = extract_display_value(value_str)
            metrics.append((line_num, name, value_float, display, is_pct, value_str))

print(f"\nExtracted {len(metrics)} metrics:")
for m in metrics:
    print(f"  Line {m[0]}: [{m[1]}] = {m[2]} (pct={m[4]}, display='{m[3]}')")

###############################################################################
# 4. Classify metrics by keyword matching
###############################################################################
def classify_metric(name):
    """Classify a metric name into financial categories."""
    n = name.lower()
    cats = set()

    # Income statement items - order matters: check specific before general
    if any(w in n for w in ['cost of revenue', 'cost of goods', 'cogs', 'cost of sales']):
        cats.add('cogs')
    elif any(w in n for w in ['revenue', 'total revenue', 'net revenue']):
        cats.add('revenue')
    elif any(w in n for w in ['net sales']) and 'cost' not in n:
        cats.add('revenue')

    if 'gross profit' in n:
        cats.add('gross_profit')

    # Operating expenses - check combined SG&A first
    if any(w in n for w in ['selling, general', 'sg&a', 'sga']):
        cats.add('sga_combined')
    if any(w in n for w in ['research', 'r&d', 'r & d']):
        cats.add('rd_expense')
    if any(w in n for w in ['sales and marketing', 'selling & marketing', 's&m']):
        cats.add('sm_expense')
    if any(w in n for w in ['general and administrative', 'g&a', 'general & administrative']):
        cats.add('ga_expense')
    if any(w in n for w in ['total operating expense', 'total opex', 'operating expenses']):
        if 'total' in n or 'opex' in n or n.strip().endswith('expenses'):
            cats.add('total_opex')

    if any(w in n for w in ['operating income', 'operating profit', 'ebit']):
        if 'margin' not in n:
            cats.add('operating_income')
    if any(w in n for w in ['other income', 'interest income', 'other expense']):
        cats.add('other_income')
    if any(w in n for w in ['income tax', 'tax provision', 'provision for tax', 'income tax expense']):
        cats.add('tax')
    if any(w in n for w in ['pre-tax', 'pretax', 'income before tax', 'earnings before tax']):
        cats.add('pretax_income')
    if any(w in n for w in ['net income', 'net profit', 'net earnings', 'net loss']):
        if 'margin' not in n:
            cats.add('net_income')
    if 'ebitda' in n and 'margin' not in n:
        cats.add('ebitda')

    # Per-share
    if any(w in n for w in ['eps', 'earnings per share']):
        cats.add('eps')
    if any(w in n for w in ['shares outstanding', 'share count', 'diluted shares', 'basic shares']):
        cats.add('shares')

    # Margin percentages
    if 'gross margin' in n:
        cats.add('gross_margin_pct')
    if 'operating margin' in n:
        cats.add('operating_margin_pct')
    if 'net margin' in n:
        cats.add('net_margin_pct')
    if 'ebitda margin' in n:
        cats.add('ebitda_margin_pct')
    if 'margin' in n and not cats:
        cats.add('margin_pct')

    # Growth / YoY
    if any(w in n for w in ['yoy', 'year-over-year', 'year over year', 'y/o/y']):
        cats.add('yoy_change')
    if any(w in n for w in ['qoq', 'quarter-over-quarter', 'sequential']):
        cats.add('qoq_change')

    # Balance sheet items
    if any(w in n for w in ['total current asset']):
        cats.add('current_assets')
    if any(w in n for w in ['total current liab']):
        cats.add('current_liabilities')
    if any(w in n for w in ['total asset']):
        cats.add('total_assets')
    if any(w in n for w in ['total liab', 'total debt']):
        cats.add('total_liabilities')
    if any(w in n for w in ['total equity', "stockholders' equity", "shareholders' equity",
                             "total stockholders'", "total shareholders'"]):
        cats.add('total_equity')
    if any(w in n for w in ['cash and equivalent', 'cash & equivalent', 'cash, cash equivalent']):
        cats.add('cash')
    elif 'cash' in n and 'flow' not in n:
        cats.add('cash')
    if any(w in n for w in ['inventory', 'inventories']):
        cats.add('inventory')
    if any(w in n for w in ['receivable']):
        cats.add('receivables')
    if any(w in n for w in ['payable']):
        cats.add('payables')
    if any(w in n for w in ['goodwill']):
        cats.add('goodwill')
    if any(w in n for w in ['intangible']):
        cats.add('intangibles')
    if any(w in n for w in ['retained earnings']):
        cats.add('retained_earnings')
    if any(w in n for w in ['working capital']):
        cats.add('working_capital')

    # Cash flow items
    if any(w in n for w in ['capex', 'capital expenditure']):
        cats.add('capex')
    if any(w in n for w in ['operating cash flow', 'cash from operations', 'cash provided by operating']):
        cats.add('operating_cf')
    if any(w in n for w in ['free cash flow', 'fcf']):
        cats.add('fcf')
    if any(w in n for w in ['investing cash flow', 'cash from investing', 'cash used in investing']):
        cats.add('investing_cf')
    if any(w in n for w in ['financing cash flow', 'cash from financing', 'cash used in financing']):
        cats.add('financing_cf')
    if any(w in n for w in ['net change in cash', 'change in cash']):
        cats.add('cash_change')
    if any(w in n for w in ['depreciation', 'amortization']):
        cats.add('da')

    # Dividends
    if any(w in n for w in ['dividend']):
        cats.add('dividend')

    # Financial ratios
    if any(w in n for w in ['current ratio']):
        cats.add('current_ratio')
    if any(w in n for w in ['debt-to-equity', 'debt to equity', 'debt/equity']):
        cats.add('debt_to_equity')
    if any(w in n for w in ['return on equity', 'roe']):
        cats.add('roe')
    if any(w in n for w in ['return on asset', 'roa']):
        cats.add('roa')
    if any(w in n for w in ['quick ratio', 'acid test']):
        cats.add('quick_ratio')

    if not cats:
        cats.add('unknown')

    return cats

line_categories = {}
for l, n, v, d, p, r in metrics:
    line_categories[l] = classify_metric(n)
    print(f"  Line {l} [{n}]: {line_categories[l]}")

def find_lines(*categories):
    """Find lines matching any of the given categories."""
    result = []
    for l, cats in line_categories.items():
        if cats.intersection(set(categories)):
            result.append(l)
    return result

# Build lookup structures
val_map = {l: v for l, n, v, d, p, r in metrics}
name_map = {l: n for l, n, v, d, p, r in metrics}
display_map = {l: d for l, n, v, d, p, r in metrics}
pct_map = {l: p for l, n, v, d, p, r in metrics}
all_lines = list(val_map.keys())

###############################################################################
# 5. Discover relationships
###############################################################################
relations = []  # tight: ('sum', parts, target) or ('ratio', pct_line, num_line, den_line)
wide_relations = []  # wide additive: same format as sum

dollar_lines = [l for l in all_lines if not pct_map[l]]
pct_lines = [l for l in all_lines if pct_map[l]]

# 5a. Tight additive relationships (tolerance 0.15 for 1-decimal rounding)
for target_line in dollar_lines:
    target = val_map[target_line]
    candidates = [l for l in dollar_lines if l != target_line]
    for size in range(2, min(len(candidates) + 1, 7)):
        for subset in itertools.combinations(candidates, size):
            s = sum(val_map[l] for l in subset)
            if abs(s - target) < 0.15:
                rel = ('sum', list(subset), target_line)
                if rel not in relations:
                    relations.append(rel)

print(f"\nTight additive relationships: {len(relations)}")
for r in relations:
    if r[0] == 'sum':
        parts_str = ' + '.join(f"L{l}" for l in r[1])
        print(f"  {parts_str} = L{r[2]}")

# 5b. Wide-tolerance additive (5% of target, for fallback)
for target_line in dollar_lines:
    target = val_map[target_line]
    wide_tol = abs(target) * 0.05
    candidates = [l for l in dollar_lines if l != target_line]
    for size in range(2, min(4, len(candidates) + 1)):  # Only size 2-3 to reduce noise
        for subset in itertools.combinations(candidates, size):
            s = sum(val_map[l] for l in subset)
            diff = abs(s - target)
            if 0.15 < diff <= wide_tol:
                rel = ('sum_wide', list(subset), target_line)
                if rel not in wide_relations:
                    wide_relations.append(rel)

print(f"Wide additive relationships: {len(wide_relations)}")

# 5c. Ratio relationships (keyword-guided)
ratio_templates = [
    ('gross_margin_pct',     ['gross_profit'],              ['revenue']),
    ('operating_margin_pct', ['operating_income'],          ['revenue']),
    ('net_margin_pct',       ['net_income'],                ['revenue']),
    ('ebitda_margin_pct',    ['ebitda'],                    ['revenue']),
    ('margin_pct',           ['gross_profit', 'operating_income',
                              'net_income', 'ebitda'],      ['revenue']),
    ('eps',                  ['net_income'],                ['shares']),
    ('current_ratio',        ['current_assets'],            ['current_liabilities']),
    ('quick_ratio',          ['current_assets', 'cash'],    ['current_liabilities']),
    ('debt_to_equity',       ['total_liabilities'],         ['total_equity']),
    ('roe',                  ['net_income'],                ['total_equity']),
    ('roa',                  ['net_income'],                ['total_assets']),
]

for pct_cat, num_cats, den_cats in ratio_templates:
    for pct_line in find_lines(pct_cat):
        for num_line in find_lines(*num_cats):
            for den_line in find_lines(*den_cats):
                if len(set([num_line, den_line, pct_line])) < 3:
                    continue
                if pct_map.get(num_line, False) or pct_map.get(den_line, False):
                    continue
                if abs(val_map[den_line]) < 0.001:
                    continue
                expected = val_map[num_line] / val_map[den_line] * 100
                # Non-percentage ratios
                if pct_cat in ('eps', 'current_ratio', 'quick_ratio', 'debt_to_equity', 'roe', 'roa'):
                    expected = val_map[num_line] / val_map[den_line]
                # Wide discovery tolerance (catches the error too)
                if abs(expected - val_map[pct_line]) < 2.0:
                    rel = ('ratio', pct_line, num_line, den_line)
                    if rel not in relations:
                        relations.append(rel)
                        print(f"  Ratio: L{pct_line} = L{num_line}/L{den_line}*100 = {expected:.2f} (reported {val_map[pct_line]})")

# 5d. Fallback: brute-force ratios for unmatched percentages
matched_pcts = {r[1] for r in relations if r[0] == 'ratio'}
for pct_line in pct_lines:
    if pct_line in matched_pcts:
        continue
    best_match = None
    best_diff = float('inf')
    for num_line in dollar_lines:
        for den_line in dollar_lines:
            if num_line == den_line:
                continue
            if abs(val_map[den_line]) < 0.001:
                continue
            expected = val_map[num_line] / val_map[den_line] * 100
            diff = abs(expected - val_map[pct_line])
            if diff < best_diff:
                best_diff = diff
                best_match = (num_line, den_line)
    if best_match and best_diff < 1.5:
        rel = ('ratio', pct_line, best_match[0], best_match[1])
        if rel not in relations:
            relations.append(rel)
            print(f"  Fallback ratio: L{pct_line} = L{best_match[0]}/L{best_match[1]}*100")

###############################################################################
# 6. Compute expected values
###############################################################################
# 6. Compute expected values (separate tight and wide)
###############################################################################
expected_tight = {l: [] for l in all_lines}
expected_wide = {l: [] for l in all_lines}

# Tight relationships
for r in relations:
    if r[0] == 'sum':
        parts, target = r[1], r[2]
        expected_tight[target].append(sum(val_map[l] for l in parts))
        for p in parts:
            other_sum = sum(val_map[l] for l in parts if l != p)
            expected_tight[p].append(val_map[target] - other_sum)
    elif r[0] == 'ratio':
        pct_l, num_l, den_l = r[1], r[2], r[3]
        expected_tight[pct_l].append(val_map[num_l] / val_map[den_l] * 100)
        expected_tight[num_l].append(val_map[pct_l] * val_map[den_l] / 100)
        if abs(val_map[pct_l]) > 0.001:
            expected_tight[den_l].append(val_map[num_l] / (val_map[pct_l] / 100))

# Wide relationships (separate dictionary)
for r in wide_relations:
    if r[0] == 'sum_wide':
        parts, target = r[1], r[2]
        expected_wide[target].append(sum(val_map[l] for l in parts))
        for p in parts:
            other_sum = sum(val_map[l] for l in parts if l != p)
            expected_wide[p].append(val_map[target] - other_sum)

print(f"\nExpected values per line (tight):")
for line in sorted(expected_tight.keys()):
    if expected_tight[line]:
        print(f"  Line {line}: reported={val_map[line]}, "
              f"n_tight={len(expected_tight[line])}, "
              f"n_wide={len(expected_wide[line])}, "
              f"sample_tight={[round(v, 2) for v in expected_tight[line][:5]]}")

###############################################################################
# 7. Identify error via relative consensus clustering
###############################################################################
def find_consensus(expected_values, rel_tol=0.005):
    """Find the largest cluster of agreeing expected values.
    Returns (consensus_value, consensus_fraction, cluster_size)."""
    if not expected_values:
        return None, 0, 0
    vals = sorted(expected_values)
    best_cluster = []
    for pivot in vals:
        cluster = [v for v in vals
                   if abs(v - pivot) / max(abs(pivot), 0.001) <= rel_tol]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    consensus = sorted(best_cluster)[len(best_cluster) // 2]
    consensus_frac = len(best_cluster) / len(vals)
    return consensus, consensus_frac, len(best_cluster)

candidates = []
for line in all_lines:
    # Primary: consensus from tight relationships only
    if expected_tight[line]:
        consensus, frac, count = find_consensus(expected_tight[line])
        tight_count = len(expected_tight[line])
    else:
        # No tight relations — try wide as last resort
        if not expected_wide[line]:
            continue
        consensus, frac, count = find_consensus(expected_wide[line])
        if consensus is None:
            continue
        frac *= 0.5  # penalize wide-only consensus
        tight_count = 0
    
    if consensus is None:
        continue
    
    diff = abs(consensus - val_map[line])
    rel_diff = diff / max(abs(val_map[line]), 0.001)

    print(f"  Line {line}: consensus={consensus:.4f}, reported={val_map[line]}, "
          f"rel_diff={rel_diff:.4f}, frac={frac:.2f}, tight_count={tight_count}, "
          f"n_tight={len(expected_tight[line])}, n_wide={len(expected_wide[line])}")

    if frac >= 0.5 and rel_diff > 0.005:
        score = frac * rel_diff * max(tight_count, 1)
        candidates.append((score, rel_diff, line, consensus, frac, tight_count))

candidates.sort(key=lambda x: -x[0])

print(f"\nCandidates ({len(candidates)}):")
for c in candidates:
    score, rel_diff, line, consensus, frac, count = c
    print(f"  Line {line}: score={score:.4f}, rel_diff={rel_diff:.4f}, "
          f"consensus={consensus:.4f}, reported={val_map[line]}, "
          f"display={display_map[line]}, frac={frac:.2f}, count={count}")

###############################################################################
# 8. Select error and write output
###############################################################################
error_line = None
error_display = None

if candidates:
    error_line = candidates[0][2]
    error_display = display_map[error_line]
    print(f"\n*** ERROR: Line {error_line}, value = {error_display} ***")
else:
    print("\nNo clear error via consensus clustering. Trying fallbacks...")

    # Fallback 1: violation counting on tight relationships only
    violation_count = {l: 0 for l in all_lines}
    for r in relations:
        if r[0] == 'sum':
            parts, target = r[1], r[2]
            if abs(sum(val_map[l] for l in parts) - val_map[target]) > 0.15:
                for l in parts + [target]:
                    violation_count[l] += 1
        elif r[0] == 'ratio':
            pct_l, num_l, den_l = r[1], r[2], r[3]
            exp = val_map[num_l] / val_map[den_l] * 100
            if abs(exp - val_map[pct_l]) > 0.15:
                for l in [pct_l, num_l, den_l]:
                    violation_count[l] += 1

    violated = [(l, c) for l, c in violation_count.items() if c > 0]
    violated.sort(key=lambda x: -x[1])
    if violated:
        error_line = violated[0][0]
        error_display = display_map[error_line]
        print(f"  Fallback violation: Line {error_line}, value = {error_display}")

    # Fallback 2: leave-one-out verification
    if error_line is None:
        for cand_line in all_lines:
            all_ok = True
            for r in relations:
                if r[0] == 'sum':
                    parts, target = r[1], r[2]
                    if cand_line in parts + [target]:
                        continue
                    if abs(sum(val_map[l] for l in parts) - val_map[target]) > 0.15:
                        all_ok = False
                        break
                elif r[0] == 'ratio':
                    pct_l, num_l, den_l = r[1], r[2], r[3]
                    if cand_line in [pct_l, num_l, den_l]:
                        continue
                    exp = val_map[num_l] / val_map[den_l] * 100
                    if abs(exp - val_map[pct_l]) > 0.15:
                        all_ok = False
                        break
            if all_ok:
                error_line = cand_line
                error_display = display_map[error_line]
                print(f"  Fallback leave-one-out: Line {error_line}, value = {error_display}")
                break

if error_line is None:
    print("ERROR: Could not identify the incorrect metric!")
    sys.exit(1)

with open(output_file, 'w') as f:
    f.write(f"{error_line},{error_display}\n")

print(f"\nWrote to {output_file}: {error_line},{error_display}")
