"""
General bank transaction filter: extract rows belonging to a target company.
Algorithm: Anchor-and-Expand with evidence propagation.
"""
import csv
import json
import re
import sys
import os

# ─── Abbreviation dictionaries ───────────────────────────────────────────────
WORD_ABBREVS = {
    'co': 'company',
    'corp': 'corporation',
    'inc': 'incorporated',
    'ltd': 'limited',
    'llc': 'limited liability company',
    'plc': 'public limited company',
    'hldgs': 'holdings',
    'cap': 'capital',
    'svcs': 'services',
    'mgmt': 'management',
    'intl': 'international',
    'tech': 'technology',
    'sys': 'systems',
    'dev': 'development',
    'mfg': 'manufacturing',
    'natl': 'national',
    'assoc': 'associates',
    'grp': 'group',
    'svc': 'service',
    'fin': 'financial',
    'ins': 'insurance',
    'inv': 'investment',
}

LEGAL_FORM_SUFFIXES = {
    'group', 'holdings', 'hldgs', 'corp', 'corporation', 'inc',
    'incorporated', 'ltd', 'limited', 'llc', 'plc', 'co', 'company',
    'lp', 'llp', 'pc', 'na', 'trust', 'fund',
}

DISTINGUISHING_SUFFIXES = {
    'advisors', 'advisory', 'adviser', 'partners', 'associates',
    'consultants', 'consulting', 'management', 'services', 'solutions',
    'ventures', 'investments',
}

# ─── Name normalization ──────────────────────────────────────────────────────

def extract_initialisms(text):
    """
    Extract dotted initialisms like 'N.W.' (requires 2+ letter-dot sequences).
    Returns (letters, remaining_text).
    """
    # Match patterns like "N.W." or "N.W" (2+ single letters with dots)
    # Require at least 2 letter-dot sequences
    pattern = r'((?:[A-Za-z]\.){2,}[A-Za-z]?)'
    match = re.search(pattern, text)
    if not match:
        return None, text
    
    initialism = match.group(0)
    letters = initialism.replace('.', '').lower()
    remaining = text[:match.start()] + text[match.end():]
    return list(letters), remaining.strip()

def normalize_name(name):
    """
    Normalize a company name for comparison.
    Returns: (tokens, initialism_letters)
    """
    n = name.lower().strip()
    
    # Extract initialisms first
    initialism_letters, remaining = extract_initialisms(n)
    
    # Remove punctuation from remaining
    remaining = re.sub(r'[^\w\s]', ' ', remaining)
    # Normalize whitespace
    remaining = re.sub(r'\s+', ' ', remaining).strip()
    
    # Expand abbreviations token by token
    tokens = remaining.split()
    expanded = []
    for t in tokens:
        expanded.append(WORD_ABBREVS.get(t, t))
    
    return expanded, initialism_letters

def strip_legal_suffixes(tokens):
    """Remove legal entity form suffixes from token list to get core name."""
    core = list(tokens)
    while core and core[-1] in LEGAL_FORM_SUFFIXES:
        core.pop()
    return core

def initialism_matches_target(initialism_letters, target_tokens):
    """
    Check if initialism letters match target tokens positionally.
    E.g., ['n', 'w'] matches ['north', 'west'] because:
    - 'n' is prefix of 'north'
    - 'w' is prefix of 'west'
    """
    if not initialism_letters or len(initialism_letters) > len(target_tokens):
        return False
    
    for i, letter in enumerate(initialism_letters):
        if not target_tokens[i].startswith(letter):
            return False
    return True

def has_distinguishing_suffix(name_lower, target_tokens):
    """
    Check if name has a distinguishing suffix that indicates a different entity.
    """
    target_str = ' '.join(target_tokens)
    
    for suffix in DISTINGUISHING_SUFFIXES:
        # Check if suffix appears as a word in the name
        if re.search(r'\b' + suffix + r'\b', name_lower):
            # But if target itself has this suffix, it's not distinguishing
            if suffix not in target_str:
                return True
    return False

def token_containment(tokens_a, tokens_b):
    """Containment similarity with minimum overlap requirement.
    
    Uses bidirectional containment to avoid false positives from short names.
    Requires minimum overlap of 3 tokens.
    """
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    
    # Require minimum overlap of 3 tokens (prevents 2-token false positives)
    if len(intersection) < 3:
        return 0.0
    
    # Bidirectional containment: max of forward/backward
    forward = len(intersection) / len(set_a)
    backward = len(intersection) / len(set_b)
    return max(forward, backward)

def core_containment(tokens_a, tokens_b):
    """Containment on core tokens (after stripping legal suffixes).
    
    Requires bidirectional containment: candidate must cover at least 50% of target tokens,
    and target must cover at least 50% of candidate tokens.
    Also requires minimum overlap of 3 tokens to avoid false positives from short names.
    """
    core_a = strip_legal_suffixes(tokens_a)
    core_b = strip_legal_suffixes(tokens_b)
    if not core_a or not core_b:
        return 0.0
    set_a = set(core_a)
    set_b = set(core_b)
    intersection = set_a & set_b
    
    # Require minimum overlap of 3 tokens (prevents 2-token false positives)
    if len(intersection) < 3:
        return 0.0
    
    # Bidirectional containment: both directions must be >= 0.5
    forward = len(intersection) / len(set_a)
    backward = len(intersection) / len(set_b)
    
    if forward < 0.5 or backward < 0.5:
        return 0.0
    
    return min(forward, backward)

def char_similarity(a, b):
    """Character-level similarity ratio."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()

def name_matches_target(row_tokens, row_initialism, target_tokens, threshold=0.6):
    """
    Determine if a row's company name matches the target entity.
    """
    # Reconstruct approximate name for suffix checking
    row_name_approx = ' '.join(row_tokens)
    if row_initialism:
        row_name_approx = ''.join(l + '.' for l in row_initialism) + ' ' + row_name_approx
    
    # Check for distinguishing suffixes first
    if has_distinguishing_suffix(row_name_approx.lower(), target_tokens):
        return False
    
    # Check initialism match
    if row_initialism and initialism_matches_target(row_initialism, target_tokens):
        # Initialism matches, check remaining tokens
        target_core = strip_legal_suffixes(target_tokens)
        row_core = strip_legal_suffixes(row_tokens)
        
        # Check if row core tokens are subset of target core
        if set(row_core).issubset(set(target_core)):
            return True
    
    # Primary: core token containment
    score = core_containment(row_tokens, target_tokens)
    if score >= threshold:
        return True
    
    # Secondary: full token containment (stricter)
    score2 = token_containment(row_tokens, target_tokens)
    if score2 >= threshold + 0.1:
        return True
    
    # Tertiary: character-level similarity
    row_str = ' '.join(row_tokens)
    target_str = ' '.join(target_tokens)
    sim = char_similarity(row_str, target_str)
    if sim >= 0.8:
        return True
    
    return False

def edit_distance_1(a, b):
    """Check if two strings differ by exactly one character."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs == 1
    # Insertion/deletion
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(longer)):
        if shorter == longer[:i] + longer[i+1:]:
            return True
    return False

# ─── Main algorithm ──────────────────────────────────────────────────────────

def extract_target_name(instruction):
    """Extract target company name from instruction text."""
    # Pattern 1: "belong to X" (most common)
    m = re.search(r'belong to\s+(.+?)(?:\.|\s+and|\s+only|\s*$)', instruction, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip('.')
        # Clean up trailing conjunctions or modifiers
        name = re.sub(r'\s+(and|only|exclusively)\s*$', '', name, flags=re.IGNORECASE)
        return name.strip()
    
    # Pattern 2: "for X" or "for the company X"
    m = re.search(r'for\s+(?:the\s+company\s+)?(.+?)(?:\.|\s+only|\s*$)', instruction, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip('.')
        name = re.sub(r'\s+(only|exclusively)\s*$', '', name, flags=re.IGNORECASE)
        return name.strip()
    
    # Pattern 3: "company: X" or "company X"
    m = re.search(r'company:\s*(.+?)(?:\.|\s*$)', instruction, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip('.')
    
    # Pattern 4: Quoted name
    m = re.search(r'"([^"]+)"', instruction)
    if m:
        return m.group(1).strip()
    
    # Pattern 5: After "Keep only" or "Extract" or "Filter"
    m = re.search(r'(?:keep only|extract|filter)\s+(?:for\s+)?(.+?)(?:\.|\s*$)', instruction, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip('.')
        # Remove common trailing phrases
        name = re.sub(r'\s+(transactions|rows|records|only)\s*$', '', name, flags=re.IGNORECASE)
        return name.strip()
    
    return None

def solve(csv_path, output_path, instruction=None, target_name=None):
    """
    Main solver: filter bank transactions for target company.
    """
    # Read CSV
    rows = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    
    # Get target name
    if target_name is None:
        if instruction is None:
            raise ValueError("Must provide either target_name or instruction")
        target_name = extract_target_name(instruction)
    
    print(f"Target company: '{target_name}'")
    target_tokens, target_initialism = normalize_name(target_name)
    target_core = strip_legal_suffixes(target_tokens)
    print(f"Target tokens: {target_tokens}")
    print(f"Target core: {target_core}")
    
    # Phase 1: Find anchor rows (name matches target)
    # Process in date order to establish target accounts first
    anchor_candidates = []
    for i, row in enumerate(rows):
        row_tokens, row_initialism = normalize_name(row['Company Name'])
        if name_matches_target(row_tokens, row_initialism, target_tokens):
            anchor_candidates.append((i, row))
    
    print(f"\nPhase 1: Found {len(anchor_candidates)} anchor candidates by name matching")
    
    # Phase 2: Collect target accounts from anchors
    # Exclude anchors whose account is a near-miss of an already-established target account
    target_accounts = set()
    anchor_indices = set()
    for i, row in anchor_candidates:
        acct = row['Account Number']
        # Check if this account is a near-miss of an already-established target account
        is_near_miss = False
        for ta in target_accounts:
            if edit_distance_1(acct, ta):
                print(f"  EXCLUDED (near-miss of {ta}): {row['Date']} | {row['Company Name']:35s} | {acct}")
                is_near_miss = True
                break
        if not is_near_miss:
            target_accounts.add(acct)
            anchor_indices.add(i)
            print(f"  {row['Date']} | {row['Company Name']:35s} | {acct}")
    
    print(f"\nTarget accounts from anchors: {target_accounts}")
    
    # Phase 3: Evidence propagation — include all rows on target accounts
    account_indices = set()
    for i, row in enumerate(rows):
        if row['Account Number'] in target_accounts:
            account_indices.add(i)
    
    # Combine all target row indices
    # NO account typo recovery: near-miss accounts are separate entities
    all_target_indices = anchor_indices | account_indices
    
    print(f"\nTotal target rows: {len(all_target_indices)}")
    print(f"  Anchors: {len(anchor_indices)}")
    print(f"  Account propagation: {len(account_indices - anchor_indices)}")
    
    # Build output
    output = []
    for i in sorted(all_target_indices):
        row = rows[i]
        output.append({
            'Company Name': row['Company Name'],
            'Account Number': row['Account Number'],
            'Date': row['Date'],
            'Amount': row['Amount'],
            'Transaction Type': row['Transaction Type'],
            'Description': row['Description']
        })
    
    # Sort by Date ascending
    output.sort(key=lambda x: x['Date'])
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nWrote {len(output)} rows to {output_path}")
    for r in output:
        print(f"  {r['Date']} | {r['Company Name']:35s} | {r['Account Number']} | {r['Amount']}")
    
    return output

if __name__ == '__main__':
    # Default: read instruction from task.yaml or use hardcoded target
    instruction = "Keep only the transactions that belong to North West Capital."
    solve('/app/data/bank_transactions.csv', '/app/data/output.json', instruction=instruction)
