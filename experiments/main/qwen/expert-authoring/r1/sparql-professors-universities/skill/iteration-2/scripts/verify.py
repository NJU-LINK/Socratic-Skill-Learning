#!/usr/bin/env python3
"""
Verify a SPARQL solution against a Turtle knowledge graph.

Usage:
    python3 verify.py

Checks:
  1. /app/solution.sparql exists and is readable.
  2. The query projects exactly ?professorName and ?universityName.
  3. Results are non-empty.
  4. No duplicate rows.
  5. Row count matches the number of qualifying professors in the graph.
"""

import sys
from pathlib import Path
from rdflib import Graph

TTL_PATH = Path("/app/university_graph.ttl")
SPARQL_PATH = Path("/app/solution.sparql")


def main():
    ok = True

    # --- File existence ---
    if not TTL_PATH.exists():
        print(f"FAIL: TTL not found: {TTL_PATH}")
        sys.exit(1)
    if not SPARQL_PATH.exists():
        print(f"FAIL: SPARQL not found: {SPARQL_PATH}")
        sys.exit(1)

    # --- Load graph ---
    g = Graph()
    g.parse(str(TTL_PATH), format="turtle")

    # --- Execute query ---
    query_text = SPARQL_PATH.read_text()
    try:
        results = g.query(query_text)
    except Exception as e:
        print(f"FAIL: Query error: {e}")
        sys.exit(1)

    # --- Check variables ---
    vars_list = [str(v) for v in results.vars]
    expected_vars = ["professorName", "universityName"]
    if vars_list != expected_vars:
        print(f"FAIL: Expected variables {expected_vars}, got {vars_list}")
        ok = False
    else:
        print(f"PASS: Variables correct: {vars_list}")

    # --- Collect rows ---
    rows = [(str(r[0]), str(r[1])) for r in results]
    unique = set(rows)
    print(f"Row count: {len(rows)}")
    print(f"Unique rows: {len(unique)}")

    if len(rows) == 0:
        print("FAIL: Zero results")
        ok = False

    if len(unique) != len(rows):
        print(f"FAIL: {len(rows) - len(unique)} duplicate row(s)")
        ok = False
    else:
        print("PASS: No duplicates")

    # --- Print results ---
    print()
    for prof, uni in sorted(rows):
        print(f"  {prof}  |  {uni}")

    # --- Cross-check: count qualifying professors ---
    # Try to detect the role predicate and affiliation path
    ns_query = """
    SELECT DISTINCT ?p WHERE {
        ?s ?p ?o .
        FILTER(CONTAINS(LCASE(STR(?p)), "role"))
    }
    """
    role_preds = [str(r[0]) for r in g.query(ns_query)]
    if role_preds:
        role_pred = role_preds[0]
        count_q = f"""
        SELECT (COUNT(DISTINCT ?person) AS ?cnt) WHERE {{
            ?person <{role_pred}> ?role .
            FILTER(CONTAINS(STR(?role), "Professor"))
        }}
        """
        expected_count = int(list(g.query(count_q))[0][0])
        print(f"\nProfessors in graph (role contains 'Professor'): {expected_count}")
        if len(unique) == expected_count:
            print("PASS: Row count matches expected")
        else:
            print(f"WARN: Row count {len(unique)} != expected {expected_count}")
            ok = False

    # --- Check for non-professor names leaking in ---
    non_prof_roles = []
    for role_pred in role_preds:
        nq = f"""
        SELECT DISTINCT ?name WHERE {{
            ?person <{role_pred}> ?role ;
                    ?nameP ?name .
            FILTER(CONTAINS(LCASE(STR(?nameP)), "name"))
            FILTER(!CONTAINS(STR(?role), "Professor"))
        }}
        """
        non_prof_roles.extend([str(r[0]) for r in g.query(nq)])

    leaked = [name for name, _ in rows if name in non_prof_roles]
    if leaked:
        print(f"FAIL: Non-professor names in results: {leaked}")
        ok = False
    else:
        print("PASS: No non-professor names in results")

    print()
    if ok:
        print("ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
