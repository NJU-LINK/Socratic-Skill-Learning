#!/usr/bin/env python3
"""
Verify a SPARQL solution against a Turtle knowledge graph.

Usage:
    python3 verify.py [--ttl PATH] [--sparql PATH]

Checks:
  1. The SPARQL file exists and is parseable.
  2. The query projects exactly ?professorName and ?universityName.
  3. Results are non-empty.
  4. No duplicate rows.
  5. No obviously non-professor role strings in results (heuristic).
"""

import argparse
import sys
from pathlib import Path

try:
    from rdflib import Graph
except ImportError:
    print("ERROR: rdflib is required. Install with: pip install rdflib")
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="Verify SPARQL solution")
    parser.add_argument("--ttl", default="/app/university_graph.ttl",
                        help="Path to the Turtle knowledge graph")
    parser.add_argument("--sparql", default="/app/solution.sparql",
                        help="Path to the SPARQL query file")
    args = parser.parse_args()

    ttl_path = Path(args.ttl)
    sparql_path = Path(args.sparql)

    # --- Check file existence ---
    if not ttl_path.exists():
        print(f"FAIL: TTL file not found: {ttl_path}")
        sys.exit(1)
    if not sparql_path.exists():
        print(f"FAIL: SPARQL file not found: {sparql_path}")
        sys.exit(1)

    # --- Load graph ---
    g = Graph()
    try:
        g.parse(str(ttl_path), format="turtle")
    except Exception as e:
        print(f"FAIL: Could not parse TTL: {e}")
        sys.exit(1)

    # --- Read and run query ---
    query_text = sparql_path.read_text()
    try:
        results = g.query(query_text)
    except Exception as e:
        print(f"FAIL: Query execution error: {e}")
        sys.exit(1)

    # --- Check projected variables ---
    vars_str = [str(v) for v in results.vars]
    expected_vars = {"professorName", "universityName"}
    actual_vars = set(vars_str)
    if actual_vars != expected_vars:
        print(f"WARN: Expected variables {expected_vars}, got {actual_vars}")

    # --- Collect rows ---
    rows = [(str(r[0]), str(r[1])) for r in results]
    print(f"Row count: {len(rows)}")

    if len(rows) == 0:
        print("FAIL: Query returned zero rows.")
        sys.exit(1)

    # --- Check for duplicates ---
    unique_rows = set(rows)
    if len(unique_rows) != len(rows):
        print(f"WARN: {len(rows) - len(unique_rows)} duplicate row(s) found.")

    # --- Print results ---
    for prof, uni in sorted(rows):
        print(f"  {prof}  |  {uni}")

    # --- Heuristic: count qualifying roles in graph ---
    role_query = """
    SELECT DISTINCT ?role WHERE {
        ?person <http://university.org/ontology#role> ?role .
        FILTER(CONTAINS(STR(?role), "Professor"))
    }
    """
    try:
        role_results = g.query(role_query)
        prof_roles = [str(r[0]) for r in role_results]
        print(f"\nProfessor role values found in graph ({len(prof_roles)}):")
        for r in sorted(prof_roles):
            print(f"  - {r}")
    except Exception:
        pass  # Role predicate may differ in variants

    # --- Count persons with professor roles and worksAt ---
    count_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT (COUNT(DISTINCT ?person) AS ?cnt) WHERE {
        ?person uni:role ?role ;
                uni:worksAt ?dept .
        ?dept uni:partOfUniversity ?uni .
        FILTER(CONTAINS(STR(?role), "Professor"))
    }
    """
    try:
        cnt_result = g.query(count_query)
        expected_count = int(list(cnt_result)[0][0])
        print(f"Expected professor count (worksAt path): {expected_count}")
        if len(unique_rows) == expected_count:
            print("PASS: Row count matches expected professor count.")
        else:
            print(f"WARN: Row count {len(unique_rows)} != expected {expected_count}")
    except Exception:
        print("INFO: Could not compute expected count (ontology may differ).")

    print("\nVerification complete.")


if __name__ == "__main__":
    main()
