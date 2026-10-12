#!/usr/bin/env python3
"""
Validate a SPARQL query against a Turtle knowledge graph.

This script runs a SPARQL query and reports results, checking:
- Query syntax validity
- Result count
- Result contents (professor names and university names)

Usage: python3 validate_query.py <ttl_file> <sparql_file>
"""

import sys
from pathlib import Path


def validate(ttl_file: str, sparql_file: str):
    """Validate a SPARQL query against a Turtle graph using rdflib."""
    try:
        from rdflib import Graph
    except ImportError:
        print("ERROR: rdflib not available. Cannot validate.")
        return False
    
    # Load graph
    g = Graph()
    g.parse(ttl_file, format='turtle')
    print(f"Loaded graph: {len(g)} triples")
    
    # Load query
    with open(sparql_file, 'r') as f:
        query_text = f.read()
    print(f"Query file: {sparql_file}")
    print(f"Query length: {len(query_text)} chars")
    print()
    
    # Execute query
    try:
        results = g.query(query_text)
    except Exception as e:
        print(f"QUERY ERROR: {e}")
        return False
    
    # Report results
    rows = list(results)
    print(f"RESULTS: {len(rows)} rows")
    print()
    
    if len(rows) == 0:
        print("WARNING: Query returned 0 results!")
        print("Check that:")
        print("  - Professor filter regex is correct")
        print("  - Affiliation path matches the graph structure")
        print("  - Name predicates are correct")
        return False
    
    # Check expected variables
    if results.vars:
        var_names = [str(v) for v in results.vars]
        print(f"Variables: {var_names}")
        expected = {'professorName', 'universityName'}
        actual = set(var_names)
        if expected != actual:
            print(f"WARNING: Expected variables {expected}, got {actual}")
    print()
    
    # Print results sorted by professor name
    print("Results (sorted by professor name):")
    for row in sorted(rows, key=lambda r: str(r[0])):
        prof = str(row[0])
        uni = str(row[1]) if len(row) > 1 else "N/A"
        print(f"  {prof:40s} | {uni}")
    
    print()
    
    # Check for duplicates
    pairs = [(str(r[0]), str(r[1])) for r in rows]
    unique_pairs = set(pairs)
    if len(pairs) != len(unique_pairs):
        print(f"WARNING: {len(pairs) - len(unique_pairs)} duplicate rows found!")
        print("Consider adding SELECT DISTINCT")
    else:
        print("OK: No duplicate rows")
    
    # Check for non-professor roles leaking through
    print()
    print("Sanity checks:")
    
    # Check if any result has "Student" or "Lecturer" in name (unlikely but possible)
    for prof, uni in pairs:
        if 'student' in prof.lower() or 'lecturer' in prof.lower():
            print(f"  WARNING: Possible non-professor in results: {prof}")
    
    print(f"  Total qualifying professors: {len(unique_pairs)}")
    print()
    print("=== VALIDATION COMPLETE ===")
    return True


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ttl_file> <sparql_file>")
        sys.exit(1)
    
    ttl_file = sys.argv[1]
    sparql_file = sys.argv[2]
    
    for f in [ttl_file, sparql_file]:
        if not Path(f).exists():
            print(f"Error: File '{f}' not found")
            sys.exit(1)
    
    validate(ttl_file, sparql_file)
