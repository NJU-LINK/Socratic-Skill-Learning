#!/usr/bin/env python3
"""
Fingerprint check for the sparql-professors-universities anchor (v01).

Purpose — anti-overfit dispatch gate. `references/v01_solution.sparql` is the
exact query that was validated on the anchor graph. It is safe to copy ONLY
when the graph in front of you is anchor-shaped. This script tests the four
conjunctive properties that the anchor query silently relies on; each check is
mechanical (pure rdflib over the loaded graph, no judgment calls):

  [a] rank signal      rank arrives as plain string literals on uni:role, with
                       >= 1 role containing "professor" (case-insensitive), and
                       NO resource-based rank (uni:hasAcademicRank / rankLabel).
  [b] worksAt coverage every person whose role qualifies has >= 1 uni:worksAt.
  [c] one-hop shape    every worksAt object of a qualifying person is NOT itself
                       a uni:University, has exactly one uni:partOfUniversity
                       target, and that target is typed uni:University and has a
                       uni:hasName.
  [d] name literals    every qualifying person and every reachable university
                       has exactly one uni:hasName.

Exit 0 = ALL conjuncts hold  -> anchor-shaped graph: copy references/v01_solution.sparql
                               and run scripts/verify.py (still mandatory).
Exit 1 = >= 1 conjunct fails -> DO NOT copy the reference. Follow the axis
                               procedure in SKILL.md and adapt
                               templates/query_template.sparql. The failing
                               conjunct tells you which edit is required:
                                 [a] fails -> axis-1 rank-signal discovery
                                 [b] fails -> keep/activate the guarded
                                              course fallback (teaches path)
                                 [c] fails -> axis-2 affiliation work:
                                              '*' + terminal type anchor,
                                              inverse containment (^),
                                              appointment hops
                                 [d] fails -> name-predicate exclusivity +
                                              GROUP BY / MIN machinery

Usage: python3 fingerprint_v01.py [--graph PATH]
"""
import argparse
import sys

import rdflib

UNI = "http://university.org/ontology#"
RDF_TYPE = rdflib.RDF.type


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="/app/university_graph.ttl")
    args = ap.parse_args()

    try:
        g = rdflib.Graph()
        g.parse(args.graph, format="turtle")
    except Exception as e:  # pragma: no cover
        print(f"ERROR loading graph: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    ns = dict(uni=UNI)
    U = lambda s: rdflib.URIRef(UNI + s)

    Person = U("Person")
    University = U("University")
    role_p, worksAt_p, partOf_p, hasName_p = (U(p) for p in
        ("role", "worksAt", "partOfUniversity", "hasName"))

    persons = {s for s, _, _ in g.triples((None, RDF_TYPE, Person))}
    universities = {s for s, _, _ in g.triples((None, RDF_TYPE, University))}

    roles = {}
    for p in persons:
        roles[p] = [o for _, _, o in g.triples((p, role_p, None))]
    rank_triples = list(g.triples((None, U("hasAcademicRank"), None))) + \
                   list(g.triples((None, U("rankLabel"), None)))

    qualifies = lambda p: any(
        isinstance(o, rdflib.Literal) and "professor" in str(o).lower()
        for o in roles.get(p, []))

    results = []  # (label, ok, detail)

    # [a] rank signal
    a_roles = [str(o) for p in persons for o in roles[p]
               if isinstance(o, rdflib.Literal)]
    a_ok = (len(rank_triples) == 0 and
            any("professor" in r.lower() for r in a_roles) and
            all(isinstance(o, rdflib.Literal) for o in
                [o for p in persons for o in roles[p]]))
    results.append(("[a] rank signal: string roles on uni:role, no hasAcademicRank",
                    a_ok,
                    f"{sum(1 for r in a_roles if 'professor' in r.lower())} "
                    f"professor-bearing role literals, "
                    f"{len(rank_triples)} academic-rank triples"))

    # [b] worksAt coverage
    qual = [p for p in persons if qualifies(p)]
    missing_wa = [p for p in qual if len(list(g.triples((p, worksAt_p, None)))) == 0]
    results.append(("[b] worksAt coverage for every qualifying person",
                    len(missing_wa) == 0,
                    f"{len(qual)} qualifying persons, "
                    f"{len(missing_wa)} without uni:worksAt"))

    # [c] one-hop containment shape
    c_bad = []
    for p in qual:
        units = [o for _, _, o in g.triples((p, worksAt_p, None))]
        for unit in units:
            if unit in universities:
                c_bad.append(f"{p} worksAt a University directly")
                continue
            targets = [o for _, _, o in g.triples((unit, partOf_p, None))]
            if len(targets) != 1:
                c_bad.append(f"{p}'s unit {unit} has {len(targets)} partOfUniversity edges")
                continue
            tgt = targets[0]
            if tgt not in universities:
                c_bad.append(f"{p}'s unit {unit} -> {tgt} is not a uni:University")
            elif len(list(g.triples((tgt, hasName_p, None)))) == 0:
                c_bad.append(f"{p}'s university {tgt} lacks uni:hasName")
    results.append(("[c] one-hop worksAt -> partOfUniversity -> University(+hasName)",
                    len(c_bad) == 0,
                    "; ".join(c_bad) if c_bad else "all units map to exactly one "
                                                   "University-typed, named target"))

    # [d] single-valued primary name literals
    d_bad = []
    reachable = set()
    for p in qual:
        for _, _, unit in g.triples((p, worksAt_p, None)):
            for _, _, tgt in g.triples((unit, partOf_p, None)):
                reachable.add(tgt)
    for node, label in ([(p, "person") for p in qual] +
                        [(u, "university") for u in reachable]):
        n = len(list(g.triples((node, hasName_p, None))))
        if n != 1:
            d_bad.append(f"{label} {node} has {n} uni:hasName literals")
    results.append(("[d] exactly one uni:hasName per person/university in scope",
                    len(d_bad) == 0,
                    "; ".join(d_bad) if d_bad else
                    f"persons {len(qual)}/{len(qual)}, universities "
                    f"{len(reachable)}/{len(reachable)} single-valued"))

    all_ok = True
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'} | {label}\n       {detail}")
        all_ok = all_ok and ok

    if all_ok:
        print("\nFINGERPRINT MATCH: anchor-shaped graph. Safe to copy "
              "references/v01_solution.sparql, then MUST verify with "
              "scripts/verify.py (projection + expected rows + exclusions).")
        return 0

    print("\nFINGERPRINT MISMATCH: do NOT copy the reference solution.")
    print("Dispatch (which failing conjunct -> which SKILL.md procedure):")
    for label, ok, _ in results:
        if not ok:
            if label.startswith("[a]"):
                print("  [a] -> axis-1 rank-signal discovery (role vs "
                      "hasAcademicRank/rankLabel vs other predicates)")
            elif label.startswith("[b]"):
                print("  [b] -> activate/keep the guarded course fallback "
                      "(teaches -> isTaughtIn -> unit)")
            elif label.startswith("[c]"):
                print("  [c] -> axis-2 affiliation work: '*' + terminal type "
                      "anchor, inverse containment (^), appointment hops")
            elif label.startswith("[d]"):
                print("  [d] -> name-predicate exclusivity + GROUP BY/MIN "
                      "machinery in the template")
    return 1


if __name__ == "__main__":
    sys.exit(main())