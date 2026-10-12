#!/usr/bin/env python3
"""Inspect a Turtle graph for the sparql-professors-universities family.

Usage:
  python3 inspect_graph.py GRAPH.ttl

Prints the evidence needed to instantiate the three-knob skeleton:
  1. uni:role literals with person counts (Knob A input: exact target list);
  2. uni:rankLabel literals, if rank-as-resource representation is used;
  3. whether persons and universities carry uni:hasName;
  4. affiliation-relevant outgoing predicates per subject (Knob B input:
     trace these by hand to a university IRI, noting hops and direction).
Requires rdflib.
"""

import sys
from collections import Counter, defaultdict

import rdflib

NS = "http://university.org/ontology#"
AFFILIATION_PREDICATES = {
    "worksAt", "worksFor", "affiliatedWith", "memberOf", "employedBy",
    "hasAcademicRank", "teaches", "partOfUniversity", "hasDepartment", "at",
}


def local(uri):
    return uri[len(NS):] if uri.startswith(NS) else str(uri)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    g = rdflib.Graph()
    g.parse(sys.argv[1], format="turtle")

    roles = Counter()
    rank_labels = Counter()
    n_person_names = 0
    n_uni_names = 0
    out_edges = defaultdict(Counter)  # subject -> predicate -> object kind count

    for s, p, o in g:
        pl = local(p)
        sl = local(s)
        if pl == "role":
            roles[str(o)] += 1
        elif pl == "rankLabel":
            rank_labels[str(o)] += 1
        elif pl == "hasName":
            types = {local(str(t)) for t in g.objects(s, rdflib.RDF.type)}
            if "Person" in types:
                n_person_names += 1
            if "University" in types:
                n_uni_names += 1
        if pl in AFFILIATION_PREDICATES:
            kind = "resource" if isinstance(o, rdflib.URIRef) else "literal"
            out_edges[sl][f"{pl}->{kind}"] += 1

    print("== uni:role literals (Knob A) ==")
    for lit, n in sorted(roles.items()):
        print(f"  {n:3d} x  {lit}")
    if rank_labels:
        print("== uni:rankLabel literals (knob A, rank-resource variant) ==")
        for lit, n in sorted(rank_labels.items()):
            print(f"  {n:3d} x  {lit}")
    print(f"== uni:hasName present on {n_person_names} persons, {n_uni_names} universities ==")
    print("== outgoing affiliation predicates (Knob B: trace by hand) ==")
    for subj, preds in sorted(out_edges.items()):
        for pred, n in sorted(preds.items()):
            print(f"  {subj}  {pred}  x{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())