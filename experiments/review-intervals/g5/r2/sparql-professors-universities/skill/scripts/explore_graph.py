#!/usr/bin/env python3
"""
Automated graph exploration for SPARQL professor-university queries.

Performs the discovery steps of the skill methodology:
1. Discovers all predicates and class types in the graph
2. Identifies which predicates carry role/rank-like string values
3. Traces paths from Person instances to University instances
4. Classifies persons as professor-qualifying or not

Usage:
    python explore_graph.py <ttl_file>

The output is a structured report that an agent can use to construct
the correct SPARQL query without having to guess the graph structure.
"""
import sys
from collections import defaultdict
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS


def qname(g, uri):
    """Convert a URI to a readable qname or shortened form."""
    try:
        return g.namespace_manager.normalizeUri(uri)
    except Exception:
        s = str(uri)
        for sep in ['#', '/']:
            if sep in s:
                return s.rsplit(sep, 1)[-1]
        return s


def explore(ttl_path: str):
    g = Graph()
    g.parse(ttl_path, format="turtle")

    print("=" * 70)
    print("GRAPH EXPLORATION REPORT")
    print("=" * 70)

    # ── 1. Namespaces ──────────────────────────────────────────────
    print("\n### 1. NAMESPACES")
    print("-" * 70)
    for prefix, ns in sorted(g.namespaces()):
        if prefix and str(ns):
            print(f"  @{prefix:15} {ns}")

    # ── 2. Predicate inventory ─────────────────────────────────────
    print("\n### 2. PREDICATE INVENTORY")
    print("-" * 70)
    pred_stats = defaultdict(lambda: {"count": 0, "obj_types": set(), "sample_vals": set()})
    for s, p, o in g:
        ps = pred_stats[p]
        ps["count"] += 1
        if isinstance(o, Literal):
            ps["obj_types"].add("literal")
            if len(ps["sample_vals"]) < 5:
                ps["sample_vals"].add(str(o)[:80])
        elif isinstance(o, URIRef):
            ps["obj_types"].add("uri")
        elif isinstance(o, BNode):
            ps["obj_types"].add("bnode")

    for p in sorted(pred_stats, key=lambda x: pred_stats[x]["count"], reverse=True):
        ps = pred_stats[p]
        types_str = ", ".join(sorted(ps["obj_types"]))
        print(f"  {qname(g, p):40} count={ps['count']:4}  types=[{types_str}]")
        if "literal" in ps["obj_types"] and ps["sample_vals"]:
            for v in sorted(ps["sample_vals"]):
                print(f"    sample: \"{v}\"")

    # ── 3. Class inventory ─────────────────────────────────────────
    print("\n### 3. CLASS INVENTORY (rdf:type)")
    print("-" * 70)
    class_counts = defaultdict(int)
    class_members = defaultdict(list)
    for s, p, o in g:
        if p == RDF.type:
            cn = qname(g, o)
            class_counts[cn] += 1
            if len(class_members[cn]) < 3:
                # Try to get a human-readable name
                name = None
                for s2, p2, o2 in g:
                    if s2 == s and "name" in str(p2).lower():
                        name = str(o2)
                        break
                class_members[cn].append(name or qname(g, s))

    for cls in sorted(class_counts):
        print(f"  {cls:30} {class_counts[cls]:4} instances")
        for m in class_members[cls]:
            print(f"    e.g. \"{m}\"")

    # ── 4. Role/rank analysis ──────────────────────────────────────
    print("\n### 4. ROLE/RANK ANALYSIS")
    print("-" * 70)

    # Find predicates that carry string values on Person instances
    person_types = set()
    for s, p, o in g:
        if p == RDF.type and "person" in qname(g, o).lower():
            person_types.add(o)

    # For each person-typed subject, find predicates with literal values
    role_preds = defaultdict(set)  # predicate -> set of values
    for s in list(g.subjects(RDF.type, None)):
        is_person = any(o in person_types for _, _, o in g.triples((s, RDF.type, None)))
        if not is_person:
            # Also check if type qname contains "Person"
            for _, _, o in g.triples((s, RDF.type, None)):
                if "person" in qname(g, o).lower():
                    is_person = True
                    break
        if is_person:
            for p, o in g.predicate_objects(s):
                if isinstance(o, Literal) and p != RDF.type:
                    role_preds[qname(g, p)].add(str(o))

    for pred_name, vals in sorted(role_preds.items()):
        print(f"\n  Predicate on Person: {pred_name}")
        for v in sorted(vals):
            is_prof = "professor" in v.lower() or "prof" in v.lower()
            marker = "✓ PROFESSOR" if is_prof else "✗ not professor"
            print(f"    \"{v}\"  [{marker}]")

    # Also check for resource-valued rank predicates
    print("\n  Resource-valued rank predicates on Person:")
    rank_preds = defaultdict(set)
    for s in list(g.subjects(RDF.type, None)):
        is_person = False
        for _, _, o in g.triples((s, RDF.type, None)):
            if "person" in qname(g, o).lower():
                is_person = True
                break
        if is_person:
            for p, o in g.predicate_objects(s):
                if isinstance(o, URIRef) and p != RDF.type:
                    # Check if the object has a label
                    for _, p2, o2 in g.triples((o, None, None)):
                        if "label" in str(p2).lower():
                            rank_preds[f"{qname(g, p)} → {qname(g, p2)}"].add(str(o2))
    
    if rank_preds:
        for pred_chain, labels in sorted(rank_preds.items()):
            print(f"\n  {pred_chain}:")
            for l in sorted(labels):
                print(f"    \"{l}\"")
    else:
        print("    (none found)")

    # ── 5. Affiliation path analysis ───────────────────────────────
    print("\n### 5. AFFILIATION PATH: Person → University")
    print("-" * 70)

    # Find University instances
    uni_instances = set()
    for s, p, o in g:
        if p == RDF.type and "university" in qname(g, o).lower():
            uni_instances.add(s)

    print(f"  Universities found: {len(uni_instances)}")
    for u in sorted(uni_instances):
        name = None
        for _, p2, o2 in g.triples((u, None, None)):
            if "name" in str(p2).lower():
                name = str(o2)
                break
        print(f"    {qname(g, u):30} \"{name}\"")

    # Find predicates that link Person to something that eventually reaches University
    # Strategy: for each Person, find outgoing URI-valued predicates, then trace
    print("\n  Path tracing from Person instances:")
    person_instances = set()
    for s, p, o in g:
        if p == RDF.type and "person" in qname(g, o).lower():
            person_instances.add(s)

    # For each person, find predicates pointing to URI objects
    person_pred_targets = defaultdict(lambda: defaultdict(set))
    for s in person_instances:
        for p, o in g.predicate_objects(s):
            if isinstance(o, URIRef) and p != RDF.type:
                person_pred_targets[qname(g, p)][s].add(o)

    for pred_name, targets in sorted(person_pred_targets.items()):
        # Check if any target is a University directly
        direct_uni = 0
        for person, objs in targets.items():
            if objs & uni_instances:
                direct_uni += 1

        # Check if any target is a Department (or similar) that links to University
        indirect_uni = 0
        for person, objs in targets.items():
            for obj in objs:
                if obj not in uni_instances:
                    # Check if obj links to a university
                    for p2, o2 in g.predicate_objects(obj):
                        if o2 in uni_instances and "university" in qname(g, p2).lower():
                            indirect_uni += 1
                            break

        if direct_uni > 0 or indirect_uni > 0:
            print(f"\n  Predicate: {pred_name}")
            print(f"    Persons using this: {len(targets)}")
            print(f"    Direct to University: {direct_uni}")
            print(f"    Indirect (via intermediate): {indirect_uni}")
            if indirect_uni > 0:
                # Find the intermediate type
                for person, objs in list(targets.items())[:3]:
                    for obj in objs:
                        if obj not in uni_instances:
                            for _, p2, o2 in g.triples((obj, RDF.type, None)):
                                print(f"    Intermediate type: {qname(g, o2)}")
                                break
                            break

    # ── 6. Summary & Recommendation ────────────────────────────────
    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print()
    print("  Based on the exploration above:")
    print()

    # Identify the role predicate
    role_pred = None
    for pred_name, vals in role_preds.items():
        prof_count = sum(1 for v in vals if "professor" in v.lower())
        if prof_count > 0:
            role_pred = pred_name
            break

    if role_pred:
        print(f"  1. Role predicate: {role_pred}")
        prof_vals = [v for v in sorted(role_preds[role_pred]) if "professor" in v.lower()]
        non_prof_vals = [v for v in sorted(role_preds[role_pred]) if "professor" not in v.lower()]
        print(f"     Qualifying values ({len(prof_vals)}): {prof_vals}")
        print(f"     Non-qualifying values ({len(non_prof_vals)}): {non_prof_vals}")
        if all(v.startswith("Professor") or v.startswith("Assistant Professor") for v in prof_vals):
            print("     → FILTER with CONTAINS(?role, \"Professor\") is safe")
        else:
            print("     → Use REGEX or VALUES list for tighter matching")
    else:
        print("  1. No string-valued role predicate found on Person instances.")
        print("     → Check for resource-valued rank predicates above")

    print()
    print("  2. Affiliation path: see Section 5 for the actual predicates")
    print("     → Use the predicates that link Person → intermediate → University")
    print()
    print("  3. Use SELECT DISTINCT to prevent duplicates")
    print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <ttl_file>", file=sys.stderr)
        sys.exit(1)
    explore(sys.argv[1])
