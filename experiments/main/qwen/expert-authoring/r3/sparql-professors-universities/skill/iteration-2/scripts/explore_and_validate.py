#!/usr/bin/env python3
"""
Graph discovery and SPARQL validation for the professors-universities task.

Usage:
  python3 scripts/explore_and_validate.py                  # Full discovery
  python3 scripts/explore_and_validate.py --validate       # Discovery + validate solution.sparql

Run from any directory. rdflib is pre-installed.
"""
import sys
from collections import Counter
import rdflib
from rdflib import RDF

TTL = "/app/university_graph.ttl"
SOL = "/app/solution.sparql"


def load():
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    return g


def local_name(uri):
    """Extract the local name from a URI, ignoring the namespace."""
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]


def prefixes():
    with open(TTL) as f:
        return [l.strip() for l in f if l.strip().startswith("@prefix")]


def discover(g):
    print("=== PREFIXES ===")
    for p in prefixes():
        print(f"  {p}")

    print("\n=== PREDICATES ===")
    pc = Counter(str(p) for _, p, _ in g)
    for p, c in sorted(pc.items()):
        print(f"  {p}  ({c})")

    print("\n=== CLASSES ===")
    cc = Counter(str(o) for _, _, o in g.triples((None, RDF.type, None)))
    for c, n in sorted(cc.items()):
        print(f"  {c}  ({n})")

    # Find role/rank predicate (check local name only)
    print("\n=== ROLE/RANK VALUES ===")
    role_pred = None
    for p in pc:
        if any(k in local_name(p).lower() for k in ("role", "rank", "position", "title")):
            role_pred = rdflib.URIRef(p)
            print(f"  Predicate: {p}")
            break
    if role_pred:
        for v, c in sorted(Counter(str(o) for _, _, o in g.triples((None, role_pred, None))).items()):
            tag = " <-- PROFESSOR" if "professor" in v.lower() else ""
            print(f"    '{v}' ({c}){tag}")
    else:
        print("  WARNING: no role/rank predicate found")

    # Find University class by local name
    print(f"\n=== AFFILIATION PATH ===")
    uni_type = None
    for _, _, o in g.triples((None, RDF.type, None)):
        if local_name(o).lower() == 'university':
            uni_type = o
            break
    unis = set(s for s, _, _ in g.triples((None, RDF.type, uni_type))) if uni_type else set()

    if uni_type:
        print(f"  University class: {uni_type} ({len(unis)} instances)")
    else:
        print("  No University class found")

    # Trace a sample professor's outgoing edges
    if role_pred:
        for person, _, rv in g.triples((None, role_pred, None)):
            if "professor" in str(rv).lower():
                print(f"  Sample professor: {person}")
                for _, p, o in g.triples((person, None, None)):
                    if p == RDF.type or "name" in local_name(p).lower() or p == role_pred:
                        continue
                    hit = " -> University!" if o in unis else ""
                    print(f"    {p} -> {o}{hit}")
                    for _, p2, o2 in g.triples((o, None, None)):
                        if p2 == RDF.type:
                            continue
                        hit2 = " -> University!" if o2 in unis else ""
                        print(f"      {p2} -> {o2}{hit2}")
                break

    print(f"\n=== NAME PREDICATE ===")
    for p in pc:
        if "name" in local_name(p).lower():
            print(f"  {p}")

    print("\n=== DONE ===")
    return role_pred


def validate(g):
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    try:
        with open(SOL) as f:
            q = f.read()
    except FileNotFoundError:
        print(f"  ERROR: {SOL} not found")
        return False

    print(f"\n  Query ({len(q)} chars):")
    for i, line in enumerate(q.strip().split("\n"), 1):
        print(f"    {i}: {line}")

    try:
        results = g.query(q)
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    var_names = set(str(v) for v in results.vars)
    expected_vars = {"professorName", "universityName"}
    print(f"\n  Rows: {len(results)}, Variables: {var_names}")

    seen, dups = set(), 0
    for row in results:
        key = (str(row[0]), str(row[1]))
        if key in seen:
            dups += 1
            print(f"    {row[0]}  ->  {row[1]}  [DUP]")
        else:
            seen.add(key)
            print(f"    {row[0]}  ->  {row[1]}")

    # Cross-check professors using local name comparisons
    role_pred = None
    missing, extra = set(), set()
    for p in set(str(p) for _, p, _ in g):
        if any(k in local_name(p).lower() for k in ("role", "rank")):
            role_pred = rdflib.URIRef(p)
            break

    if role_pred:
        prof_names = set()
        for s, _, v in g.triples((None, role_pred, None)):
            if "professor" in str(v).lower():
                for s2, _, _ in g.triples((None, role_pred, v)):
                    for _, p2, n in g.triples((s2, None, None)):
                        if "name" in local_name(p2).lower():
                            prof_names.add(str(n))
        result_names = set(str(row[0]) for row in results)
        missing = prof_names - result_names
        extra = result_names - prof_names

    ok = (var_names == expected_vars) and (dups == 0) and not missing and not extra
    print(f"\n  Vars OK: {var_names == expected_vars}")
    print(f"  Dups: {dups}")
    if missing:
        print(f"  MISSING: {missing}")
    if extra:
        print(f"  EXTRA: {extra}")
    if not missing and not extra:
        print(f"  All professors matched. PASS.")
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    g = load()
    discover(g)
    if "--validate" in sys.argv:
        ok = validate(g)
        sys.exit(0 if ok else 1)
