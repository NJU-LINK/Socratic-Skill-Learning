#!/usr/bin/env python3
"""
Financial analysis solution - reference implementation.
Demonstrates the core mechanisms for the financial-analysis skill family.
"""

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional


def normalize_key(key: str) -> str:
    """Normalize a field name for flexible matching."""
    return re.sub(r'[\s_\-]', '', key.lower())


def flexible_field_match(row: Dict, target_keywords: List[str]) -> Optional[str]:
    """Find a field that contains any of the target keywords."""
    for key in row.keys():
        normalized_key = normalize_key(key)
        for keyword in target_keywords:
            normalized_keyword = normalize_key(keyword)
            if normalized_keyword in normalized_key:
                return key
    return None


def extract_financial_value(row: Dict, field_keywords: List[str]) -> Optional[float]:
    """Extract numeric value with flexible matching and format handling."""
    field_name = flexible_field_match(row, field_keywords)
    if not field_name:
        return None
    
    value_str = row[field_name]
    cleaned = re.sub(r'[^\d.\-]', '', str(value_str))
    
    try:
        return float(cleaned)
    except ValueError:
        return None


def looks_like_csv_header(line: str) -> bool:
    """
    Detect if a line looks like a CSV header (multiple comma-separated text fields).
    Uses structural heuristic rather than language-specific keywords.
    Headers have multiple non-numeric fields; data rows are mostly numeric.
    """
    parts = line.split(',')
    if len(parts) < 2:
        return False
    # Count non-numeric fields (text fields)
    text_fields = sum(1 for p in parts if p.strip() and not p.strip().replace('.','').replace('-','').isdigit())
    return text_fields >= 2  # At least 2 non-numeric fields suggests a header


def parse_financial_data(file_path: Path) -> List[Dict]:
    """
    Layered parsing approach to handle various formats.
    Uses structural CSV header detection that works across languages.
    """
    content = file_path.read_text()
    
    # Strategy 1: Extract CSV block from decorated text
    # Uses structural heuristic to detect headers (language-agnostic)
    lines = content.split('\n')
    csv_lines = []
    in_csv_block = False
    
    for line in lines:
        # Detect CSV header by structure, not vocabulary
        if looks_like_csv_header(line):
            in_csv_block = True
            csv_lines.append(line)
        elif in_csv_block:
            # Continue collecting data rows
            if ',' in line and line.strip() and not line.startswith('=') and not line.startswith('#'):
                csv_lines.append(line)
            else:
                # End of CSV block
                if csv_lines:
                    break
    
    if csv_lines:
        reader = csv.DictReader(csv_lines)
        return list(reader)
    
    # Strategy 2: Try standard CSV
    try:
        reader = csv.DictReader(content.split('\n'))
        data = list(reader)
        if data and len(data[0]) > 1:
            return data
    except Exception:
        pass
    
    # Strategy 3: Try JSON
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'data' in data:
            return data['data']
    except Exception:
        pass
    
    return []


def discover_financial_file(directory: str, company_name: str) -> Optional[Path]:
    """
    Content-based file discovery with validation.
    Returns the first file that mentions the company AND produces parseable data.
    This prevents stopping at decoy files that mention the company but have no usable data.
    """
    dir_path = Path(directory)
    
    for file_path in dir_path.iterdir():
        if not file_path.is_file():
            continue
            
        try:
            content = file_path.read_text()
            if company_name.lower() in content.lower():
                # Validate: can we actually parse financial data from this file?
                data = parse_financial_data(file_path)
                if data:
                    return file_path
        except Exception:
            continue
    
    return None


def extract_year_value(year_str: str) -> str:
    """
    Extract numeric year from various formats.
    "FY2022" -> "2022"
    "2022" -> "2022"
    "Q1_2025" -> "2025"
    """
    # Look for 4-digit year (no word boundary requirement to handle "FY2022")
    match = re.search(r'(19|20)\d{2}', year_str)
    if match:
        return match.group(0)
    return year_str


def calculate_metric(data: List[Dict], metric_type: str) -> List[Dict]:
    """
    Calculate the requested financial metric.
    Supports: gross_margin, operating_margin, net_margin, return_on_equity, year_over_year_growth
    """
    results = []
    
    for row in data:
        # Extract year/period identifier
        year_field = flexible_field_match(row, ['year', 'period', 'date', 'quarter'])
        year_value = row.get(year_field, 'Unknown') if year_field else 'Unknown'
        
        # Calculate based on metric type
        if metric_type == 'gross_margin':
            revenue = extract_financial_value(row, ['revenue', 'sales', 'net sales'])
            gross_profit = extract_financial_value(row, ['gross profit', 'grossprofit', 'gross_income'])
            
            if revenue and gross_profit:
                margin = (gross_profit / revenue) * 100
                results.append({
                    'year': year_value,
                    'value': round(margin, 2)
                })
        
        elif metric_type == 'operating_margin':
            revenue = extract_financial_value(row, ['revenue', 'sales'])
            operating_income = extract_financial_value(row, ['operating income', 'operatingincome', 'operating_income', 'operating_profit', 'operatingprofit'])
            
            if revenue and operating_income:
                margin = (operating_income / revenue) * 100
                results.append({
                    'year': year_value,
                    'value': round(margin, 2)
                })
        
        elif metric_type == 'net_margin':
            revenue = extract_financial_value(row, ['revenue', 'sales'])
            net_income = extract_financial_value(row, ['net income', 'netincome', 'net_income', 'net_profit', 'netprofit'])
            
            if revenue and net_income:
                margin = (net_income / revenue) * 100
                results.append({
                    'year': year_value,
                    'value': round(margin, 2)
                })
        
        elif metric_type == 'return_on_equity':
            net_income = extract_financial_value(row, ['net income', 'netincome', 'net_income'])
            equity = extract_financial_value(row, ['equity', "shareholders' equity", 'stockholders_equity', 'shareholdersequity'])
            
            if net_income and equity:
                roe = (net_income / equity) * 100
                results.append({
                    'year': year_value,
                    'value': round(roe, 2)
                })
    
    # Handle YoY growth (requires sequential processing)
    if metric_type == 'year_over_year_growth':
        revenue_values = []
        for row in data:
            year_field = flexible_field_match(row, ['year', 'period'])
            year_value = row.get(year_field, 'Unknown') if year_field else 'Unknown'
            revenue = extract_financial_value(row, ['revenue', 'sales'])
            if revenue:
                revenue_values.append((year_value, revenue))
        
        for i in range(1, len(revenue_values)):
            current_year, current_revenue = revenue_values[i]
            prior_year, prior_revenue = revenue_values[i-1]
            
            if prior_revenue != 0:
                growth = ((current_revenue - prior_revenue) / abs(prior_revenue)) * 100
                results.append({
                    'year': current_year,
                    'value': round(growth, 2)
                })
    
    return results


def main():
    """
    Example usage for v01 task.
    Adapt company_name, financials_dir, output_file, and metric_type for other variants.
    """
    # Task-specific parameters
    company_name = "NVIDIA Corporation"
    financials_dir = "/app/financials"
    output_file = "/app/results.csv"
    
    # Step 1: Discover the correct file (with validation)
    print(f"Searching for {company_name} financial data...")
    data_file = discover_financial_file(financials_dir, company_name)
    
    if not data_file:
        print("ERROR: Could not find financial data file")
        return
    
    print(f"Found data in: {data_file}")
    
    # Step 2: Parse the financial data
    data = parse_financial_data(data_file)
    print(f"Extracted {len(data)} records")
    
    if not data:
        print("ERROR: No financial data extracted")
        return
    
    # Step 3: Calculate Gross Margin for all years
    gross_margins = calculate_metric(data, 'gross_margin')
    
    if not gross_margins:
        print("ERROR: Could not calculate gross margins")
        return
    
    # Step 4: Check conditional - if most recent year > 70%, output Gross Margin
    # Otherwise output Net Margin
    most_recent_margin = gross_margins[-1]['value']
    
    print(f"Most recent year Gross Margin: {most_recent_margin}%")
    
    if most_recent_margin > 70:
        print("Threshold exceeded (70%). Outputting Gross Margin for all years.")
        final_results = gross_margins
        metric_name = "gross_margin_pct"
    else:
        print("Threshold not met. Calculating Net Margin instead.")
        final_results = calculate_metric(data, 'net_margin')
        metric_name = "net_margin_pct"
    
    # Step 5: Write results with Unix line endings
    with open(output_file, 'w', newline='\n') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['fiscal_year', metric_name])
        for result in final_results:
            # Extract numeric year from "FY2022" format
            year_str = extract_year_value(result['year'])
            writer.writerow([year_str, result['value']])
    
    print(f"Results written to {output_file}")
    
    # Display results
    print("\nResults:")
    for result in final_results:
        year_str = extract_year_value(result['year'])
        print(f"  {year_str}: {result['value']}%")


if __name__ == "__main__":
    main()
