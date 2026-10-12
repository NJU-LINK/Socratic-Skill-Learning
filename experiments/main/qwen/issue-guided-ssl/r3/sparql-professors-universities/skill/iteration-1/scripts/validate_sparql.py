#!/usr/bin/env python3
"""
Validate a SPARQL query against a Turtle knowledge graph.

Usage:
    python3 validate_sparql.py <ttl_file> <sparql_file>

Loads the TTL into an rdflib Graph, runs the SPARQL query, and prints:
- Number of results
- Projected variables
- All result rows (sorted by first variable)
"""

import sys
from rdflib import Graph


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ttl_file> <sparql_file>", file=sys.stderr)
        sys.exit(1)

    ttl_file = sys.argv[1]
    sparql_file = sys.argv[2]

    # Load graph
    g = Graph()
    g.parse(ttl_file, format="turtle")
    print(f"Loaded graph: {len(g)} triples from {ttl_file}")

    # Load query
    with open(sparql_file) as f:
        query_text = f.read()

    # Run query
    try:
        results = g.query(query_text)
    except Exception as e:
        print(f"Query error: {e}", file=sys.stderr)
        sys.exit(1)

    rows = list(results)
    var_names = [str(v) for v in results.vars]

    print(f"Variables: {var_names}")
    print(f"Result count: {len(rows)}")
    print()

    if rows:
        # Sort by first column for stable output
        sorted_rows = sorted(rows, key=lambda r: str(r[0]))
        # Print header
        print(" | ".join(var_names))
        print("-" * (sum(len(v) for v in var_names) + 3 * (len(var_names) - 1)))
        for row in sorted_rows:
            print(" | ".join(str(cell) for cell in row))
    else:
        print("(no results)")


if __name__ == "__main__":
    main()
