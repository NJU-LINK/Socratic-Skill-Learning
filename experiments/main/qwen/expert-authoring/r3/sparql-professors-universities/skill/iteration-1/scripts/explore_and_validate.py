#!/usr/bin/env python3
"""
Explore the university knowledge graph and validate a SPARQL solution.

Usage:
  python3 explore_and_validate.py                  # Explore graph only
  python3 explore_and_validate.py --validate       # Explore + validate /app/solution.sparql
"""

import sys
import rdflib
from rdflib import RDF

TTL_PATH = "/app/university_graph.ttl"
SOLUTION_PATH = "/app/solution.sparql"


def load_graph():
    g = rdflib.Graph()
    g.parse(TTL_PATH, format="turtle")
    return g


def extract_prefixes():
    """Extract @prefix declarations from the Turtle file."""
    prefixes = []
    with open(TTL_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("@prefix"):
                prefixes.append(line)
    return prefixes


def explore(g):
    print("=" * 60)
    print("GRAPH EXPLORATION")
    print("=" * 60)

    # Prefixes
    print("\n--- Prefixes ---")
    for p in extract_prefixes():
        print(f"  {p}")

    # Classes
    print("\n--- Classes (rdf:type values) ---")
    classes = sorted(set(str(o) for _, _, o in g.triples((None, RDF.type, None))))
    for c in classes:
        count = sum(1 for _, _, o in g.triples((None, RDF.type, rdflib.URIRef(c))))
        print(f"  {c}  ({count} instances)")

    # All predicates
    print("\n--- All predicates ---")
    preds = sorted(set(str(p) for _, p, _ in g))
    for p in preds:
        count = sum(1 for _, pp, _ in g if str(pp) == p)
        print(f"  {p}  ({count} triples)")

    # Role values (common pattern)
    print("\n--- Role / rank values ---")
    role_preds = [p for p in preds if "role" in p.lower() or "rank" in p.lower()]
    for rp in role_preds:
        print(f"  Predicate: {rp}")
        for _, _, o in g.triples((None, rdflib.URIRef(rp), None)):
            print(f"    -> {o}")

    # Affiliation predicates (worksAt, affiliatedWith, etc.)
    print("\n--- Affiliation-related predicates ---")
    aff_keywords = ["work", "affil", "member", "employ", "position", "teach"]
    for p in preds:
        if any(kw in p.lower() for kw in aff_keywords):
            print(f"  {p}")
            # Show a sample
            for s, _, o in list(g.triples((None, rdflib.URIRef(p), None)))[:3]:
                print(f"    {s} -> {o}")

    # Organization hierarchy predicates
    print("\n--- Organization hierarchy predicates ---")
    org_keywords = ["part", "contain", "has", "belong", "parent", "sub"]
    for p in preds:
        if any(kw in p.lower() for kw in org_keywords):
            print(f"  {p}")
            for s, _, o in list(g.triples((None, rdflib.URIRef(p), None)))[:5]:
                print(f"    {s} -> {o}")

    # Sample professor trace
    print("\n--- Sample professor trace ---")
    role_pred = None
    for p in preds:
        if p.endswith("#role") or "role" in p.lower():
            role_pred = rdflib.URIRef(p)
            break
    if role_pred:
        for s, _, o in g.triples((None, role_pred, None)):
            val = str(o).lower()
            if "professor" in val:
                print(f"  Professor: {s} (role: {o})")
                for _, p2, o2 in g.triples((s, None, None)):
                    print(f"    {p2} -> {o2}")
                break  # Just show one

    # Sample university
    print("\n--- Sample university ---")
    uni_type = rdflib.URIRef("http://university.org/ontology#University")
    for s, _, _ in list(g.triples((None, RDF.type, uni_type)))[:1]:
        print(f"  University: {s}")
        for _, p, o in g.triples((s, None, None)):
            print(f"    {p} -> {o}")


def validate(g):
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    try:
        with open(SOLUTION_PATH) as f:
            query_text = f.read()
    except FileNotFoundError:
        print(f"  ERROR: {SOLUTION_PATH} not found!")
        return False

    print(f"\n  Query loaded ({len(query_text)} chars)")
    print("  ---")
    for i, line in enumerate(query_text.strip().split("\n"), 1):
        print(f"  {i:3}: {line}")
    print("  ---")

    try:
        results = g.query(query_text)
    except Exception as e:
        print(f"  ERROR: Query failed to execute: {e}")
        return False

    print(f"\n  Query executed successfully: {len(results)} rows")

    # Check variable names
    var_names = [str(v) for v in results.vars]
    print(f"  Variables: {var_names}")
    expected_vars = {"professorName", "universityName"}
    actual_vars = set(var_names)
    if actual_vars != expected_vars:
        print(f"  WARNING: Expected variables {expected_vars}, got {actual_vars}")

    # Print all results
    print("\n  Results:")
    seen = set()
    duplicates = 0
    for row in results:
        key = (str(row[0]), str(row[1]))
        marker = ""
        if key in seen:
            duplicates += 1
            marker = "  [DUPLICATE]"
        seen.add(key)
        print(f"    {row[0]}  ->  {row[1]}{marker}")

    if duplicates > 0:
        print(f"\n  WARNING: {duplicates} duplicate rows detected!")
    else:
        print(f"\n  OK: No duplicate rows")

    # Check for non-professor roles leaking through
    role_pred = None
    preds = sorted(set(str(p) for _, p, _ in g))
    for p in preds:
        if p.endswith("#role") or "role" in p.lower():
            role_pred = rdflib.URIRef(p)
            break

    if role_pred:
        professor_names = set()
        for s, _, o in g.triples((None, role_pred, None)):
            if "professor" in str(o).lower():
                name_pred = rdflib.URIRef(str(s).rsplit("/", 1)[0] + "/ontology#hasName")
                # Try common hasName predicate
                for ns in ["http://university.org/ontology#"]:
                    hp = rdflib.URIRef(ns + "hasName")
                    for _, _, name in g.triples((s, hp, None)):
                        professor_names.add(str(name))

        result_names = set(str(row[0]) for row in results)
        missing = professor_names - result_names
        extra = result_names - professor_names
        if missing:
            print(f"  WARNING: Missing professors: {missing}")
        if extra:
            print(f"  WARNING: Extra names (non-professors?): {extra}")
        if not missing and not extra:
            print(f"  OK: All professors found, no extras")

    return True


if __name__ == "__main__":
    g = load_graph()
    explore(g)

    if "--validate" in sys.argv:
        ok = validate(g)
        sys.exit(0 if ok else 1)
    else:
        print("\n  Tip: run with --validate to also test /app/solution.sparql")
