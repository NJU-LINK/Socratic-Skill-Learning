#!/usr/bin/env python3
"""
Discover graph structure for sparql-professors-universities queries.

Reports on:
- Role values and rank resources (how professors are identified)
- Person-to-organization predicates and direction
- University linkage patterns
- Name predicates for persons and organizations
"""

import sys
from collections import Counter
from rdflib import Graph, Namespace, URIRef, Literal

def discover_graph(ttl_path):
    g = Graph()
    g.parse(ttl_path, format="turtle")
    
    print("=" * 60)
    print("GRAPH DISCOVERY REPORT")
    print("=" * 60)
    
    # 1. Discover professor identification patterns
    print("\n## 1. PROFESSOR IDENTIFICATION")
    
    # Check for uni:role values
    role_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?role
    WHERE {
        ?person a uni:Person ;
                uni:role ?role .
    }
    """
    roles = [str(row.role) for row in g.query(role_query)]
    
    if roles:
        print(f"\nFound {len(roles)} uni:role values:")
        for role in sorted(roles):
            is_prof = "professor" in role.lower()
            marker = " [PROF]" if is_prof else ""
            print(f"  - \"{role}\"{marker}")
    
    # Check for hasAcademicRank pattern (resource-based ranks)
    rank_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?rank ?label
    WHERE {
        ?person uni:hasAcademicRank ?rank .
        OPTIONAL { ?rank uni:rankLabel ?label }
    }
    """
    rank_results = list(g.query(rank_query))
    if rank_results:
        print(f"\nFound uni:hasAcademicRank pattern with {len(rank_results)} ranks:")
        for row in rank_results:
            label = f" (label: {row.label})" if row.label else ""
            print(f"  - {row.rank}{label}")
    else:
        print("\nNo uni:hasAcademicRank pattern found (using string roles)")
    
    # 2. Discover affiliation structure
    print("\n## 2. AFFILIATION STRUCTURE")
    
    # Find predicates from Person to Organization
    person_org_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?predicate ?objType
    WHERE {
        ?person a uni:Person ;
                ?predicate ?org .
        OPTIONAL { ?org a ?objType }
        FILTER (isURI(?org))
    }
    """
    person_org_preds = Counter()
    for row in g.query(person_org_query):
        pred = str(row.predicate)
        person_org_preds[pred] += 1
    
    print("\nPredicates from Person to Organization:")
    for pred, count in person_org_preds.most_common():
        print(f"  - {pred} ({count} occurrences)")
    
    # Find university linkage patterns
    print("\nUniversity linkage (Department → University):")
    dept_uni_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?predicate
    WHERE {
        ?dept a uni:Department ;
              ?predicate ?uni .
        ?uni a uni:University .
    }
    """
    for row in g.query(dept_uni_query):
        print(f"  - Department → {row.predicate} → University")
    
    # Check for inverse patterns
    print("\nInverse containment patterns:")
    inverse_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?predicate
    WHERE {
        ?uni a uni:University ;
             ?predicate ?dept .
        ?dept a uni:Department .
    }
    """
    for row in g.query(inverse_query):
        print(f"  - University → {row.predicate} → Department (inverse)")
    
    # 3. Discover name predicates
    print("\n## 3. NAME PREDICATES")
    
    name_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT DISTINCT ?pred
    WHERE {
        {?s a uni:Person ; ?pred ?name }
        UNION
        {?s a uni:University ; ?pred ?name }
        FILTER (isLiteral(?name))
    }
    """
    name_preds = set()
    for row in g.query(name_query):
        name_preds.add(str(row.pred))
    
    print("\nName predicates found:")
    for pred in sorted(name_preds):
        print(f"  - {pred}")
    
    # 4. Sample data census
    print("\n## 4. SAMPLE DATA CENSUS")
    
    count_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT (COUNT(DISTINCT ?person) AS ?count)
    WHERE {
        ?person a uni:Person .
    }
    """
    for row in g.query(count_query):
        print(f"\nTotal Persons: {row[0]}")
    
    uni_count_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT (COUNT(DISTINCT ?uni) AS ?count)
    WHERE {
        ?uni a uni:University .
    }
    """
    for row in g.query(uni_count_query):
        print(f"Total Universities: {row[0]}")
    
    dept_count_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT (COUNT(DISTINCT ?dept) AS ?count)
    WHERE {
        ?dept a uni:Department .
    }
    """
    for row in g.query(dept_count_query):
        print(f"Total Departments: {row[0]}")
    
    # Check for multi-department professors
    multi_dept_query = """
    PREFIX uni: <http://university.org/ontology#>
    SELECT ?person (COUNT(DISTINCT ?dept) AS ?deptCount)
    WHERE {
        ?person a uni:Person ;
                uni:worksAt ?dept .
    }
    GROUP BY ?person
    HAVING (?deptCount > 1)
    """
    multi_dept = list(g.query(multi_dept_query))
    if multi_dept:
        print(f"\nPersons with multiple worksAt: {len(multi_dept)}")
        for row in multi_dept:
            print(f"  - {row.person}: {row.deptCount} departments")
    else:
        print("\nNo persons with multiple worksAt departments")
    
    print("\n" + "=" * 60)
    print("END OF DISCOVERY REPORT")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python discover_graph.py <path_to_ttl_file>")
        sys.exit(1)
    
    discover_graph(sys.argv[1])
