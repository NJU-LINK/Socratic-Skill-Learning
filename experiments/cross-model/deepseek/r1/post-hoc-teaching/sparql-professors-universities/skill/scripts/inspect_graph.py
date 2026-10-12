#!/usr/bin/env python3
"""Inspect a university knowledge-graph Turtle file to plan a SPARQL solution.

Usage:
    python3 inspect_graph.py <graph.ttl> [solution.sparql]

With no query file it prints an inventory that answers the three planning
questions for the sparql-professors-universities family:
  1. How are people/universities typed and what predicates exist?
  2. What role / rankLabel values exist (professor identification semantics)?
  3. How is each person linked to universities (affiliation structure)?  This
     includes blank-node resources (appointments/reifications) and INVERSE
     edges (e.g. a department pointing back at a person via uni:hasMember).

With a query file it additionally parses+runs the query with rdflib and prints
the result rows side by side with the reachable (person -> universities) map,
so you can spot wrong chains, missing professors, or duplicate rows.

Requires: rdflib (pip install rdflib)

Caveat: the reachability map follows only OUTGOING edges from the person; a
chain that requires traversing INWARD from the person (i.e. some other node
points at the person and then onward) is not followed. The per-person
"incoming links" inventory below makes such structures visible, and the
predicate inventory lists every predicate so no structure is silently hidden.
"""
import sys
from collections import Counter

import rdflib
from rdflib.plugins.sparql import prepareQuery

ONT = "http://university.org/ontology#"


def qname(uri):
    s = str(uri)
    if isinstance(uri, rdflib.BNode):
        return f"_:{uri}"
    return s.replace(ONT, "uni:") if s.startswith(ONT) else s


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    graph_path = sys.argv[1]
    query_path = sys.argv[2] if len(sys.argv) > 2 else None

    g = rdflib.Graph()
    g.parse(graph_path, format="turtle")
    print(f"== Graph {graph_path}: {len(g)} triples ==")

    # 1) Types and predicates
    classes = Counter(str(o) for s, p, o in g if p == rdflib.RDF.type)
    print("\n-- rdf:type counts --")
    for c, n in classes.most_common():
        print(f"  {n:3d}  {qname(c)}")
    preds = Counter(str(p) for s, p, o in g)
    print("\n-- predicates (ontology-local) --")
    for p, n in sorted(preds.items()):
        if ONT in p:
            print(f"  {n:3d}  {qname(p)}")

    # 2) Role / rank label inventories (professor identification)
    role = rdflib.URIRef(ONT + "role")
    rank_label = rdflib.URIRef(ONT + "rankLabel")
    roles = Counter(str(o) for s, p, o in g if p == role)
    labels = Counter(str(o) for s, p, o in g if p == rank_label)
    if roles:
        print("\n-- distinct uni:role values --")
        for r, n in roles.most_common():
            print(f"  {n:3d}  {r!r}")
    if labels:
        print("\n-- distinct uni:rankLabel values --")
        for r, n in labels.most_common():
            print(f"  {n:3d}  {r!r}")

    # 3) Person -> university reachability (outgoing edges only; any node kind)
    persons = sorted(g.subjects(rdflib.RDF.type, rdflib.URIRef(ONT + "Person")),
                     key=lambda x: str(g.value(x, rdflib.URIRef(ONT + "hasName")) or x))
    print("\n-- reachable universities per person (outgoing paths) --")
    for p in persons:
        name = g.value(p, rdflib.URIRef(ONT + "hasName"))
        role_v = g.value(p, role)
        visited = set()
        unis = set()
        frontier = [p]
        while frontier:
            node = frontier.pop()
            if node in visited:
                continue
            visited.add(node)
            for _, _, obj in g.triples((node, None, None)):
                if isinstance(obj, rdflib.Literal):
                    continue  # literals are leaves
                if obj in visited:
                    continue
                if (obj, rdflib.RDF.type, rdflib.URIRef(ONT + "University")) in g:
                    unis.add(obj)
                frontier.append(obj)  # URIRef or BNode: both are traversable
        names = sorted(str(g.value(u, rdflib.URIRef(ONT + "hasName")) or u) for u in unis)
        # incoming links: structures that point AT the person (inverse containment,
        # e.g. uni:D1 uni:hasMember uni:p1) - invisible to the outgoing BFS
        incoming = sorted(
            f"{qname(s)} {qname(pred)}" for s, pred, o in g.triples((None, None, p))
            if not isinstance(s, rdflib.Literal)
        )
        inc = f"  INCOMING: {incoming}" if incoming else ""
        print(f"  {str(name)!r:40s} role={str(role_v)!r:45s} uni={names}{inc}")

    # 4) Optional: run the candidate query
    if query_path:
        print(f"\n== Running {query_path} ==")
        try:
            q = prepareQuery(open(query_path).read())
            rows = [tuple(str(x) for x in r) for r in g.query(q)]
            print(f"  {len(rows)} result row(s):")
            for r in sorted(rows):
                print(f"    {r}")
        except Exception as e:  # noqa: BLE001 - report any parse/execution issue
            print(f"  ERROR: {type(e).__name__}: {e}")
            sys.exit(2)


if __name__ == "__main__":
    main()