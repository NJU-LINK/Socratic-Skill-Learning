#!/usr/bin/env python3
"""Self-verification for the sparql-professors-universities task family.

Runs a SPARQL solution file against the task's Turtle graph with rdflib and
reports the contract checks that matter:

  1. query parses and executes,
  2. projected variables (must match the instruction exactly),
  3. row count vs. distinct-row count (duplicate detection),
  4. names appearing with more than one university (cardinality leak),
  5. full row dump when small enough to eyeball.

Usage:
    python3 verify_solution.py [solution.sparql] [graph.ttl]

Defaults: /app/solution.sparql and the first *.ttl found in /app.
"""
import glob
import sys
from collections import Counter, defaultdict

import rdflib


def main() -> int:
    query_path = sys.argv[1] if len(sys.argv) > 1 else "/app/solution.sparql"
    if len(sys.argv) > 2:
        ttl_path = sys.argv[2]
    else:
        candidates = sorted(glob.glob("/app/*.ttl"))
        if not candidates:
            print("FAIL: no .ttl file found in /app (pass the path explicitly)")
            return 1
        ttl_path = candidates[0]

    print(f"graph: {ttl_path}")
    print(f"query: {query_path}")

    with open(query_path) as fh:
        query_text = fh.read()
    if "PREFIX" not in query_text.upper():
        print("WARN: query declares no PREFIX - prefixes in the .ttl do NOT "
              "carry over to the .sparql file")

    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")
    print(f"triples: {len(g)}")

    try:
        res = g.query(query_text)
    except Exception as exc:  # noqa: BLE001 - report any engine failure
        print(f"FAIL: query did not parse/execute: {exc}")
        return 1

    vars_ = [str(v) for v in res.vars]
    print(f"projected vars: {vars_}  (must match the instruction EXACTLY)")
    if len(vars_) != 2:
        print("WARN: expected exactly 2 projected variables in this family")

    rows = [tuple(str(cell) for cell in row) for row in res]
    distinct = set(rows)
    print(f"rows: {len(rows)} | distinct rows: {len(distinct)}")
    if len(rows) != len(distinct):
        dupes = [r for r, c in Counter(rows).items() if c > 1]
        print(f"FAIL: duplicate rows present: {dupes[:5]}")
        print("      -> add SELECT DISTINCT on the final projection")
        return 1

    if len(vars_) >= 2:
        by_name = defaultdict(set)
        for row in rows:
            by_name[row[0]].add(row[1])
        multi = {n: us for n, us in by_name.items() if len(us) > 1}
        if multi:
            print(f"WARN: names bound to >1 university: {multi}")
            print("      -> if the instruction forbids this, check for a raw "
                  "UNION fallback or teaches-path fan-out")

    limit = 50
    for row in sorted(rows)[:limit]:
        print("  " + " | ".join(row))
    if len(rows) > limit:
        print(f"  ... ({len(rows) - limit} more)")

    print("OK: parses, runs, no duplicate rows. Now confirm the row SET "
          "matches the qualifying population from the instruction "
          "(no lecturers/students/near-miss titles, none missing).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
