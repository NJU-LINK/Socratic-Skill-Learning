#!/usr/bin/env python3
"""
Generic verification harness for sparql-professors-universities queries.
Runs a SPARQL query against a Turtle graph with rdflib (preinstalled in the task
container; no pip needed) and checks the family invariants.

Usage:
  python3 verify.py --graph GRAPH.ttl --query QUERY.sparql [options]

Options:
  --graph PATH            Turtle graph to load (default /app/university_graph.ttl)
  --query PATH            SPARQL query to run (default /app/solution.sparql)
  --expected 'A|B' ...    expected rows, one argument per row, 'name|university'
  --expected-file PATH    same, read from file (one 'name|university' per line,
                          '#' comments and blank lines ignored)
  --exclude-substr S      fail if any projected value contains S (repeatable;
                          e.g. --exclude-substr Lecturer --exclude-substr Student)
  --min-rows N            fail if fewer than N rows
  --max-rows N            fail if more than N rows
  --print                 print all result rows

Exit code 0 = all checks pass, 1 = any check fails, 2 = usage/load error.

Checks performed:
  - projected variables are EXACTLY {professorName, universityName}, read from
    the stable engine-result surface (Result.vars, fallback: first row .labels);
    the query algebra is deliberately NOT inspected (private internals).
  - every row has >= 2 columns (backstop for a correctly named but wrongly
    shaped projection)
  - expected rows, if given, match as MULTISETS of (name, university) string
    pairs: order ignored, but every duplicate emission is rejected with a
    "duplicate rows" diagnostic (set comparison alone would miss a query that
    emits all pairs twice)
  - no projected value contains any --exclude-substr substring
  - row count bounds
"""
import argparse
import sys
from collections import Counter

import rdflib
from rdflib.plugins.sparql import prepareQuery


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="/app/university_graph.ttl")
    ap.add_argument("--query", default="/app/solution.sparql")
    ap.add_argument("--expected", nargs="*", default=[], metavar="NAME|UNIV")
    ap.add_argument("--expected-file")
    ap.add_argument("--exclude-substr", action="append", default=[])
    ap.add_argument("--min-rows", type=int)
    ap.add_argument("--max-rows", type=int)
    ap.add_argument("--print", action="store_true", help="print all result rows")
    args = ap.parse_args()

    try:
        g = rdflib.Graph()
        g.parse(args.graph, format="turtle")
        with open(args.query) as f:
            q = f.read()
        prepared = prepareQuery(q)
        res = g.query(prepared)
        # Projection check via the stable results surface (NOT the query algebra,
        # whose internals are private and version-dependent).
        proj = None
        if hasattr(res, "vars") and res.vars is not None:
            proj = {str(v) for v in res.vars}
        if not proj:
            first = next(iter(res), None)
            if first is not None and hasattr(first, "labels"):
                labels = first.labels
                if isinstance(labels, dict):
                    proj = {str(k) for k in labels.keys()}
                else:
                    proj = {str(v) for v in labels}
        results = sorted(tuple(str(v) for v in row)
                         for row in res)
    except Exception as e:  # pragma: no cover - environment errors
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    # always print when an expected-file is given (or --print)
    if args.print or args.expected_file:
        print(f"== {len(results)} rows ==")
        for row in results:
            print("  " + " | ".join(row))

    failures = []

    required = {"professorName", "universityName"}
    if proj is None:
        failures.append("could not determine projected variables from engine results")
    elif proj != required:
        failures.append(f"projected variables {sorted(proj)} do not match "
                        f"required set {sorted(required)}")

    if len(results) == 0:
        failures.append("query returned ZERO rows (wrong rank predicate? "
                        "too-strict type guard? unguarded filter error?)")
    elif any(len(row) < 2 for row in results):
        # backstop: correct names but wrong column shape
        failures.append("query must project TWO variables "
                        "(?professorName ?universityName)")

    expected = set(args.expected)
    if args.expected_file:
        with open(args.expected_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, _, univ = line.partition("|")
                expected.add((name.strip(), univ.strip()))

    if expected:
        # MULTISET comparison: each expected/actual pair must appear the SAME
        # number of times. Set comparison alone would PASS a query that emits
        # every pair twice (e.g. a plain UNION of worksAt and teaches paths
        # whose duplicates happen to be in the expected set) - a silent
        # axis-3 cardinality violation.
        actual_multi = Counter(
            tuple(row[:2]) if len(row) >= 2 else (row[0], "")
            for row in results)
        expected_multi = Counter(expected)
        if actual_multi != expected_multi:
            missing = set(expected_multi) - set(actual_multi)
            extra = set(actual_multi) - set(expected_multi)
            dup = {r for r in expected_multi if actual_multi[r] > expected_multi[r]}
            if missing:
                failures.append(f"missing expected rows: {sorted(missing)}")
            if extra:
                failures.append(f"unexpected extra rows: {sorted(extra)}")
            if dup:
                failures.append(f"duplicate rows (pair emitted >1x): {sorted(dup)}")

    for substr in args.exclude_substr:
        leaked = sorted((r[0], r[1]) for r in results
                        if any(substr in v for v in r))
        if leaked:
            failures.append(f"rows leaked containing {substr!r}: {leaked}")

    if args.min_rows is not None and len(results) < args.min_rows:
        failures.append(f"only {len(results)} rows, expected >= {args.min_rows}")
    if args.max_rows is not None and len(results) > args.max_rows:
        failures.append(f"{len(results)} rows, expected <= {args.max_rows}")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())