#!/usr/bin/env python3
"""
Automated schema discovery and query construction for SPARQL professors-universities tasks.

This script implements the discovery procedure from SKILL.md:
1. Inspects the graph schema (role representation, affiliation path, name predicate)
2. Constructs the appropriate SPARQL query
3. Validates the results

Usage:
    python3 scripts/discover_and_query.py <ttl_file> <output_sparql_file>
"""

import sys
from pathlib import Path
from rdflib import Graph, Namespace

def discover_schema(g):
    """
    Discover the schema by probing the graph.
    Returns a dict with discovered patterns.
    """
    schema = {
        'role_pattern': None,
        'role_predicate': None,
        'rank_predicate': None,
        'rank_label_predicate': None,
        'affiliation_path': None,
        'name_predicate': None
    }
    
    # Probe 1a: How are professor roles represented?
    print("=== Step 1a: Discovering role representation ===")
    
    # Check for string-valued role predicates
    query = """
    SELECT DISTINCT ?pred WHERE {
      ?person a <http://university.org/ontology#Person> ; ?pred ?val .
      FILTER(isLiteral(?val))
    }
    """
    try:
        results = list(g.query(query))
        literal_preds = [str(row.pred) for row in results]
        print(f"Found literal predicates on Person: {literal_preds}")
        
        # Look for role-like predicates
        for pred in literal_preds:
            if 'role' in pred.lower():
                schema['role_predicate'] = pred
                # Check if values contain "prof"
                check_query = f"""
                SELECT DISTINCT ?val WHERE {{
                  ?person <{pred}> ?val .
                  FILTER(REGEX(LCASE(?val), "(^|[^a-zA-Z])prof"))
                }}
                """
                prof_results = list(g.query(check_query))
                if prof_results:
                    schema['role_pattern'] = 'string'
                    print(f"✓ Found string-valued role predicate: {pred}")
                    print(f"  Values matching 'prof': {len(prof_results)}")
                    break
    except Exception as e:
        print(f"Error probing literal predicates: {e}")
    
    # Check for resource-based rank predicates
    if not schema['role_pattern']:
        query = """
        SELECT DISTINCT ?pred ?val WHERE {
          ?person a <http://university.org/ontology#Person> ; ?pred ?val .
          FILTER(isIRI(?val))
        }
        """
        try:
            results = list(g.query(query))
            resource_preds = [(str(row.pred), str(row.val)) for row in results]
            print(f"Found resource predicates on Person: {set(p[0] for p in resource_preds)}")
            
            # Look for rank-like predicates
            for pred, val in resource_preds:
                if 'rank' in pred.lower():
                    schema['rank_predicate'] = pred
                    # Check if the resource has a label containing "prof"
                    label_query = f"""
                    SELECT DISTINCT ?label WHERE {{
                      <{val}> ?labelPred ?label .
                      FILTER(isLiteral(?label))
                    }}
                    """
                    label_results = list(g.query(label_query))
                    if label_results:
                        for label_row in label_results:
                            label = str(label_row.label)
                            if 'prof' in label.lower():
                                schema['role_pattern'] = 'resource'
                                schema['rank_label_predicate'] = str(label_row.labelPred)
                                print(f"✓ Found resource-based rank: {pred} → {val}")
                                print(f"  Label: {label}")
                                break
                    if schema['role_pattern']:
                        break
        except Exception as e:
            print(f"Error probing resource predicates: {e}")
    
    # Probe 1b: How does Person connect to University?
    print("\n=== Step 1b: Discovering affiliation path ===")
    
    # Check direct predicates
    query = """
    SELECT DISTINCT ?pred WHERE {
      ?person a <http://university.org/ontology#Person> .
      ?person ?pred ?uni .
      ?uni a <http://university.org/ontology#University> .
    }
    """
    try:
        results = list(g.query(query))
        if results:
            direct_pred = str(results[0].pred)
            schema['affiliation_path'] = f'direct:{direct_pred}'
            print(f"✓ Found direct Person→University predicate: {direct_pred}")
        else:
            # Check 2-hop paths
            query = """
            SELECT DISTINCT ?p1 ?p2 WHERE {
              ?person a <http://university.org/ontology#Person> .
              ?person ?p1 ?mid .
              ?mid ?p2 ?uni .
              ?uni a <http://university.org/ontology#University> .
            }
            """
            results = list(g.query(query))
            if results:
                p1 = str(results[0].p1)
                p2 = str(results[0].p2)
                schema['affiliation_path'] = f'2hop:{p1}:{p2}'
                print(f"✓ Found 2-hop path: {p1} → {p2}")
            else:
                print("✗ No affiliation path found")
    except Exception as e:
        print(f"Error probing affiliation path: {e}")
    
    # Probe 1c: How is university name stored?
    print("\n=== Step 1c: Discovering university name predicate ===")
    
    query = """
    SELECT DISTINCT ?pred WHERE {
      ?uni a <http://university.org/ontology#University> ; ?pred ?name .
      FILTER(isLiteral(?name))
    }
    """
    try:
        results = list(g.query(query))
        name_preds = [str(row.pred) for row in results]
        print(f"Found name predicates: {name_preds}")
        
        # Prefer hasName, then name, then label
        for pred in name_preds:
            if 'hasName' in pred or pred.endswith('#name'):
                schema['name_predicate'] = pred
                print(f"✓ Using name predicate: {pred}")
                break
        if not schema['name_predicate'] and name_preds:
            schema['name_predicate'] = name_preds[0]
            print(f"✓ Using fallback name predicate: {name_preds[0]}")
    except Exception as e:
        print(f"Error probing name predicate: {e}")
    
    return schema


def construct_query(schema, prefix='http://university.org/ontology#'):
    """
    Construct the SPARQL query based on discovered schema.
    """
    print("\n=== Step 2: Constructing query ===")
    
    # Build prefix declaration
    query = f"PREFIX uni: <{prefix}>\n\n"
    query += "SELECT DISTINCT ?professorName ?universityName\nWHERE {\n"
    query += "  ?person a uni:Person ;\n"
    query += "          uni:hasName ?professorName ;\n"
    
    # Add role/rank pattern
    if schema['role_pattern'] == 'string':
        role_pred = schema['role_predicate'].split('#')[-1]
        query += f"          uni:{role_pred} ?role ;\n"
    elif schema['role_pattern'] == 'resource':
        rank_pred = schema['rank_predicate'].split('#')[-1]
        rank_label_pred = schema['rank_label_predicate'].split('#')[-1]
        query += f"          uni:{rank_pred} ?rank ;\n"
    
    # Add affiliation path
    if schema['affiliation_path']:
        if schema['affiliation_path'].startswith('direct:'):
            pred = schema['affiliation_path'].split(':')[1].split('#')[-1]
            query += f"          uni:{pred} ?uni .\n"
        elif schema['affiliation_path'].startswith('2hop:'):
            parts = schema['affiliation_path'].split(':')
            p1 = parts[1].split('#')[-1]
            p2 = parts[2].split('#')[-1]
            query += f"          uni:{p1} ?dept .\n\n"
            query += f"  ?dept uni:{p2} ?uni .\n"
    
    # Add university name
    if schema['name_predicate']:
        name_pred = schema['name_predicate'].split('#')[-1]
        query += f"  ?uni uni:{name_pred} ?universityName .\n"
    
    # Add filter
    query += "\n"
    if schema['role_pattern'] == 'string':
        query += '  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))\n'
    elif schema['role_pattern'] == 'resource':
        query += f"  ?rank uni:{schema['rank_label_predicate'].split('#')[-1]} ?rankLabel .\n"
        query += '  FILTER(REGEX(LCASE(?rankLabel), "(^|[^a-zA-Z])prof"))\n'
    
    query += "}\n"
    
    print("Generated query:")
    print(query)
    return query


def validate_query(g, query):
    """
    Execute the query and validate results.
    """
    print("\n=== Step 3: Validating results ===")
    
    try:
        results = list(g.query(query))
        print(f"✓ Query executed successfully")
        print(f"✓ Found {len(results)} professors")
        
        # Check for duplicates
        prof_uni_pairs = [(str(row.professorName), str(row.universityName)) for row in results]
        if len(prof_uni_pairs) == len(set(prof_uni_pairs)):
            print("✓ No duplicates")
        else:
            print("✗ Duplicates detected")
        
        # Check both variables bound
        unbound = [p for p, u in prof_uni_pairs if not p or not u]
        if not unbound:
            print("✓ All variables bound")
        else:
            print(f"✗ Unbound variables: {unbound}")
        
        print("\nResults:")
        for prof, uni in sorted(prof_uni_pairs):
            print(f"  {prof:<30} → {uni}")
        
        return True
    except Exception as e:
        print(f"✗ Query execution failed: {e}")
        return False


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 discover_and_query.py <ttl_file> <output_sparql_file>")
        sys.exit(1)
    
    ttl_file = sys.argv[1]
    output_file = sys.argv[2]
    
    print(f"Loading {ttl_file}...")
    g = Graph()
    g.parse(ttl_file, format="turtle")
    
    # Discover schema
    schema = discover_schema(g)
    
    if not schema['role_pattern']:
        print("\n✗ Could not determine role pattern")
        sys.exit(1)
    
    if not schema['affiliation_path']:
        print("\n✗ Could not determine affiliation path")
        sys.exit(1)
    
    if not schema['name_predicate']:
        print("\n✗ Could not determine name predicate")
        sys.exit(1)
    
    # Construct query
    query = construct_query(schema)
    
    # Validate
    success = validate_query(g, query)
    
    if success:
        # Save query
        with open(output_file, 'w') as f:
            f.write(query)
        print(f"\n✓ Query saved to {output_file}")
    else:
        print("\n✗ Validation failed, query not saved")
        sys.exit(1)


if __name__ == '__main__':
    main()
