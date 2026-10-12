#!/usr/bin/env python3
"""
Property-grounded schema discovery for SPARQL professors-universities tasks.

KEY PRINCIPLE: Discover what plays a role by following property structure,
NOT by matching type URI strings. This handles variants where types might be
ex:AcademicStaff, foaf:Person, schema:Employee, org:Organization, etc.

Usage: python3 discover_schema.py [path_to_ttl]
Default path: /app/university_graph.ttl
"""

import sys
from collections import defaultdict
from rdflib import Graph, RDF, URIRef, Literal

def main():
    ttl_path = sys.argv[1] if len(sys.argv) > 1 else "/app/university_graph.ttl"
    
    g = Graph()
    g.parse(ttl_path, format="turtle")
    
    print(f"=== Graph loaded from {ttl_path} ===")
    print(f"Total triples: {len(g)}")
    
    # 1. All predicates
    pred_counts = defaultdict(int)
    for s, p, o in g:
        pred_counts[str(p)] += 1
    
    print("\n=== Predicates ===")
    for p in sorted(pred_counts.keys()):
        print(f"  {p}  ({pred_counts[p]} triples)")
    
    # 2. All types
    type_counts = defaultdict(int)
    for s, p, o in g.triples((None, RDF.type, None)):
        type_counts[str(o)] += 1
    
    print("\n=== rdf:type classes ===")
    for t in sorted(type_counts.keys()):
        print(f"  {t}  ({type_counts[t]} instances)")
    
    # 3. Find namespace
    namespaces = set()
    for p in pred_counts:
        if '#' in p:
            namespaces.add(p.rsplit('#', 1)[0] + '#')
        elif '/' in p:
            namespaces.add(p.rsplit('/', 1)[0] + '/')
    print("\n=== Namespaces ===")
    for ns in sorted(namespaces):
        print(f"  {ns}")
    
    # 4. PROPERTY-GROUNDED: Discover role-like predicates
    # Instead of assuming type names, find predicates that carry role/rank/position/title info
    role_predicates = set()
    for s, p, o in g:
        if isinstance(o, Literal):
            p_lower = str(p).lower()
            if any(kw in p_lower for kw in ['role', 'rank', 'position', 'title', 'jobtitle']):
                role_predicates.add(p)
    
    print(f"\n=== Role/rank-like predicates (discovered by property name) ===")
    for rp in sorted(role_predicates):
        print(f"  {rp}")
    
    # 5. PROPERTY-GROUNDED: Discover person-like resources
    # Find all resources that carry a role-like predicate -> these are person-like
    person_like = set()
    for rp in role_predicates:
        for s, p, o in g.triples((None, rp, None)):
            person_like.add(s)
    
    print(f"\n=== Person-like resources (discovered by carrying role predicates) ===")
    print(f"  Count: {len(person_like)}")
    
    # Show their types and role values
    print("\n=== Person-like resources: types and role values ===")
    for person in sorted(person_like):
        types = list(g.objects(person, RDF.type))
        print(f"  {person}")
        print(f"    Types: {types}")
        for rp in role_predicates:
            for o in g.objects(person, rp):
                print(f"    {rp} -> \"{o}\"")
        # Also show name predicates
        for p, o in g.predicate_objects(person):
            if isinstance(o, Literal) and any(kw in str(p).lower() for kw in ['name', 'label']):
                print(f"    {p} -> \"{o}\"")
    
    # 6. PROPERTY-GROUNDED: Discover university-like resources
    # Trace from person-like resources outward (1-3 hops) and collect types
    # The type that appears on resources with names and reachable from persons is university-like
    reachable_from_persons = defaultdict(set)  # type -> set of resources
    for person in person_like:
        # 1-hop
        for o in g.objects(person, None):
            if isinstance(o, URIRef):
                for t in g.objects(o, RDF.type):
                    reachable_from_persons[t].add(o)
        # 2-hop
        for mid in g.objects(person, None):
            if isinstance(mid, URIRef):
                for o in g.objects(mid, None):
                    if isinstance(o, URIRef):
                        for t in g.objects(o, RDF.type):
                            reachable_from_persons[t].add(o)
        # 3-hop
        for mid1 in g.objects(person, None):
            if isinstance(mid1, URIRef):
                for mid2 in g.objects(mid1, None):
                    if isinstance(mid2, URIRef):
                        for o in g.objects(mid2, None):
                            if isinstance(o, URIRef):
                                for t in g.objects(o, RDF.type):
                                    reachable_from_persons[t].add(o)
    
    print(f"\n=== Types reachable from person-like resources (1-3 hops) ===")
    for t, resources in sorted(reachable_from_persons.items()):
        print(f"  {t}  ({len(resources)} instances)")
        # Show if these resources have name-like properties
        for r in sorted(resources)[:3]:  # Show first 3
            name_preds = [p for p, o in g.predicate_objects(r) 
                         if isinstance(o, Literal) and any(kw in str(p).lower() for kw in ['name', 'label'])]
            if name_preds:
                print(f"    {r} has name predicates: {name_preds}")
    
    # Heuristic: university-like types are those reachable from persons,
    # have name predicates, and are NOT person-like themselves
    uni_like_types = set()
    uni_like_resources = set()
    for t, resources in reachable_from_persons.items():
        # Check if this type has name predicates
        has_name = any(
            any(isinstance(o, Literal) and any(kw in str(p).lower() for kw in ['name', 'label'])
                for p, o in g.predicate_objects(r))
            for r in resources
        )
        # Check if this type is NOT person-like
        is_not_person = not any(r in person_like for r in resources)
        
        if has_name and is_not_person:
            uni_like_types.add(t)
            uni_like_resources.update(resources)
    
    print(f"\n=== University-like resources (heuristic: reachable, has name, not person-like) ===")
    print(f"  Types: {sorted(uni_like_types)}")
    print(f"  Count: {len(uni_like_resources)}")
    for u in sorted(uni_like_resources):
        for p, o in g.predicate_objects(u):
            if isinstance(o, Literal) and any(kw in str(p).lower() for kw in ['name', 'label']):
                print(f"  {u}: {p} -> \"{o}\"")
    
    # 7. Find paths from persons to universities
    print(f"\n=== Paths from person-like to university-like resources ===")
    for person in sorted(person_like):
        # 1-hop
        for o in g.objects(person, None):
            if o in uni_like_resources:
                p = [str(pred) for pred in g.predicates(person, o)]
                print(f"  {person} --{p}--> {o}")
        # 2-hop
        for mid in g.objects(person, None):
            if isinstance(mid, URIRef) and mid not in uni_like_resources:
                for o in g.objects(mid, None):
                    if o in uni_like_resources:
                        p1 = [str(pred) for pred in g.predicates(person, mid)]
                        p2 = [str(pred) for pred in g.predicates(mid, o)]
                        print(f"  {person} --{p1}--> {mid} --{p2}--> {o}")
        # 3-hop
        for mid1 in g.objects(person, None):
            if isinstance(mid1, URIRef) and mid1 not in uni_like_resources:
                for mid2 in g.objects(mid1, None):
                    if isinstance(mid2, URIRef) and mid2 not in uni_like_resources:
                        for o in g.objects(mid2, None):
                            if o in uni_like_resources:
                                p1 = [str(pred) for pred in g.predicates(person, mid1)]
                                p2 = [str(pred) for pred in g.predicates(mid1, mid2)]
                                p3 = [str(pred) for pred in g.predicates(mid2, o)]
                                print(f"  {person} --{p1}--> {mid1} --{p2}--> {mid2} --{p3}--> {o}")
    
    # Namespace prefix - read actual prefix declarations from the Turtle file
    print(f"\n{'='*70}")
    print("QUICK SUMMARY - Key findings for SPARQL query construction")
    print('='*70)
    
    # Read prefix declarations from the Turtle file
    prefixes = {}
    with open(ttl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('@prefix') or line.startswith('PREFIX'):
                # Parse: @prefix uni: <http://university.org/ontology#> .
                parts = line.split()
                if len(parts) >= 3:
                    pfx = parts[1].rstrip(':')
                    uri = parts[2].strip('<>').rstrip()
                    prefixes[pfx] = uri
    
    # Find the main ontology namespace (non-standard, non-rdf)
    main_ns = None
    main_prefix = None
    for pfx, uri in prefixes.items():
        if 'w3.org' not in uri and uri not in ['http://www.w3.org/2001/XMLSchema#']:
            main_ns = uri
            main_prefix = pfx
            break
    
    if main_ns and main_prefix:
        print(f"\n1. Namespace prefix: {main_prefix}: <{main_ns}>")
        print(f"   Use in SPARQL: PREFIX {main_prefix}: <{main_ns}>")
    elif namespaces:
        ns_list = [ns for ns in sorted(namespaces) if 'w3.org' not in ns]
        if ns_list:
            main_ns = ns_list[0]
            print(f"\n1. Namespace: <{main_ns}>")
            print(f"   (No prefix declaration found; use full URIs or define a prefix)")
    
    prefix = main_prefix or 'ns'  # fallback
    
    # Role predicate
    if role_predicates:
        rp = sorted(role_predicates)[0]
        # Extract local name
        local_name = rp.split('#')[-1] if '#' in rp else rp.split('/')[-1]
        print(f"\n2. Role predicate: {rp}")
        print(f"   Use in SPARQL: ?person {prefix}:{local_name} ?role")
    
    # Name predicate (find most common name predicate on person-like resources)
    name_pred_counts = defaultdict(int)
    for person in person_like:
        for p, o in g.predicate_objects(person):
            if isinstance(o, Literal) and any(kw in str(p).lower() for kw in ['name', 'label']):
                name_pred_counts[p] += 1
    
    if name_pred_counts:
        name_pred = max(name_pred_counts, key=name_pred_counts.get)
        local_name = name_pred.split('#')[-1] if '#' in name_pred else name_pred.split('/')[-1]
        print(f"\n3. Name predicate: {name_pred}")
        print(f"   Use in SPARQL: ?person {prefix}:{local_name} ?professorName")
        print(f"   Also for universities: ?university {prefix}:{local_name} ?universityName")
    
    # Affiliation path (find most common pattern)
    path_patterns = defaultdict(int)
    for person in person_like:
        # 2-hop via department
        for mid in g.objects(person, None):
            if isinstance(mid, URIRef) and mid not in uni_like_resources:
                for o in g.objects(mid, None):
                    if o in uni_like_resources:
                        p1 = [str(pred).split('#')[-1] if '#' in str(pred) else str(pred).split('/')[-1] 
                              for pred in g.predicates(person, mid)]
                        p2 = [str(pred).split('#')[-1] if '#' in str(pred) else str(pred).split('/')[-1] 
                              for pred in g.predicates(mid, o)]
                        if p1 and p2:
                            pattern = f"?person {prefix}:{p1[0]} ?dept . ?dept {prefix}:{p2[0]} ?university"
                            path_patterns[pattern] += 1
        # 1-hop direct
        for o in g.objects(person, None):
            if o in uni_like_resources:
                p = [str(pred).split('#')[-1] if '#' in str(pred) else str(pred).split('/')[-1] 
                     for pred in g.predicates(person, o)]
                if p:
                    pattern = f"?person {prefix}:{p[0]} ?university"
                    path_patterns[pattern] += 1
    
    if path_patterns:
        most_common_path = max(path_patterns, key=path_patterns.get)
        print(f"\n4. Most common affiliation path:")
        print(f"   {most_common_path}")
        print(f"   (Used {path_patterns[most_common_path]} times)")
    
    print(f"\n{'='*70}")

if __name__ == "__main__":
    main()
