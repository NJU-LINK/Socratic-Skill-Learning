#!/usr/bin/env python3
"""Verify a professor-university SPARQL solution against a Turtle graph.

Usage:
  python3 verify.py GRAPH.ttl SOLUTION.sparql [expected_pairs.tsv]

expected_pairs.tsv: one line per expected row, two TAB-separated fields
(professorName TAB universityName), the hand-traced oracle from the
inspection procedure. When given, the script reports count equality and
set equality between the query result and the expectation, and exits
non-zero on any mismatch. Requires rdflib (python3 -c "import rdflib").
"""
import sys
import rdflib


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    graph_path, query_path = sys.argv[1], sys.argv[2]
    expected_path = sys.argv[3] if len(sys.argv) > 3 else None

    g = rdflib.Graph()
    g.parse(graph_path, format="turtle")
    rows = sorted((str(a), str(b)) for a, b in g.query(open(query_path).read()))
    print(f"query returned {len(rows)} rows")
    for a, b in rows:
        print(f"  {a}\t{b}")

    if not expected_path:
        print("(no expected-pairs file: count/pair identity not checked)")
        return 0

    expected = []
    for line in open(expected_path):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            print(f"warning: malformed expected line: {line!r}", file=sys.stderr)
            continue
        expected.append(tuple(parts))
    got = set(rows)
    exp = set(expected)
    ok_count = len(rows) == len(expected)
    ok_set = got == exp
    print(f"rows == {len(expected)} expected pairs: {ok_count}")
    print(f"pair set equality (no wrong/missing bindings): {ok_set}")
    if not (ok_count and ok_set):
        print("MISSING from result:", sorted(exp - got))
        print("UNEXPECTED in result:", sorted(got - exp))
        return 1
    print("VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())