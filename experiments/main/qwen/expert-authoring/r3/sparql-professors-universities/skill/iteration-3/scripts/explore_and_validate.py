#!/usr/bin/env python3
"""
Full discovery + optional validation for professors-universities SPARQL task.

Usage:
  python3 scripts/explore_and_validate.py                  # Discovery only
  python3 scripts/explore_and_validate.py --validate       # Discovery + validate /app/solution.sparql
"""
import sys
from collections import Counter
import rdflib
from rdflib import RDF

TTL = "/app/university_graph.ttl"
SOL = "/app/solution.sparql"


def ln(uri):
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]


def load():
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    return g


def discover(g):
    print("=== PREFIXES ===")
    with open(TTL) as f:
        for line in f:
            if line.strip().startswith("@prefix"):
                print(f"  {line.strip()}")

    print("\n=== PREDICATES ===")
    pc = Counter(str(p) for _, p, _ in g)
    for p, c in sorted(pc.items()):
        print(f"  {p}  ({c})")

    print("\n=== CLASSES ===")
    cc = Counter(str(o) for _, _, o in g.triples((None, RDF.type, None)))
    for c, n in sorted(cc.items()):
        print(f"  {c}  ({n})")

    print("\n=== ROLES ===")
    role_pred = None
    for p in pc:
        if any(k in ln(p).lower() for k in ("role", "rank", "position", "title")):
            role_pred = rdflib.URIRef(p)
            print(f"  Predicate: {p}")
            break
    if role_pred:
        for v, c in sorted(Counter(str(o) for _, _, o in g.triples((None, role_pred, None))).items()):
            tag = " <-- PROFESSOR" if "professor" in v.lower() else ""
            print(f"    '{v}' ({c}){tag}")

    uni_class = None
    for _, _, o in g.triples((None, RDF.type, None)):
        if ln(o).lower() == 'university':
            uni_class = o
            break
    unis = set(s for s, _, _ in g.triples((None, RDF.type, uni_class))) if uni_class else set()
    print(f"\n=== UNIVERSITY CLASS: {uni_class} ({len(unis)} instances) ===")

    name_pred = None
    for p in pc:
        if ln(p).lower() in ("hasname", "name"):
            name_pred = rdflib.URIRef(p)
            break
    print(f"\n=== NAME PREDICATE: {name_pred} ===")

    print(f"\n=== ALL PROFESSOR PATHS (BFS) ===")
    affiliation_pred = None
    professors, unreachable = [], []

    if role_pred:
        def is_noise(pred):
            return pred == RDF.type or pred == role_pred or (name_pred and pred == name_pred)

        for person, _, rv in g.triples((None, role_pred, None)):
            if "professor" not in str(rv).lower():
                continue
            pname = "?"
            if name_pred:
                for _, _, n in g.triples((person, name_pred, None)):
                    pname = str(n)

            reached = False
            # Depth 1: direct
            for _, ep, eo in g.triples((person, None, None)):
                if is_noise(ep): continue
                if eo in unis:
                    print(f"  {pname}: {ln(ep)} -> University (1-hop)")
                    affiliation_pred = ep
                    reached = True
                    professors.append(pname)
                    break
            if reached: continue

            # Depth 2
            for _, ep, eo in g.triples((person, None, None)):
                if is_noise(ep): continue
                for _, ep2, eo2 in g.triples((eo, None, None)):
                    if ep2 == RDF.type: continue
                    if eo2 in unis:
                        print(f"  {pname}: {ln(ep)} -> {ln(eo)} -> {ln(ep2)} -> University (2-hop)")
                        if not affiliation_pred: affiliation_pred = ep
                        reached = True
                        professors.append(pname)
                        break
                if reached: break
            if reached: continue

            # Depth 3
            for _, ep, eo in g.triples((person, None, None)):
                if is_noise(ep): continue
                for _, ep2, eo2 in g.triples((eo, None, None)):
                    if ep2 == RDF.type: continue
                    for _, ep3, eo3 in g.triples((eo2, None, None)):
                        if ep3 == RDF.type: continue
                        if eo3 in unis:
                            print(f"  {pname}: {ln(ep)} -> ... -> {ln(ep3)} -> University (3-hop)")
                            if not affiliation_pred: affiliation_pred = ep
                            reached = True
                            professors.append(pname)
                            break
                    if reached: break
                if reached: break

            if not reached:
                unreachable.append(pname)
                print(f"  {pname}: NO PATH TO UNIVERSITY")

    print(f"\n=== SUMMARY ===")
    print(f"  Found: {len(professors)}, Unreachable: {len(unreachable)}")
    if unreachable: print(f"  WARNING: {unreachable}")
    if affiliation_pred: print(f"  Affiliation pred: {affiliation_pred}")
    print("\n=== DONE ===")


def validate(g):
    print("\n" + "=" * 50)
    print("VALIDATION")
    print("=" * 50)
    try:
        with open(SOL) as f:
            q = f.read()
    except FileNotFoundError:
        print(f"  ERROR: {SOL} not found")
        return False
    try:
        results = g.query(q)
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

    vars = set(str(v) for v in results.vars)
    expected = {"professorName", "universityName"}
    print(f"  {len(results)} rows, vars={vars}")
    seen, dups = set(), 0
    for row in results:
        k = (str(row[0]), str(row[1]))
        if k in seen: dups += 1
        seen.add(k)
        print(f"    {row[0]}  ->  {row[1]}")

    role_pred = None
    missing, extra = set(), set()
    for p in set(str(p) for _, p, _ in g):
        if any(k in ln(p).lower() for k in ("role", "rank")):
            role_pred = rdflib.URIRef(p)
            break
    if role_pred:
        name_pred = None
        for p in set(str(p) for _, p, _ in g):
            if ln(p).lower() in ("hasname", "name"):
                name_pred = rdflib.URIRef(p)
                break
        if name_pred:
            prof_names = set()
            for _, _, v in g.triples((None, role_pred, None)):
                if "professor" in str(v).lower():
                    for s2, _, _ in g.triples((None, role_pred, v)):
                        for _, _, n in g.triples((s2, name_pred, None)):
                            prof_names.add(str(n))
            result_names = set(str(r[0]) for r in results)
            missing = prof_names - result_names
            extra = result_names - prof_names

    ok = (vars == expected) and (dups == 0) and not missing and not extra
    print(f"\n  vars={'OK' if vars==expected else 'FAIL'} dups={dups} missing={len(missing)} extra={len(extra)}")
    if missing: print(f"  MISSING: {missing}")
    if extra: print(f"  EXTRA: {extra}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    g = load()
    discover(g)
    if "--validate" in sys.argv:
        ok = validate(g)
        sys.exit(0 if ok else 1)
