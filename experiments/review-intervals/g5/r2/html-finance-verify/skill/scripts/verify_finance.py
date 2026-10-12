#!/usr/bin/env python3
"""
HTML Financial Verification Script

Parses an HTML earnings report, extracts financial metrics, discovers
relationships between them, and identifies the single incorrect value.

Usage:
    python3 verify_finance.py <html_file> <output_file>

Example:
    python3 verify_finance.py /app/q2_earnings_report.html /app/value.txt
"""

import sys
import re
from html.parser import HTMLParser
from itertools import combinations
from typing import List, Tuple, Dict, Set, Optional


class FinancialHTMLParser(HTMLParser):
    """Parse HTML to extract (line_number, label, value) triples from tables."""
    
    def __init__(self):
        super().__init__()
        self.entries = []
        self.current_row = []
        self.current_cell = ""
        self.in_td = False
        self.in_table = False
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.in_table = True
        elif tag == "td":
            self.in_td = True
            self.current_cell = ""
        elif tag == "tr" and self.in_table:
            self.current_row = []
    
    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data
    
    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == "tr" and self.in_table and self.current_row:
            # Process completed row - detect which column has the line number
            if len(self.current_row) >= 3:
                line_idx = None
                for i, cell in enumerate(self.current_row):
                    if re.match(r'^\d+$', cell.strip()):
                        line_idx = i
                        break
                
                if line_idx is not None:
                    line_num = int(self.current_row[line_idx].strip())
                    # Label is the next non-numeric cell after line number
                    label = ""
                    value_str = ""
                    for i in range(line_idx + 1, len(self.current_row)):
                        cell = self.current_row[i].strip()
                        if not label and not re.match(r'^[\$\(\-]?[\d,\.]+[\)%]?$', cell):
                            label = cell
                        elif label and not value_str:
                            value_str = cell
                            break
                    
                    if label and value_str:
                        numeric_val = self.parse_numeric_value(value_str)
                        if numeric_val is not None:
                            self.entries.append({
                                'line': line_num,
                                'label': label,
                                'value': numeric_val,
                                'raw_value': value_str,
                                'is_percentage': self.is_percentage(value_str, label)
                            })
            self.current_row = []
        elif tag == "table":
            self.in_table = False
    
    def parse_numeric_value(self, value_str: str) -> Optional[float]:
        """Parse numeric value from string, handling $, %, commas, parentheses for negatives."""
        cleaned = value_str.strip()
        
        # Handle accounting notation for negatives: ($123.4) or (123.4)
        negative = False
        if cleaned.startswith('(') and cleaned.endswith(')'):
            negative = True
            cleaned = cleaned[1:-1].strip()
        
        # Remove common formatting
        cleaned = cleaned.replace('$', '').replace('%', '').replace(',', '')
        cleaned = cleaned.strip()
        
        # Handle leading minus sign
        if cleaned.startswith('-'):
            negative = not negative
            cleaned = cleaned[1:]
        
        # Try to parse as float
        try:
            val = float(cleaned)
            return -val if negative else val
        except ValueError:
            return None
    
    def is_percentage(self, value_str: str, label: str) -> bool:
        """Determine if a value is a percentage based on format or label."""
        if '%' in value_str:
            return True
        label_lower = label.lower()
        if any(kw in label_lower for kw in ['margin', 'rate', 'ratio', 'yield', 'growth', 'change']):
            return True
        return False


def parse_html_file(filepath: str) -> List[Dict]:
    """Parse HTML file and extract financial entries."""
    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    parser = FinancialHTMLParser()
    parser.feed(html_content)
    
    # Fallback to regex if HTMLParser didn't find entries
    if not parser.entries:
        parser.entries = parse_with_regex(html_content)
    
    return parser.entries


def parse_with_regex(html_content: str) -> List[Dict]:
    """Fallback regex-based parser for well-structured HTML."""
    entries = []
    # Pattern to match: <td class="line">123</td><td>Label</td><td class="num">$456.7</td>
    pattern = r'<td[^>]*class="line"[^>]*>(\d+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*class="num"[^>]*>([^<]+)</td>'
    
    for match in re.finditer(pattern, html_content, re.IGNORECASE):
        line_num = int(match.group(1))
        label = match.group(2).strip()
        value_str = match.group(3).strip()
        
        parser = FinancialHTMLParser()
        numeric_val = parser.parse_numeric_value(value_str)
        is_pct = parser.is_percentage(value_str, label)
        
        if numeric_val is not None:
            entries.append({
                'line': line_num,
                'label': label,
                'value': numeric_val,
                'raw_value': value_str,
                'is_percentage': is_pct
            })
    
    return entries


def discover_additive_relationships(entries: List[Dict]) -> List[Tuple]:
    """
    Discover additive relationships: result = sum(components) or result = A - B
    Uses structure-aware discovery (line number proximity) + brute force fallback.
    Returns list of tuples:
      ('sum', result_line, [component_lines])
      ('diff', result_line, positive_line, negative_line)
    """
    relationships = []
    dollar_entries = [e for e in entries if not e['is_percentage']]
    
    # Strategy 1: Label-based heuristics with structure awareness
    for entry in entries:
        if entry['is_percentage']:
            continue
        
        label_lower = entry['label'].lower()
        
        # Check for "total" or "subtotal" keywords
        if 'total' in label_lower or 'subtotal' in label_lower:
            # Find components that sum to this total
            # Prefer components with line numbers close to (but less than) the total
            potential_components = []
            for other in dollar_entries:
                if other['line'] == entry['line']:
                    continue
                if other['value'] > 0 and other['value'] < entry['value']:
                    potential_components.append(other)
            
            # Sort by line number proximity to the total
            potential_components.sort(key=lambda x: abs(x['line'] - entry['line']))
            
            # Try subsets of size 2-5, preferring nearby lines
            for size in range(2, min(6, len(potential_components) + 1)):
                for combo in combinations(potential_components[:10], size):  # Limit search space
                    component_sum = sum(c['value'] for c in combo)
                    if abs(component_sum - entry['value']) < 0.1:
                        relationships.append(('sum', entry['line'], [c['line'] for c in combo]))
        
        # Check for difference relationships (e.g., Gross Profit = Revenue - COGS)
        # Use label heuristics to guide the search
        if 'gross profit' in label_lower or 'operating income' in label_lower or 'net income' in label_lower:
            # Try A = B - C pattern
            for b in dollar_entries:
                for c in dollar_entries:
                    if b['line'] == entry['line'] or c['line'] == entry['line'] or b['line'] == c['line']:
                        continue
                    if abs(b['value'] - c['value'] - entry['value']) < 0.1:
                        relationships.append(('diff', entry['line'], b['line'], c['line']))
    
    # Strategy 2: Brute force - try all subsets for sum relationships
    # But limit to avoid combinatorial explosion
    for entry in dollar_entries:
        others = [e for e in dollar_entries if e['line'] != entry['line']]
        # Sort by line number proximity
        others.sort(key=lambda x: abs(x['line'] - entry['line']))
        
        for size in range(2, min(5, len(others) + 1)):
            # Limit search to nearby lines to avoid spurious matches
            for combo in combinations(others[:8], size):
                component_sum = sum(c['value'] for c in combo)
                if abs(component_sum - entry['value']) < 0.1:
                    rel = ('sum', entry['line'], sorted([c['line'] for c in combo]))
                    if rel not in relationships:
                        relationships.append(rel)
    
    return relationships


def discover_ratio_relationships(entries: List[Dict]) -> List[Tuple[int, int, int]]:
    """
    Discover ratio relationships: percentage = (numerator / denominator) * 100
    Uses flexible label matching, then exhaustive fallback for unmatched percentages.
    Returns list of (percentage_line, numerator_line, denominator_line)
    """
    relationships = []
    dollar_entries = [e for e in entries if not e['is_percentage']]
    pct_entries = [e for e in entries if e['is_percentage']]
    
    # Strategy 1: Flexible label-based heuristics
    # Find revenue/sales as common denominator
    revenue_entry = None
    for d in dollar_entries:
        label_lower = d['label'].lower()
        if 'revenue' in label_lower or 'sales' in label_lower or 'net sales' in label_lower:
            revenue_entry = d
            break
    
    for pct_entry in pct_entries:
        label_lower = pct_entry['label'].lower()
        
        # Margin relationships: "X margin" → "X" / Revenue
        if 'margin' in label_lower:
            # Extract the margin type (e.g., "gross margin" → "gross")
            margin_type = label_lower.replace('margin', '').strip()
            
            if revenue_entry:
                # Find matching numerator with precise matching
                # Sort dollar_entries to prefer exact matches (e.g., "net income" over "other income, net")
                for d in sorted(dollar_entries, key=lambda x: len(x['label'])):
                    d_label = d['label'].lower()
                    # Precise matching: "gross margin" → "gross profit", "operating margin" → "operating income"
                    # Avoid matching "operating margin" to "operating expenses"
                    if margin_type == 'gross' and 'gross profit' in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
                    elif margin_type == 'operating' and 'operating income' in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
                    elif margin_type == 'net' and 'net income' in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
                    elif margin_type == 'ebitda' and 'ebitda' in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
                    # Generic fallback for other margin types
                    elif margin_type and margin_type in d_label and 'expense' not in d_label and 'cost' not in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
        
        # Rate/ratio relationships: "X rate" or "X ratio" → X / Revenue (or other base)
        elif 'rate' in label_lower or 'ratio' in label_lower:
            # Extract the type
            rate_type = label_lower.replace('rate', '').replace('ratio', '').strip()
            
            if revenue_entry:
                for d in dollar_entries:
                    d_label = d['label'].lower()
                    if rate_type and rate_type in d_label:
                        relationships.append((pct_entry['line'], d['line'], revenue_entry['line']))
                        break
        
        # "X as % of Y" pattern
        elif '% of' in label_lower or 'as a %' in label_lower or 'as percent' in label_lower:
            # Parse: "R&D as % of revenue" → R&D / Revenue
            parts = label_lower.split()
            if 'of' in parts:
                of_idx = parts.index('of')
                numerator_words = parts[:of_idx]
                denominator_words = parts[of_idx+1:]
                
                # Find numerator
                for d in dollar_entries:
                    d_label = d['label'].lower()
                    if any(w in d_label for w in numerator_words if len(w) > 2):
                        numerator = d
                        break
                else:
                    numerator = None
                
                # Find denominator
                for d in dollar_entries:
                    d_label = d['label'].lower()
                    if any(w in d_label for w in denominator_words if len(w) > 2):
                        denominator = d
                        break
                else:
                    denominator = None
                
                if numerator and denominator:
                    relationships.append((pct_entry['line'], numerator['line'], denominator['line']))
    
    # Strategy 2: Exhaustive fallback for unmatched percentages
    matched_pct_lines = {r[0] for r in relationships}
    for pct_entry in pct_entries:
        if pct_entry['line'] in matched_pct_lines:
            continue
        
        for num_entry in dollar_entries:
            for den_entry in dollar_entries:
                if num_entry['line'] == den_entry['line']:
                    continue
                if den_entry['value'] == 0:
                    continue
                
                calculated = (num_entry['value'] / den_entry['value']) * 100
                calculated_rounded = round(calculated, 1)
                
                # Moderate tolerance to catch novel ratios without spurious matches
                if abs(calculated_rounded - pct_entry['value']) < 2.0:
                    rel = (pct_entry['line'], num_entry['line'], den_entry['line'])
                    if rel not in relationships:
                        relationships.append(rel)
    
    return relationships


def check_relationships(entries: List[Dict], additive_rels: List[Tuple], ratio_rels: List[Tuple]) -> Tuple[Set, Set]:
    """
    Check which relationships hold and which are violated.
    Returns (satisfied_set, violated_set) where each contains relationship identifiers.
    """
    entry_map = {e['line']: e for e in entries}
    satisfied = set()
    violated = set()
    
    # Check additive relationships
    for idx, rel in enumerate(additive_rels):
        if rel[0] == 'sum':
            _, result_line, component_lines = rel
            if result_line not in entry_map:
                continue
            if any(cl not in entry_map for cl in component_lines):
                continue
            
            result_val = entry_map[result_line]['value']
            component_sum = sum(entry_map[cl]['value'] for cl in component_lines)
            
            rel_id = ('additive', idx)
            if abs(result_val - component_sum) < 0.1:
                satisfied.add(rel_id)
            else:
                violated.add(rel_id)
        
        elif rel[0] == 'diff':
            _, result_line, pos_line, neg_line = rel
            if result_line not in entry_map or pos_line not in entry_map or neg_line not in entry_map:
                continue
            
            result_val = entry_map[result_line]['value']
            component_val = entry_map[pos_line]['value'] - entry_map[neg_line]['value']
            
            rel_id = ('additive', idx)
            if abs(result_val - component_val) < 0.1:
                satisfied.add(rel_id)
            else:
                violated.add(rel_id)
    
    # Check ratio relationships
    for idx, (pct_line, num_line, den_line) in enumerate(ratio_rels):
        if pct_line not in entry_map or num_line not in entry_map or den_line not in entry_map:
            continue
        
        pct_val = entry_map[pct_line]['value']
        num_val = entry_map[num_line]['value']
        den_val = entry_map[den_line]['value']
        
        if den_val == 0:
            continue
        
        calculated = (num_val / den_val) * 100
        calculated_rounded = round(calculated, 1)
        
        rel_id = ('ratio', idx)
        if abs(calculated_rounded - pct_val) < 0.05:
            satisfied.add(rel_id)
        else:
            violated.add(rel_id)
    
    return satisfied, violated


def line_participates(line: int, rel_id: Tuple, additive_rels: List[Tuple], ratio_rels: List[Tuple]) -> bool:
    """Check if a line number participates in a given relationship."""
    rel_type, idx = rel_id
    
    if rel_type == 'additive':
        rel = additive_rels[idx]
        if rel[0] == 'sum':
            _, result_line, component_lines = rel
            return line == result_line or line in component_lines
        elif rel[0] == 'diff':
            _, result_line, pos_line, neg_line = rel
            return line in (result_line, pos_line, neg_line)
    
    elif rel_type == 'ratio':
        pct_line, num_line, den_line = ratio_rels[idx]
        return line in (pct_line, num_line, den_line)
    
    return False


def find_incorrect_value(entries: List[Dict], additive_rels: List[Tuple], ratio_rels: List[Tuple]) -> Optional[Dict]:
    """
    Find the single incorrect value using scoring algorithm.
    The incorrect value appears in ALL violated relationships but NO satisfied relationships.
    
    Fallback: if primary algorithm fails, pick the value with highest
    (violated_participation - satisfied_participation) score.
    """
    satisfied, violated = check_relationships(entries, additive_rels, ratio_rels)
    
    if not violated:
        return None
    
    # Primary algorithm: find value in ALL violated but NO satisfied
    for candidate in entries:
        line = candidate['line']
        
        # Does this line appear in ANY satisfied relationship?
        in_satisfied = False
        for rel_id in satisfied:
            if line_participates(line, rel_id, additive_rels, ratio_rels):
                in_satisfied = True
                break
        
        if in_satisfied:
            continue  # This value is correct — skip it
        
        # Does this line appear in EVERY violated relationship?
        in_all_violated = True
        for rel_id in violated:
            if not line_participates(line, rel_id, additive_rels, ratio_rels):
                in_all_violated = False
                break
        
        if in_all_violated:
            return candidate
    
    # Fallback: score each entry by violated participation minus satisfied participation
    print("  Primary scoring found no unique candidate. Using fallback scoring...")
    best_candidate = None
    best_score = -float('inf')
    
    for candidate in entries:
        line = candidate['line']
        
        violated_count = sum(1 for rel_id in violated 
                           if line_participates(line, rel_id, additive_rels, ratio_rels))
        satisfied_count = sum(1 for rel_id in satisfied 
                            if line_participates(line, rel_id, additive_rels, ratio_rels))
        
        score = violated_count - satisfied_count
        if score > best_score:
            best_score = score
            best_candidate = candidate
    
    return best_candidate


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 verify_finance.py <html_file> <output_file>")
        sys.exit(1)
    
    html_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # Parse HTML
    entries = parse_html_file(html_file)
    
    if not entries:
        print("Error: No financial entries found in HTML file")
        sys.exit(1)
    
    print(f"Found {len(entries)} entries:")
    for e in entries:
        pct_marker = "%" if e['is_percentage'] else ""
        print(f"  Line {e['line']}: {e['label']} = {e['value']}{pct_marker}")
    
    # Discover relationships
    additive_rels = discover_additive_relationships(entries)
    ratio_rels = discover_ratio_relationships(entries)
    
    print(f"\nDiscovered {len(additive_rels)} additive relationships")
    for rel in additive_rels:
        if rel[0] == 'sum':
            _, result, components = rel
            print(f"  Line {result} = sum of lines {components}")
        elif rel[0] == 'diff':
            _, result, pos, neg = rel
            print(f"  Line {result} = Line {pos} - Line {neg}")
    
    print(f"\nDiscovered {len(ratio_rels)} ratio relationships")
    for pct, num, den in ratio_rels:
        print(f"  Line {pct} = Line {num} / Line {den} * 100")
    
    # Check relationships
    satisfied, violated = check_relationships(entries, additive_rels, ratio_rels)
    print(f"\nSatisfied: {len(satisfied)}, Violated: {len(violated)}")
    
    # Find incorrect value
    incorrect = find_incorrect_value(entries, additive_rels, ratio_rels)
    
    if incorrect:
        print(f"\nIncorrect value found:")
        print(f"  Line {incorrect['line']}: {incorrect['label']} = {incorrect['raw_value']}")
        
        # Write output
        with open(output_file, 'w') as f:
            # Format value: remove % sign if present, handle decimals
            value_str = incorrect['raw_value'].replace('%', '').strip()
            f.write(f"{incorrect['line']},{value_str}\n")
        
        print(f"\nOutput written to {output_file}")
    else:
        print("\nError: Could not identify incorrect value")
        sys.exit(1)


if __name__ == '__main__':
    main()
