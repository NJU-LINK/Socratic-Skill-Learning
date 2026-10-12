#!/usr/bin/env python3
"""Automated Knob B: trace person->university affiliation structure.

Usage:
  python3 trace_affiliations.py GRAPH.ttl

For the sparql-professors-universities family: prints, for the CURRENT
draw,
  1. where rank info lives: uni:role/uni:rankLabel on Person nodes vs on
     uni:Appointment nodes (Knob A must be applied at the right node);
  2. per role-bearing node, the minimal path(s) to a uni:University node
     (BFS over outgoing edges, plus incoming edges into non-Person
     organization nodes only - persons are walls, so enrollment links of
     students cannot leak into professors' paths) - including nodes with
     ZERO reachable universities and nodes reaching MULTIPLE universities
     (axis-3 ambiguity risk);
  3. a coverage table of standard candidate path expressions (direct
     worksAt, worksAt->partOfUniversity+, worksAt->^hasDepartment,
     teaches->isTaughtIn->partOfUniversity+, ^appointee->atUniversity),
     i.e. how many role-bearing nodes each query template would reach;
  4. a path expression DERIVED from the discovered signatures (first hop
     fixed from the most common signature; the tail becomes
     alternation-in-repetition over every predicate observed at any later
     hop position, e.g. worksAt/(partOfUniversity|subOrganizationOf)+),
     so heterogeneous chains with unseen predicates are covered without
     hard-coding predicate names;
  5. a suggested path snippet for the query, with uncovered nodes listed
     by their own minimal signature (so noise-by-role is recognizable).

Grounded in the draw structure only: BFS discovers predicates and
directions; it never assumes the v01 shape. Requires rdflib.
"""
import sys
from collections import Counter, defaultdict, deque
import rdflib

NS = "http://university.org/ontology#"
# Candidate Knob B path expressions (SPARQL property paths) to score.
CANDIDATES = [
    ("direct worksAt", "uni:worksAt"),
    ("worksAt -> partOfUniversity+ (chain)", "uni:worksAt/uni:partOfUniversity+"),
    ("worksAt -> ^hasDepartment (inverse containment)",
     "uni:worksAt/^uni:hasDepartment"),
    ("worksAt -> ^partOfUniversity (inverse containment alt)",
     "uni:worksAt/^uni:partOfUniversity"),
    ("teaches -> isTaughtIn -> partOfUniversity+ (course fallback)",
     "uni:teaches/uni:isTaughtIn/uni:partOfUniversity+"),
    ("^appointee -> atUniversity (appointment)",
     "^uni:appointee/uni:atUniversity"),
]


def local(uri):
    return uri[len(NS):] if uri.startswith(NS) else str(uri)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    g = rdflib.Graph()
    g.parse(sys.argv[1], format="turtle")

    RDF_TYPE = rdflib.RDF.type
    universities = {s for s, p, o in g if p == RDF_TYPE
                    and local(str(o)) == "University"}
    person_nodes = {s for s, p, o in g if p == RDF_TYPE
                    and local(str(o)) == "Person"}
    role_nodes = {s for s, p, o in g if local(str(p)) in ("role", "rankLabel")}
    role_where = Counter()
    for s in role_nodes:
        types = {local(str(t)) for t in g.objects(s, RDF_TYPE)}
        if "Appointment" in types:
            role_where["Appointment"] += 1
        elif "Person" in types:
            role_where["Person"] += 1
        else:
            role_where["untyped node"] += 1
    print(f"== rank info placement (Knob A node) == roles on: {dict(role_where)}")

    adj = defaultdict(list)  # neighbor, predicate-label, forward?
    for s, p, o in g:
        if isinstance(o, rdflib.Literal) or p == RDF_TYPE:
            # literals are dead ends; rdf:type edges are schema wires that
            # would teleport BFS between all instances of a class
            continue
        adj[s].append((o, local(str(p)), True))
        adj[o].append((s, local(str(p)), False))

    def paths_to_university(start, max_depth=6):
        """BFS to any uni:University; persons are walls (never entered)."""
        found = []
        seen = {start}
        q = deque([(start, [])])
        while q and len(found) < 5:
            node, path = q.popleft()
            if node in universities:
                found.append((tuple(path), node))
                continue
            if len(path) >= max_depth:
                continue
            for nxt, pred, fwd in adj.get(node, []):
                if nxt in seen:
                    continue
                # Never route through another person (their signals are
                # unrelated); reverse hops are allowed only into
                # non-person nodes (organizations/courses/appointments).
                if nxt in person_nodes and nxt != start:
                    continue
                seen.add(nxt)
                q.append((nxt, path + [(pred, fwd)]))
        return found

    def sig(path):
        return "/".join(pred if fwd else "^" + pred for pred, fwd in path)

    targets = role_nodes | person_nodes
    per_node = {node: paths_to_university(node) for node in sorted(targets, key=str)}

    min_sigs = Counter()
    n_reachable = n_multi = n_none = 0
    multi_info = []
    for node, res in per_node.items():
        if not res:
            n_none += 1
            continue
        n_reachable += 1
        unis = {str(u) for _, u in res}
        if len(unis) > 1:
            n_multi += 1
            best_len = min(len(p) for p, _ in res)
            best_sig = next(sig(p) for p, _ in res if len(p) == best_len)
            multi_info.append((local(str(node)), len(unis), best_sig))
        best_len = min(len(p) for p, _ in res)
        for p, _ in res:
            if len(p) == best_len:
                min_sigs[sig(p)] += 1
                break

    print(f"\n== reachability (role-bearing/person nodes: {len(targets)}) ==")
    print(f"  reach a university: {n_reachable}   unreachable: {n_none}"
          f"   multi-university: {n_multi}")
    if n_none:
        no_uni = [local(str(n)) for n, r in per_node.items() if not r]
        print(f"  unreachable nodes: {no_uni}")
    for node, k, s in multi_info:
        print(f"  multi-university {node}: {k} universities via {s}"
              f" (DISTINCT will NOT fix this; decide per task semantics)")

    print("\n== minimal path signatures (frequencies) ==")
    for s, c in min_sigs.most_common():
        print(f"  {c:3d} x  {s}")

    print("\n== candidate path-expression coverage (query templates) ==")
    target_strs = {str(t) for t in targets}
    scores = []
    for label, path in CANDIDATES:
        q = (f"PREFIX uni: <{NS}> SELECT DISTINCT ?p WHERE {{ "
             f"?p {path} ?u . ?u a uni:University . }}")
        try:
            matched = {str(r[0]) for r in g.query(q)}
            hit = len(matched & target_strs)
            scores.append((label, path, hit, len(matched)))
            print(f"  {hit:3d}/{len(targets)} targets  ({len(matched):3d} nodes)  {label}")
        except Exception as e:
            print(f"  ERR  {label}: {e}")
            scores.append((label, path, -1, 0))

    # Derive a path expression from the SIGNATURES, not from the hardcoded
    # candidate list (unseen predicates -> heterogeneous chains): take the
    # most common minimal signature (ties -> longest, most informative),
    # fix its first hop, and make the tail alternation-in-repetition over
    # every predicate observed at any later hop position across ALL
    # signatures.
    if min_sigs:
        max_c = max(min_sigs.values())
        top_sigs = sorted((s for s, c in min_sigs.items() if c == max_c),
                          key=lambda s: (len(s), s), reverse=True)
        top = top_sigs[0]
        hops = top.split("/")
        tail_preds = sorted({h for s in min_sigs
                             for h in s.split("/")[1:]})
        to_uni = lambda h: ("^uni:" if h.startswith("^") else "uni:") \
            + h.lstrip("^")
        first = to_uni(hops[0])
        derived_path = (f"{first}/({'|'.join(to_uni(p) for p in tail_preds)})+"
                        if tail_preds else first)
        q = (f"PREFIX uni: <{NS}> SELECT DISTINCT ?p WHERE {{ "
             f"?p {derived_path} ?u . ?u a uni:University . }}")
        try:
            matched = {str(r[0]) for r in g.query(q)}
            hit = len(matched & target_strs)
            scores.append(("DERIVED from signatures", derived_path, hit,
                           len(matched)))
            print(f"  {hit:3d}/{len(targets)} targets  ({len(matched):3d} nodes)"
                  f"  DERIVED from signatures (top: {top}): {derived_path}")
        except Exception as e:
            print(f"  ERR  DERIVED path {derived_path}: {e}")

    if n_reachable:
        valid = [s for s in scores if s[2] >= 0]
        best = (max(valid,
                    key=lambda s: (s[2], s[0].startswith("DERIVED")))
                if valid else None)
        if best and best[2] == n_reachable:
            print(f"\n== SUGGESTED Knob B path ==\n  ?p {best[1]} ?u   "
                  f"(covers all {n_reachable} reachable targets)")
        elif best:
            q = (f"PREFIX uni: <{NS}> SELECT DISTINCT ?p WHERE {{ "
                 f"?p {best[1]} ?u . ?u a uni:University . }}")
            covered = {str(r[0]) for r in g.query(q)}
            print(f"\n== NO single expression covers all reachable targets ==")
            print(f"  best: {best[1]} ({best[2]}/{n_reachable}); uncovered:")
            for n, res in per_node.items():
                if res and str(n) not in covered:
                    best_len = min(len(p) for p, _ in res)
                    s = next(sig(p) for p, _ in res if len(p) == best_len)
                    print(f"    {local(str(n)):28s} only via {s}")
            print("  -> judge by role (uncovered nodes with student/lecturer roles"
                  " are Knob-A noise, not Knob-B gaps); build an OPTIONAL/UNION"
                  " fallback only for QUALIFYING uncovered nodes (SKILL.md axis-2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())