#!/usr/bin/env python3
"""
Verify a SPARQL query against a Turtle knowledge graph.

Usage:
    python verify_query.py <ttl_file> <sparql_file>

Loads the Turtle file, executes the SPARQL query, and prints results
with row count and column headers.
"""
import sys
from rdflib import Graph


def verify(ttl_path: str, sparql_path: str) -> int:
    """Run a SPARQL query against a Turtle graph and print results.
    
    Returns the number of rows.
    """
    g = Graph()
    g.parse(ttl_path, format="turtle")

    with open(sparql_path) as f:
        query_text = f.read()

    results = g.query(query_text)

    # Print column headers from the query's projection variables
    var_names = [str(v) for v in results.vars] if results.vars else []
    if var_names:
        header = "  |  ".join(f"?{v}" for v in var_names)
        print(header)
        print("-" * len(header))

    row_count = 0
    for row in results:
        values = "  |  ".join(str(val) for val in row)
        print(f"  {values}")
        row_count += 1

    print(f"\nRows returned: {row_count}")
    return row_count


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ttl_file> <sparql_file>", file=sys.stderr)
        sys.exit(1)

    ttl_path = sys.argv[1]
    sparql_path = sys.argv[2]
    verify(ttl_path, sparql_path)


if __name__ == "__main__":
    main()
