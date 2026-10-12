#!/usr/bin/env python3
"""
HTML Finance Report Verifier - Generalized Version

Identifies the single incorrect metric using three-valued consistency analysis.

Usage:
    python verify_report.py <input_html> <output_file>
"""

import sys
import re
from html.parser import HTMLParser
from typing import Dict, List, Tuple, Optional, Set
from enum import Enum


class Status(Enum):
    """Three-valued logic for relationship checking."""
    UNTESTABLE = 0  # Missing operands - provides no information
    PASS = 1        # Relationship holds within tolerance
    FAIL = 2        # Relationship violated


class FinancialReportParser(HTMLParser):
    """Parse HTML financial report into structured (line, name, value) records."""
    
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_thead = False
        self.current_row = []
        self.current_cell_text = []
        self.headers = []
        self.data = []  # List of (line, name, value_str)
        self.line_col_idx = None
        self.metric_col_idx = None
        self.value_col_idx = None
        self.in_header = False
        self.all_rows = []  # For content-based fallback
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'table':
            self.in_table = True
            self.headers = []
            self.all_rows = []
        elif tag == 'thead':
            self.in_thead = True
        elif tag == 'th':
            self.in_header = True
            self.current_cell_text = []
        elif tag == 'td':
            self.current_cell_text = []
            
    def handle_endtag(self, tag):
        if tag == 'th':
            self.in_header = False
            text = ''.join(self.current_cell_text).strip()
            self.headers.append(text)
            self.current_cell_text = []
        elif tag == 'td':
            text = ''.join(self.current_cell_text).strip()
            self.current_row.append(text)
            self.current_cell_text = []
        elif tag == 'tr':
            if self.current_row:
                self.all_rows.append(self.current_row.copy())
            self.current_row = []
        elif tag == 'thead':
            self.in_thead = False
            self._identify_columns_from_headers()
        elif tag == 'table':
            self.in_table = False
            if self.line_col_idx is None:
                self._identify_columns_from_content()
            self._process_all_rows()
            
    def handle_data(self, data):
        self.current_cell_text.append(data)
        
    def _identify_columns_from_headers(self):
        """Identify columns from header text."""
        headers_lower = [h.lower().strip() for h in self.headers]
        
        for i, h in enumerate(headers_lower):
            if 'line' in h:
                self.line_col_idx = i
            elif h in ['metric', 'item', 'description']:
                self.metric_col_idx = i
            elif 'value' in h:
                self.value_col_idx = i
        
        # Fallback defaults
        if self.line_col_idx is None:
            self.line_col_idx = 0
        if self.metric_col_idx is None and len(self.headers) >= 2:
            self.metric_col_idx = 1
        if self.value_col_idx is None:
            self.value_col_idx = -1
    
    def _identify_columns_from_content(self):
        """Fallback: identify line column by content (all integers)."""
        if not self.all_rows:
            return
        
        num_cols = max(len(r) for r in self.all_rows)
        
        # Find column that is all integers
        for col_idx in range(num_cols):
            all_integers = True
            for row in self.all_rows:
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    if val and not re.match(r'^\d+$', val):
                        all_integers = False
                        break
            if all_integers and len(self.all_rows) > 0:
                self.line_col_idx = col_idx
                break
        
        # Default others
        if self.line_col_idx is None:
            self.line_col_idx = 0
        if self.metric_col_idx is None:
            # Pick middle column that's not line
            candidates = [i for i in range(num_cols) if i != self.line_col_idx]
            if candidates:
                self.metric_col_idx = candidates[0]
        if self.value_col_idx is None:
            self.value_col_idx = -1
    
    def _is_value_cell(self, cell: str) -> bool:
        """Check if cell looks like a financial value ($, %, decimal)."""
        cell = cell.strip()
        if not cell:
            return False
        # Match: optional currency, digits with optional commas, optional decimal, optional %
        return bool(re.match(r'^[$€£]?[\d,]+(\.\d+)?%?$', cell))
    
    def _check_value_column_ambiguity(self):
        """
        Guard: refuse if multiple value-looking columns and no explicit 'value' header.
        This prevents silent mis-selection on multi-period tables (Q2, Q1, etc.).
        """
        if self.value_col_idx is not None and self.value_col_idx != -1:
            return  # Explicit value column found, no ambiguity
        
        if not self.all_rows:
            return
        
        num_cols = max(len(r) for r in self.all_rows)
        value_like_cols = []
        
        for col_idx in range(num_cols):
            # Skip line column
            if col_idx == self.line_col_idx:
                continue
            # Check if this column contains value-looking cells
            has_values = False
            for row in self.all_rows:
                if col_idx < len(row) and self._is_value_cell(row[col_idx]):
                    has_values = True
                    break
            if has_values:
                value_like_cols.append(col_idx)
        
        if len(value_like_cols) > 1:
            # Multiple value-like columns detected - ambiguous
            raise ValueError(
                f"Ambiguous value columns detected: {len(value_like_cols)} columns "
                f"contain numeric/financial data at indices {value_like_cols}. "
                "Multi-period tables require explicit 'Value' header or parser extension."
            )
    
    def _process_all_rows(self):
        """Process all collected rows into structured data."""
        # Guard against silent mis-selection on multi-period tables
        self._check_value_column_ambiguity()
        for row in self.all_rows:
            self._process_row(row)
    
    def _process_row(self, row: List[str]):
        """Extract line, name, value from a data row."""
        if not row:
            return
        
        # Get line number
        if self.line_col_idx is not None and self.line_col_idx < len(row):
            line_text = row[self.line_col_idx]
        else:
            line_text = row[0] if row else ''
        
        line_match = re.search(r'\d+', line_text)
        if not line_match:
            return
        line_num = int(line_match.group())
        
        # Get metric name
        if self.metric_col_idx is not None and self.metric_col_idx < len(row):
            name = row[self.metric_col_idx]
        elif len(row) > 2:
            name = row[1]
        else:
            name = ''
        
        # Get value
        value_idx = self.value_col_idx if self.value_col_idx is not None else -1
        if value_idx < len(row):
            value_str = row[value_idx]
        elif row:
            value_str = row[-1]
        else:
            return
        
        self.data.append((line_num, name, value_str))


def normalize_name(name: str) -> str:
    """Normalize metric name for matching."""
    name = name.lower().strip()
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    
    # Define synonyms in order of specificity (more specific first)
    synonyms_ordered = [
        ('cost_of_revenue', ['cost of revenue', 'cogs', 'cost of sales', 'cost of goods sold']),
        ('gross_profit', ['gross profit', 'gross income']),
        ('total_op_expenses', ['total operating expenses']),
        ('operating_income', ['operating income', 'operating profit', 'income from operations']),
        ('net_income', ['net income', 'net profit', 'earnings']),
        ('research_and_development', ['research and development', 'r and d']),
        ('sales_and_marketing', ['sales and marketing', 'selling and marketing']),
        ('general_and_administrative', ['general and administrative', 'g and a']),
        ('other_income', ['other income', 'other income net']),
        ('revenue', ['total revenue', 'net sales']),
        ('revenue', ['revenue', 'sales']),  # Less specific, check last
        ('gross_margin', ['gross margin']),
        ('operating_margin', ['operating margin']),
        ('net_margin', ['net margin', 'profit margin']),
    ]
    
    # Check for exact match first
    for canonical, variants in synonyms_ordered:
        for variant in variants:
            if name == variant:
                return canonical
    
    # Then check for substring match (word boundaries)
    for canonical, variants in synonyms_ordered:
        for variant in variants:
            if variant in name:
                return canonical
    
    return name


def parse_value(value_str: str) -> Tuple[Optional[float], str]:
    """Parse value string, preserving original for output."""
    original = value_str.strip()
    cleaned = original.replace('$', '').replace('%', '').replace(',', '').strip()
    
    try:
        return float(cleaned), original
    except ValueError:
        return None, original


def build_metric_map(records: List[Tuple[int, str, str]]) -> Tuple[Dict, Dict]:
    """Build metric maps by normalized name and by line number."""
    metrics = {}
    by_line = {}
    
    for line_num, name, value_str in records:
        norm_name = normalize_name(name)
        numeric, original = parse_value(value_str)
        
        if numeric is None:
            continue
        
        entry = {
            'line': line_num,
            'name': name,
            'norm_name': norm_name,
            'value': numeric,
            'original': original,
            'is_percentage': '%' in value_str
        }
        
        by_line[line_num] = entry
        
        if norm_name not in metrics:
            metrics[norm_name] = []
        metrics[norm_name].append(entry)
    
    return metrics, by_line


class Relationship:
    """Base class for checkable relationships."""
    
    def __init__(self, result_name: str, operand_names: List[str]):
        self.result_name = result_name
        self.operand_names = operand_names
    
    def get_result(self, metrics: Dict) -> Optional[Dict]:
        entries = metrics.get(self.result_name, [])
        return entries[0] if entries else None
    
    def get_operands(self, metrics: Dict) -> List[Optional[Dict]]:
        return [metrics.get(n, [None])[0] for n in self.operand_names]
    
    def involves_metric(self, entry: Dict, metrics: Dict) -> bool:
        """Check if this relationship involves the given metric entry."""
        if entry['norm_name'] == self.result_name:
            return True
        if entry['norm_name'] in self.operand_names:
            return True
        return False
    
    def check(self, metrics: Dict, tolerance: float = 0.06) -> Tuple[Status, str]:
        raise NotImplementedError


class SumRelationship(Relationship):
    """Check: result = sum(operands)"""
    
    def check(self, metrics: Dict, tolerance: float = 0.06) -> Tuple[Status, str]:
        operands = self.get_operands(metrics)
        result = self.get_result(metrics)
        
        if any(o is None for o in operands) or result is None:
            return Status.UNTESTABLE, "Missing operands or result"
        
        expected = sum(o['value'] for o in operands)
        actual = result['value']
        diff = abs(actual - expected)
        
        passes = diff <= tolerance or (actual != 0 and diff / abs(actual) <= 0.001)
        
        if passes:
            return Status.PASS, f"{self.result_name} = {actual} (expected {expected})"
        else:
            return Status.FAIL, f"{self.result_name}: {actual} vs expected {expected} (diff {diff:.2f})"


class DifferenceRelationship(Relationship):
    """Check: result = operand1 - operand2"""
    
    def __init__(self, result_name: str, op1_name: str, op2_name: str):
        super().__init__(result_name, [op1_name, op2_name])
        self.op1_name = op1_name
        self.op2_name = op2_name
    
    def check(self, metrics: Dict, tolerance: float = 0.06) -> Tuple[Status, str]:
        op1 = metrics.get(self.op1_name, [None])[0]
        op2 = metrics.get(self.op2_name, [None])[0]
        result = self.get_result(metrics)
        
        if op1 is None or op2 is None or result is None:
            return Status.UNTESTABLE, "Missing operands or result"
        
        expected = op1['value'] - op2['value']
        actual = result['value']
        diff = abs(actual - expected)
        
        passes = diff <= tolerance or (actual != 0 and diff / abs(actual) <= 0.001)
        
        if passes:
            return Status.PASS, f"{self.result_name} = {actual}"
        else:
            return Status.FAIL, f"{self.result_name}: {actual} vs expected {expected} (diff {diff:.2f})"


class RatioRelationship(Relationship):
    """Check: result = (numerator / denominator) * scale"""
    
    def __init__(self, result_name: str, num_name: str, den_name: str, scale: float = 100):
        super().__init__(result_name, [num_name, den_name])
        self.num_name = num_name
        self.den_name = den_name
        self.scale = scale
    
    def check(self, metrics: Dict, tolerance: float = 0.06) -> Tuple[Status, str]:
        num = metrics.get(self.num_name, [None])[0]
        den = metrics.get(self.den_name, [None])[0]
        result = self.get_result(metrics)
        
        if num is None or den is None or result is None:
            return Status.UNTESTABLE, "Missing operands or result"
        
        if den['value'] == 0:
            return Status.UNTESTABLE, "Division by zero"
        
        expected = (num['value'] / den['value']) * self.scale
        actual = result['value']
        diff = abs(actual - expected)
        
        passes = diff <= tolerance
        
        if passes:
            return Status.PASS, f"{self.result_name} = {actual}%"
        else:
            return Status.FAIL, f"{self.result_name}: {actual}% vs expected {expected:.1f}% (diff {diff:.1f}%)"


def define_relationships() -> List[Relationship]:
    """Define all checkable relationships."""
    return [
        DifferenceRelationship('gross_profit', 'revenue', 'cost_of_revenue'),
        SumRelationship('total_op_expenses', ['research_and_development', 'sales_and_marketing', 'general_and_administrative']),
        DifferenceRelationship('operating_income', 'gross_profit', 'total_op_expenses'),
        SumRelationship('net_income', ['operating_income', 'other_income']),
        RatioRelationship('gross_margin', 'gross_profit', 'revenue', 100),
        RatioRelationship('operating_margin', 'operating_income', 'revenue', 100),
        RatioRelationship('net_margin', 'net_income', 'revenue', 100),
    ]


def build_metrics_without(metrics: Dict, exclude_entry: Dict) -> Dict:
    """Build metrics dict excluding the given entry."""
    result = {}
    for name, entries in metrics.items():
        new_entries = [e for e in entries if e['line'] != exclude_entry['line']]
        if new_entries:
            result[name] = new_entries
    return result


def analyze_with_three_valued_logic(
    metrics: Dict, 
    by_line: Dict, 
    relationships: List[Relationship], 
    tolerance: float = 0.06
) -> Optional[Dict]:
    """
    Find incorrect metric using (a)+(b)+(c) rule:
    
    M is the culprit iff:
    (a) Every relationship NOT involving M PASSES
    (b) Every TESTABLE relationship involving M FAILS  
    (c) M participates in at least one TESTABLE relationship
    
    Uses full metric set; filters by involvement. Does NOT remove suspects.
    """
    candidates = []
    
    for line_num, suspect in by_line.items():
        # Check (c): does M participate in any TESTABLE relationship?
        participates = False
        for rel in relationships:
            status, _ = rel.check(metrics, tolerance)
            if status != Status.UNTESTABLE and rel.involves_metric(suspect, metrics):
                participates = True
                break
        
        if not participates:
            continue
        
        # Check (a): all relationships NOT involving M must PASS
        a_satisfied = True
        for rel in relationships:
            if rel.involves_metric(suspect, metrics):
                continue
            status, msg = rel.check(metrics, tolerance)
            if status == Status.FAIL:
                a_satisfied = False
                break
            # UNTESTABLE is fine - provides no information
        
        if not a_satisfied:
            continue
        
        # Check (b): all TESTABLE relationships involving M must FAIL
        b_satisfied = True
        for rel in relationships:
            if not rel.involves_metric(suspect, metrics):
                continue
            status, msg = rel.check(metrics, tolerance)
            if status == Status.UNTESTABLE:
                continue
            if status == Status.PASS:
                b_satisfied = False
                break
        
        if b_satisfied:
            candidates.append(suspect)
            print(f"  Line {suspect['line']} ({suspect['name']}): CANDIDATE")
    
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) == 0:
        print("ERROR: No candidate found - check relationships and tolerance")
        return None
    else:
        print(f"ERROR: {len(candidates)} candidates found - underdetermined")
        for c in candidates:
            print(f"  - Line {c['line']}: {c['name']}")
        return None


def find_incorrect_metric(html_path: str, tolerance: float = 0.06) -> Optional[Tuple[int, str]]:
    """Main entry point."""
    print(f"Parsing {html_path}...")
    
    with open(html_path, 'r') as f:
        parser = FinancialReportParser()
        parser.feed(f.read())
    
    print(f"Found {len(parser.data)} records")
    
    metrics, by_line = build_metric_map(parser.data)
    
    print(f"\nMetrics by normalized name:")
    for name, entries in sorted(metrics.items()):
        for e in entries:
            print(f"  {name}: Line {e['line']} = {e['original']} (parsed: {e['value']})")
    
    relationships = define_relationships()
    
    print(f"\nChecking {len(relationships)} relationships:")
    for rel in relationships:
        status, msg = rel.check(metrics, tolerance)
        status_str = {Status.PASS: 'PASS', Status.FAIL: 'FAIL', Status.UNTESTABLE: 'N/A'}[status]
        print(f"  [{status_str}] {msg}")
    
    print(f"\nAnalyzing with three-valued logic:")
    culprit = analyze_with_three_valued_logic(metrics, by_line, relationships, tolerance)
    
    if culprit is None:
        return None
    
    # Extract output value (strip unit symbols, preserve digit string)
    output_value = re.sub(r'[$€£%\s]', '', culprit['original']).strip()
    print(f"\nCULPRIT: Line {culprit['line']}, Value '{output_value}'")
    
    return culprit['line'], output_value


def main():
    if len(sys.argv) != 3:
        print("Usage: python verify_report.py <input_html> <output_file>")
        sys.exit(1)
    
    html_path = sys.argv[1]
    output_path = sys.argv[2]
    
    result = find_incorrect_metric(html_path)
    
    if result is None:
        print("Failed to find incorrect metric")
        sys.exit(1)
    
    line_num, value = result
    
    with open(output_path, 'w') as f:
        f.write(f"{line_num},{value}")
    
    print(f"\nWritten to {output_path}: {line_num},{value}")


if __name__ == "__main__":
    main()
