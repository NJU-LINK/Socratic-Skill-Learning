#!/usr/bin/env python3
"""
Validate SPARQL solution for sparql-professors-universities queries.

Checks:
- Projection variables match requirements
- No duplicate rows
- Results are non-empty
- Cross-checks against role census
"""

import sys
import re
from rdflib import Graph

def extract_select_vars(query):
    """Extract SELECT variable names from query."""
    # Match SELECT [DISTINCT] ?var1 ?var2 ...
    match = re.search(r'SELECT\s+(?:DISTINCT\s+)?([?\w\s]+?)(?:WHERE|\{)', query, re.IGNORECASE)
    if match:
        vars_str = match.group(1)
        # Extract ?varname patterns
        vars_found = re.findall(r'\?(\w+)', vars_str)
        return vars_found
    return []

def validate_solution(graph_path, query_path):
    g = Graph()
    g.parse(graph_path, format="turtle")
    
    with open(query_path, "r") as f:
        query = f.read()
    
    print("=" * 60)
    print("SOLUTION VALIDATION REPORT")
    print("=" * 60)
    
    # 1. Check projection
    print("\n## 1. PROJECTION CHECK")
    vars_found = extract_select_vars(query)
    print(f"Variables in SELECT: {vars_found}")
    
    expected_vars = ["professorName", "universityName"]
    if vars_found == expected_vars:
        print(f"✓ Projection matches expected: {expected_vars}")
    else:
        print(f"✗ Projection mismatch!")
        print(f"  Expected: {expected_vars}")
        print(f"  Found: {vars_found}")
    
    has_distinct = "DISTINCT" in query.upper()
    print(f"DISTINCT modifier: {'Yes' if has_distinct else 'No'}")
    
    # 2. Execute and check results
    print("\n## 2. RESULTS CHECK")
    
    try:
        results = list(g.query(query))
        print(f"Total rows returned: {len(results)}")
        
        if len(results) == 0:
            print("✗ No results returned!")
            return False
        
        # Check for duplicates
        row_tuples = [tuple(str(v) for v in row) for row in results]
        unique_rows = set(row_tuples)
        
        if len(row_tuples) != len(unique_rows):
            print(f"✗ Found {len(row_tuples) - len(unique_rows)} duplicate rows!")
            # Show duplicates
            from collections import Counter
            counts = Counter(row_tuples)
            for row, count in counts.items():
                if count > 1:
                    print(f"    Duplicate ({count}x): {row}")
        else:
            print(f"✓ No duplicate rows (all {len(row_tuples)} rows are unique)")
        
        # Display results
        print("\n## 3. QUERY RESULTS")
        print(f"{'Professor Name':<35} | {'University Name':<40}")
        print("-" * 80)
        for row in results:
            prof = str(row[0]) if row[0] else "N/A"
            uni = str(row[1]) if row[1] else "N/A"
            print(f"{prof:<35} | {uni:<40}")
        
        # 4. Cross-check role census
        print("\n## 4. ROLE CENSUS CROSS-CHECK")
        
        # Find which roles were matched
        role_check_query = """
        PREFIX uni: <http://university.org/ontology#>
        SELECT DISTINCT ?name ?role
        WHERE {
            ?person a uni:Person ;
                    uni:hasName ?name ;
                    uni:role ?role .
        }
        """
        role_map = {}
        for row in g.query(role_check_query):
            role_map[str(row.name)] = str(row.role)
        
        # Check each result against role
        prof_roles_found = set()
        for row in results:
            name = str(row[0])
            if name in role_map:
                role = role_map[name]
                prof_roles_found.add(role)
        
        print(f"Roles identified as professors ({len(prof_roles_found)}):")
        for role in sorted(prof_roles_found):
            print(f"  - \"{role}\"")
        
        # Roles NOT selected (for verification)
        all_roles = set(role_map.values())
        non_selected = all_roles - prof_roles_found
        if non_selected:
            print(f"\nRoles NOT selected (excluded from results):")
            for role in sorted(non_selected):
                print(f"  - \"{role}\"")
        
        # 5. Summary
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        
        checks = [
            ("Projection correct", vars_found == expected_vars),
            ("Has DISTINCT modifier", has_distinct),
            ("Results non-empty", len(results) > 0),
            ("No duplicates", len(row_tuples) == len(unique_rows)),
        ]
        
        all_passed = True
        for name, passed in checks:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"  {status}: {name}")
            if not passed:
                all_passed = False
        
        print("=" * 60)
        return all_passed
        
    except Exception as e:
        print(f"✗ Error executing query: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python validate_solution.py <graph.ttl> <solution.sparql>")
        sys.exit(1)
    
    success = validate_solution(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
