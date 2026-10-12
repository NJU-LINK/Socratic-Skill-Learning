#!/usr/bin/env python3
"""
Automated graph inspection for SPARQL professors-universities queries.

This script analyzes a Turtle knowledge graph to discover:
- Namespace/prefix
- Professor identification mechanism (role strings vs academic-rank resources)
- Affiliation paths (direct, department-mediated, appointment-based)
- Name predicates

Usage: python3 inspect_graph.py <ttl_file>
"""

import sys
from pathlib import Path

def inspect_with_rdflib(ttl_file: str):
    """Use rdflib for automated graph inspection."""
    try:
        from rdflib import Graph, RDF
    except ImportError:
        return None
    
    g = Graph()
    g.parse(ttl_file, format='turtle')
    
    print("=== GRAPH INSPECTION (rdflib) ===\n")
    
    # 1. Find ontology namespace
    print("1. NAMESPACES:")
    for prefix, ns in g.namespaces():
        if prefix and 'university' in str(ns).lower():
            print(f"   {prefix}: {ns}")
    
    # 2. Find all types
    print("\n2. TYPES USED:")
    types = set()
    for s, p, o in g.triples((None, RDF.type, None)):
        types.add(str(o).split('#')[-1] if '#' in str(o) else str(o))
    for t in sorted(types):
        print(f"   - {t}")
    
    # 3. Find Person predicates
    print("\n3. PERSON PREDICATES:")
    person_preds = set()
    for s, p, o in g.triples((None, RDF.type, None)):
        if 'Person' in str(o):
            for s2, p2, o2 in g.triples((s, None, None)):
                pred_name = str(p2).split('#')[-1] if '#' in str(p2) else str(p2)
                person_preds.add(pred_name)
    for pred in sorted(person_preds):
        print(f"   - {pred}")
    
    # 4. Find University predicates
    print("\n4. UNIVERSITY PREDICATES:")
    uni_preds = set()
    for s, p, o in g.triples((None, RDF.type, None)):
        if 'University' in str(o):
            for s2, p2, o2 in g.triples((s, None, None)):
                pred_name = str(p2).split('#')[-1] if '#' in str(p2) else str(p2)
                uni_preds.add(pred_name)
    for pred in sorted(uni_preds):
        print(f"   - {pred}")
    
    # 5. Find Department predicates
    print("\n5. DEPARTMENT PREDICATES:")
    dept_preds = set()
    for s, p, o in g.triples((None, RDF.type, None)):
        if 'Department' in str(o):
            for s2, p2, o2 in g.triples((s, None, None)):
                pred_name = str(p2).split('#')[-1] if '#' in str(p2) else str(p2)
                dept_preds.add(pred_name)
    for pred in sorted(dept_preds):
        print(f"   - {pred}")
    
    # 6. Discover affiliation paths
    print("\n6. AFFILIATION PATH DISCOVERY:")
    
    # Direct Person → University
    q_direct = """
    SELECT DISTINCT ?pred WHERE {
      ?person a <http://university.org/ontology#Person> .
      ?person ?pred ?uni .
      ?uni a <http://university.org/ontology#University> .
    }
    """
    try:
        results = g.query(q_direct)
        direct_preds = [str(row[0]).split('#')[-1] for row in results]
        if direct_preds:
            print(f"   Direct Person→University: {direct_preds}")
        else:
            print(f"   Direct Person→University: None")
    except:
        print(f"   Direct Person→University: Query failed")
    
    # Two-hop forward: Person → ?pred1 → intermediate → ?pred2 → University
    q_forward = """
    SELECT DISTINCT ?pred1 ?pred2 WHERE {
      ?person a <http://university.org/ontology#Person> .
      ?person ?pred1 ?intermediate .
      ?intermediate ?pred2 ?uni .
      ?uni a <http://university.org/ontology#University> .
    }
    """
    try:
        results = g.query(q_forward)
        if len(list(results)) > 0:
            print(f"   Two-hop forward paths:")
            for row in results:
                p1 = str(row[0]).split('#')[-1]
                p2 = str(row[1]).split('#')[-1]
                print(f"      {p1} → {p2}")
        else:
            print(f"   Two-hop forward paths: None")
    except:
        print(f"   Two-hop forward paths: Query failed")
    
    # Two-hop inverse: Person → ?pred1 → intermediate ← ?pred2 ← University
    q_inverse = """
    SELECT DISTINCT ?pred1 ?pred2 WHERE {
      ?person a <http://university.org/ontology#Person> .
      ?person ?pred1 ?intermediate .
      ?uni a <http://university.org/ontology#University> .
      ?uni ?pred2 ?intermediate .
    }
    """
    try:
        results = g.query(q_inverse)
        if len(list(results)) > 0:
            print(f"   Two-hop inverse paths:")
            for row in results:
                p1 = str(row[0]).split('#')[-1]
                p2 = str(row[1]).split('#')[-1]
                print(f"      {p1} ← {p2}")
        else:
            print(f"   Two-hop inverse paths: None")
    except:
        print(f"   Two-hop inverse paths: Query failed")
    
    # 7. Find role/rank values
    print("\n7. ROLE/RANK VALUES:")
    role_preds = ['role', 'hasAcademicRank', 'rank', 'position', 'title']
    for role_pred in role_preds:
        q_roles = f"""
        SELECT DISTINCT ?val WHERE {{
          ?person a <http://university.org/ontology#Person> .
          ?person ?pred ?val .
          FILTER(STRSTARTS(STR(?pred), "http://university.org/ontology#{role_pred}"))
        }}
        LIMIT 20
        """
        try:
            results = g.query(q_roles)
            vals = [str(row[0]) for row in results]
            if vals:
                print(f"   {role_pred}:")
                for val in vals[:10]:
                    print(f"      - '{val}'")
                if len(vals) > 10:
                    print(f"      ... and {len(vals) - 10} more")
        except:
            pass
    
    # 8. Find name predicates
    print("\n8. NAME PREDICATES:")
    name_preds = set()
    for s, p, o in g.triples((None, None, None)):
        if isinstance(o, str) and any(kw in str(p).lower() for kw in ['name', 'label', 'title']):
            pred_name = str(p).split('#')[-1] if '#' in str(p) else str(p)
            name_preds.add(pred_name)
    for pred in sorted(name_preds):
        print(f"   - {pred}")
    
    print("\n=== INSPECTION COMPLETE ===")
    return True


def inspect_with_grep(ttl_file: str):
    """Fallback: use grep-based inspection when rdflib is not available."""
    import subprocess
    
    print("=== GRAPH INSPECTION (grep fallback) ===\n")
    
    # 1. Find prefix
    print("1. PREFIX:")
    result = subprocess.run(['grep', '@prefix', ttl_file], capture_output=True, text=True)
    for line in result.stdout.split('\n')[:5]:
        if line.strip():
            print(f"   {line.strip()}")
    
    # 2. Find University declarations
    print("\n2. UNIVERSITY URIs:")
    result = subprocess.run(['grep', '-E', 'a\\s+.*University', ttl_file], capture_output=True, text=True)
    for line in result.stdout.split('\n')[:5]:
        if line.strip():
            print(f"   {line.strip()}")
    
    # 3. Find role-related predicates
    print("\n3. ROLE/RANK PREDICATES:")
    result = subprocess.run(['grep', '-iE', '(role|rank|position|title)', ttl_file], capture_output=True, text=True)
    for line in result.stdout.split('\n')[:10]:
        if line.strip() and not line.strip().startswith('#'):
            print(f"   {line.strip()}")
    
    print("\n=== INSPECTION COMPLETE ===")
    return True


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <ttl_file>")
        sys.exit(1)
    
    ttl_file = sys.argv[1]
    if not Path(ttl_file).exists():
        print(f"Error: File '{ttl_file}' not found")
        sys.exit(1)
    
    # Try rdflib first, fall back to grep
    if not inspect_with_rdflib(ttl_file):
        print("rdflib not available, using grep fallback...\n")
        inspect_with_grep(ttl_file)
