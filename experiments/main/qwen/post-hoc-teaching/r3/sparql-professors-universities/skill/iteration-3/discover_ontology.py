#!/usr/bin/env python3
"""
Integrated ontology discovery script for SPARQL professors-universities queries.
Run this first to understand the graph structure before writing the query.

Usage: python3 discover_ontology.py [path_to_ttl]
"""

from rdflib import Graph, RDF, URIRef, Namespace, Literal
from collections import defaultdict
import re
import sys


def discover_ontology(ttl_path="/app/university_graph.ttl"):
    """Discover ontology structure and output findings."""

    print("=" * 70)
    print("ONTOLOGY DISCOVERY")
    print("=" * 70)

    g = Graph()
    g.parse(ttl_path, format="turtle")

    # 1. Discover namespace prefixes
    print("\n1. NAMESPACE PREFIXES")
    prefixes = {}
    for prefix, uri in g.namespaces():
        if prefix and uri:
            prefixes[str(prefix)] = str(uri)

    # Find the main ontology namespace (used for Person, University, etc.)
    main_ns_uri = None
    main_ns_prefix = None
    for prefix, uri in prefixes.items():
        if "university" in uri.lower() or "ontology" in uri.lower():
            main_ns_uri = uri
            main_ns_prefix = prefix
            print(f"   {prefix}: {uri}  ← MAIN ONTOLOGY")
        else:
            print(f"   {prefix}: {uri}")

    if not main_ns_uri:
        # Fallback: find namespace used for Person class
        for s, p, o in g.triples((None, RDF.type, None)):
            o_str = str(o)
            if "Person" in o_str:
                main_ns_uri = o_str.rsplit("#", 1)[0] + "#" if "#" in o_str else o_str.rsplit("/", 1)[0] + "/"
                main_ns_prefix = "ex"
                print(f"   → Inferred main namespace: {main_ns_uri}")
                break

    main_ns = Namespace(main_ns_uri) if main_ns_uri else None

    # 2. Discover all classes
    print("\n2. CLASSES (rdf:type assertions)")
    classes = defaultdict(set)  # str(class_uri) -> set of instance URIRefs
    for s, p, o in g.triples((None, RDF.type, None)):
        classes[str(o)].add(s)

    for cls_uri, instances in sorted(classes.items()):
        print(f"   {cls_uri}: {len(instances)} instances")

    # 3. Discover all predicates
    print("\n3. PREDICATES")
    predicates = defaultdict(int)
    for s, p, o in g:
        predicates[str(p)] += 1

    for pred, count in sorted(predicates.items()):
        print(f"   {pred}: {count} triples")

    # 4. Find Person instances
    print("\n4. PERSON INSTANCES AND PROPERTIES")
    person_class_str = None
    for cls_uri in classes.keys():
        if "Person" in cls_uri:
            person_class_str = cls_uri
            break

    persons = set()
    if person_class_str:
        persons = classes[person_class_str]
        print(f"   Found {len(persons)} Person instances")

        # Sample first 3 persons
        for person in sorted(persons, key=str)[:3]:
            print(f"\n   {person}:")
            for p, o in sorted(g.predicate_objects(person), key=lambda x: str(x[0])):
                pred_name = str(p).split("#")[-1] if "#" in str(p) else str(p)
                if isinstance(o, Literal):
                    print(f"      {pred_name}: \"{o}\"")
                else:
                    obj_name = str(o).split("#")[-1] if "#" in str(o) else str(o)
                    print(f"      {pred_name}: → {obj_name}")
    else:
        print("   WARNING: No Person class found!")

    # 5. Enumerate role/rank values (for professor identification)
    print("\n5. ROLE/RANK VALUES (for professor identification)")
    role_predicates = []
    for pred in predicates.keys():
        pred_name = pred.split("#")[-1].lower() if "#" in pred else pred.lower()
        if any(kw in pred_name for kw in ["role", "rank", "position", "title", "appointment"]):
            role_predicates.append(pred)

    prof_regex = re.compile(r'(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])')

    for role_pred in role_predicates:
        print(f"\n   Predicate: {role_pred}")
        literal_values = set()
        resource_values = set()

        for s, p, o in g.triples((None, URIRef(role_pred), None)):
            if isinstance(o, Literal):
                literal_values.add(str(o))
            else:
                # Resource-based rank: get its label
                for _, lp, lo in g.triples((o, None, None)):
                    if "label" in str(lp).lower():
                        resource_values.add((str(o), str(lo)))

        if literal_values:
            print(f"   String values ({len(literal_values)}):")
            for val in sorted(literal_values):
                is_prof = bool(prof_regex.search(val))
                marker = "✓ PROFESSOR" if is_prof else ""
                print(f"      '{val}' {marker}")

        if resource_values:
            print(f"   Resource values ({len(resource_values)}):")
            for uri, label in sorted(resource_values):
                is_prof = bool(prof_regex.search(label))
                marker = "✓ PROFESSOR" if is_prof else ""
                print(f"      {uri} → '{label}' {marker}")

    # 6. Find University instances
    print("\n6. UNIVERSITY INSTANCES")
    uni_class_str = None
    for cls_uri in classes.keys():
        if "University" in cls_uri or "Organization" in cls_uri:
            uni_class_str = cls_uri
            break

    universities = set()
    name_preds = []
    if uni_class_str:
        universities = classes[uni_class_str]
        print(f"   Found {len(universities)} University instances")

        # Find name predicate from first university
        for uni in list(universities)[:1]:
            for p, o in g.predicate_objects(uni):
                if isinstance(o, Literal):
                    pred_name = str(p).split("#")[-1].lower() if "#" in str(p) else str(p).lower()
                    if "name" in pred_name or "label" in pred_name:
                        name_preds.append(str(p))
                        print(f"   Name predicate: {p} → '{o}'")
    else:
        print("   WARNING: No University class found!")

    # 7. Probe affiliation paths (Person → University)
    print("\n7. AFFILIATION PATHS (Person → University)")

    direct_count = 0
    two_hop_count = 0
    inverse_count = 0
    two_hop_details = []

    if persons and universities:
        # Pattern A: Direct link (Person → University)
        for person in persons:
            for p, o in g.predicate_objects(person):
                if o in universities:
                    direct_count += 1
                    if direct_count <= 2:
                        print(f"   Direct: {str(person).split('#')[-1]} →{str(p).split('#')[-1]}→ {str(o).split('#')[-1]}")

        # Pattern B: Two-hop via intermediate (Person → ?mid → University)
        for person in persons:
            for p1, mid in g.predicate_objects(person):
                if isinstance(mid, URIRef) and mid not in universities:
                    for p2, o in g.predicate_objects(mid):
                        if o in universities:
                            two_hop_count += 1
                            if two_hop_count <= 3:
                                two_hop_details.append(
                                    f"   Two-hop: {str(person).split('#')[-1]} →{str(p1).split('#')[-1]}→ "
                                    f"{str(mid).split('#')[-1]} →{str(p2).split('#')[-1]}→ {str(o).split('#')[-1]}"
                                )

        # Pattern C: Inverse (University → Person)
        for uni in universities:
            for p, o in g.predicate_objects(uni):
                if o in persons:
                    inverse_count += 1
                    if inverse_count <= 2:
                        print(f"   Inverse: {str(uni).split('#')[-1]} →{str(p).split('#')[-1]}→ {str(o).split('#')[-1]}")

        if direct_count > 0:
            print(f"   → Pattern A (direct): {direct_count} person→university links")
        if two_hop_count > 0:
            for detail in two_hop_details:
                print(detail)
            print(f"   → Pattern B (two-hop): {two_hop_count} person→?→university links")
        if inverse_count > 0:
            print(f"   → Pattern C (inverse): {inverse_count} university→person links")
    else:
        print("   Cannot probe: missing Person or University instances")

    # 8. Summary and recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)

    if main_ns_prefix and main_ns_uri:
        print(f"\n✓ Namespace: PREFIX {main_ns_prefix}: <{main_ns_uri}>")

    if role_predicates:
        rp = role_predicates[0]
        rp_name = rp.split("#")[-1] if "#" in rp else rp
        print(f"\n✓ Professor identification predicate: {main_ns_prefix}:{rp_name}")
        if literal_values:
            print(f"  Type: String-valued (use REGEX filter)")
            print(f"  Filter: REGEX(?role, \"(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])\")")
        elif resource_values:
            print(f"  Type: Resource-based (follow to label, then REGEX)")

    print(f"\n✓ Affiliation path:")
    if direct_count > 0:
        print(f"  Direct: ?person ?pred ?university")
    elif two_hop_count > 0:
        print(f"  Two-hop: ?person ?p1 ?mid . ?mid ?p2 ?university")
    elif inverse_count > 0:
        print(f"  Inverse: ?university ?pred ?person")
    else:
        print(f"  WARNING: No affiliation path found!")

    if name_preds:
        np = name_preds[0]
        np_name = np.split("#")[-1] if "#" in np else np
        print(f"\n✓ University name predicate: {main_ns_prefix}:{np_name}")

    print(f"\n✓ Use SELECT DISTINCT for cardinality")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    ttl_path = sys.argv[1] if len(sys.argv) > 1 else "/app/university_graph.ttl"
    discover_ontology(ttl_path)
