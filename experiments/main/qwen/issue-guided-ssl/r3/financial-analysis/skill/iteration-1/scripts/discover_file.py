#!/usr/bin/env python3
"""
Content-based financial file discovery.

Given a directory and a target company name, scores each file by:
  1. Company name presence (case-insensitive)
  2. Financial field coverage (how many known financial labels appear)

Returns the best-matching file(s).
"""

import os
import re
from pathlib import Path
from typing import Optional

# Financial field labels to search for (case-insensitive)
FINANCIAL_FIELD_PATTERNS = [
    r'\brevenue\b', r'\btotal\s*revenue\b', r'\bnet\s*sales\b',
    r'\bgross\s*profit\b', r'\bgross\s*margin\b',
    r'\boperating\s*income\b', r'\boperating\s*profit\b', r'\bop(?:erat(?:ing)?)?\s*exp\b',
    r'\bnet\s*income\b', r'\bnet\s*earnings\b', r'\bprofit\s*after\s*tax\b',
    r'\btotal\s*assets\b', r'\btotal\s*liabilities\b',
    r'\bshareholders?\s*equity\b', r'\bstockholders?\s*equity\b',
    r'\btotal\s*equity\b', r'\bbook\s*value\b',
    r'\bcost\s*of\s*revenue\b', r'\bcost\s*of\s*goods\s*sold\b', r'\bCOGS\b',
    r'\bretained\s*earnings\b',
    r'\bfiscal\s*year\b', r'\bfy\d{2,4}\b',
]

# Patterns that indicate non-financial decoy content
DECOY_INDICATORS = [
    r'\bquarterly\s*data\s*only\b',
    r'\bnot\s*annual\b',
]


def score_file(filepath: str, company_name: str) -> dict:
    """Score a file for relevance to the financial analysis task."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except (IOError, OSError):
        return {'path': filepath, 'score': -1, 'reason': 'unreadable'}

    content_lower = content.lower()

    # Check company name match
    company_match = company_name.lower() in content_lower
    if not company_match:
        return {'path': filepath, 'score': -1, 'reason': 'company not found'}

    # Check for financial field coverage
    field_count = 0
    matched_fields = []
    for pattern in FINANCIAL_FIELD_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            field_count += 1
            matched_fields.append(pattern)

    # Check for decoy indicators (reduce score)
    decoy_penalty = 0
    for pattern in DECOY_INDICATORS:
        if re.search(pattern, content, re.IGNORECASE):
            decoy_penalty += 2

    # Check for numeric data (at least some numbers present)
    numbers = re.findall(r'[\d,]+\.?\d*', content)
    has_numbers = len(numbers) > 3

    score = field_count + (10 if company_match else 0) + (5 if has_numbers else 0) - decoy_penalty

    return {
        'path': filepath,
        'score': score,
        'company_match': company_match,
        'field_count': field_count,
        'matched_fields': matched_fields,
        'has_numbers': has_numbers,
        'decoy_penalty': decoy_penalty,
    }


def discover_financial_file(directory: str, company_name: str) -> Optional[str]:
    """Find the best financial data file for the given company."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    candidates = []
    for entry in directory.iterdir():
        if entry.is_file():
            result = score_file(str(entry), company_name)
            candidates.append(result)

    # Sort by score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    if not candidates or candidates[0]['score'] <= 0:
        return None

    return candidates[0]['path']


def discover_all_files(directory: str, company_name: str, min_score: int = 5) -> list:
    """Find all files that might contain relevant financial data."""
    directory = Path(directory)
    candidates = []
    for entry in directory.iterdir():
        if entry.is_file():
            result = score_file(str(entry), company_name)
            if result['score'] >= min_score:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates


if __name__ == '__main__':
    import sys
    directory = sys.argv[1] if len(sys.argv) > 1 else '/app/financials'
    company = sys.argv[2] if len(sys.argv) > 2 else 'NVIDIA Corporation'

    best = discover_financial_file(directory, company)
    print(f"Best file: {best}")

    all_files = discover_all_files(directory, company)
    for f in all_files:
        print(f"  {f['path']}: score={f['score']}, fields={f['field_count']}")
