#!/usr/bin/env python3
"""Local verifier for the sparql-professors-universities family.

Runs a SPARQL query file against a Turtle graph with rdflib and prints:
  1. the projected variables,
  2. the sorted result rows (+ a warning if a name lands on >1 row),
  3. diagnostics: a ROLE census (every rank-like literal value and how often
     it occurs), every person-like entity (typed Person or carrying a rank
     literal) with its rank and worksAt-like neighbors and the upstream
     partOf-style chain, and a compact list of organizations.

Usage:
  python3 check_query.py <graph.ttl> <solution.sparql> [--no-diag]

Diagnostics are heuristic and vocabulary-agnostic (local-name matching on
predicate/class names); always verify the printed facts against the raw
Turtle file before trusting them.
"""
import sys
from collections import Counter

import rdflib
from rdflib.namespace import RDF

# local-name hints: predicates that look like employment/affiliation links ...
AFFIL_HINTS = ("worksat", "worksin", "worksfor", "employedby", "affiliation",
               "affiliatedwith", "hasappointment", "appointment", "employer",
               "memberof", "workplace", "holds", "atorganization", "appointedat")
# ... and predicates that walk UP an organization tree.
PARTOF_HINTS = ("partofuniversity", "partof", "suborganizationof", "subunitof",
                "belongsto", "inside", "departmentof")
# predicates whose object is a rank/role description.
ROLE_HINTS = ("role", "rank", "ranklabel", "position", "title", "academicrank")
# predicates carrying a name literal.
NAME_HINTS = ("name", "label")


def local(pred):
    return str(pred).split("#")[-1].split("/")[-1].lower().replace("_", "").replace("-", "")


def matches(pred, hints):
    l = local(pred)
    return any(h in l for h in hints)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    graph_path, query_path = sys.argv[1], sys.argv[2]
    show_diag = "--no-diag" not in sys.argv

    g = rdflib.Graph()
    g.parse(graph_path, format="turtle")
    query = open(query_path).read()

    res = g.query(query)
    print(f"VARS: {[str(v) for v in res.vars]}")
    rows = sorted(tuple(str(x) for x in r) for r in res)
    print(f"ROWS: {len(rows)}")
    for r in rows:
        print("   " + " | ".join(r))
    counts = Counter(r[0] for r in rows)
    dupes = {n: c for n, c in counts.items() if c > 1}
    print(f"DISTINCT first-column count: {len(counts)}")
    if dupes:
        print(f"!!! names appearing on multiple rows: {dupes}")

    if not show_diag:
        return

    preds = set(g.predicates())  # deduped
    name_preds = {p for p in preds if matches(p, NAME_HINTS)}
    role_preds = {p for p in preds if matches(p, ROLE_HINTS)}
    affil_preds = {p for p in preds if matches(p, AFFIL_HINTS)}
    partof_preds = {p for p in preds if matches(p, PARTOF_HINTS)}

    typed = {}
    for s, o in g.subject_objects(RDF.type):
        typed.setdefault(s, set()).add(o)
    personish_classes = {c for ctypes in typed.values() for c in ctypes
                         if "person" in local(c) or "employee" in local(c)
                         or "faculty" in local(c) or "staff" in local(c)}

    role_values = Counter()
    for p in role_preds:
        for o in g.objects(None, p):
            role_values[str(o)] += 1

    print("\n--- ROLE/RANK VALUES SEEN (decide the include set from these) ---")
    for val, cnt in role_values.most_common():
        print(f"   x{cnt}  {val!r}")

    print("\n--- CLASSES SEEN (rdf:type) ---")
    for c, cnt in Counter(g.objects(None, RDF.type)).most_common():
        print(f"   x{cnt}  {c}")

    persons = {s for c in personish_classes for s, t in typed.items() if c in t}
    persons |= {s for p in role_preds for s in g.subjects(p, None)}
    outsiders = {s for p in (affil_preds | role_preds)
                 for s in g.subjects(p, None)} - persons
    persons |= outsiders  # people linked via worksAt even without an obvious type

    print("\n--- PERSON-LIKE ENTITIES ---")
    for person in sorted(persons, key=str):
        names = []
        for p in name_preds:
            names.extend(str(o) for o in g.objects(person, p))
        roles = []
        for p in role_preds:
            roles.extend(str(o) for o in g.objects(person, p))
        affils = sorted({str(o) for p in affil_preds for o in g.objects(person, p)})
        print(f"PERSON {person}")
        print(f"   names  : {sorted(set(names)) or '!!! no name'}")
        print(f"   roles  : {sorted(set(roles)) or '??? no rank-like literal'}")
        print(f"   affil  : {affils or '??? no worksAt-like link -> fallback?'}")
        for start in affils:
            chain, seen = [start], {start}
            frontier = [start]
            while frontier:
                node = frontier.pop(0)
                for pp in partof_preds:
                    for oo in g.objects(rdflib.URIRef(node), pp):
                        s = str(oo)
                        if s not in seen:
                            seen.add(s)
                            chain.append(s)
                            frontier.append(s)
            if len(chain) > 1:
                print(f"   chain  : {' -> '.join(chain)}")

    print("\n--- ORGANIZATIONS (name + type) ---")
    for s in sorted({s for p in name_preds for s in g.subjects(p, None)} - persons,
                    key=str):
        n = sorted({str(o) for p in name_preds for o in g.objects(s, p)})
        t = sorted(local(c) for c in typed.get(s, ()))
        print(f"   {s}   ({', '.join(t) or 'untyped'}) {n}")


if __name__ == "__main__":
    main()