---
name: sparql-professors-universities
description: >
  Construct SPARQL queries that retrieve professor names paired with their
  university names from a Turtle knowledge graph. Provides a unified
  discovery-and-build script that automatically detects the ontology structure
  and generates the correct query, handling variation in professor identification
  (string roles vs. resource-based ranks), affiliation chains (direct links,
  department intermediaries, teaching fallbacks), and graph noise (duplicate
  bindings, non-professor distractors).
---

# SPARQL Professors–Universities Query Construction

## Task Shape

Given a Turtle file containing ontology + instance data for a university knowledge graph, produce a SPARQL query that:
1. Identifies all qualifying professors
2. For each, retrieves the name of the university they work at
3. Returns `?professorName` and `?universityName`
4. Produces exactly one row per professor–university pair

## Unified Discovery-and-Build Script

**Run this script first.** It discovers the ontology structure, builds the query, validates it, and saves it.

```python
from rdflib import Graph, URIRef, RDF
import re

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# 1. Discover all predicates and categorize them
predicates = sorted(set(str(p) for s, p, o in g))
name_preds = [p for p in predicates if 'name' in p.lower() or 'label' in p.lower()]
role_preds = [p for p in predicates if 'role' in p.lower() or 'rank' in p.lower()]
affil_preds = [p for p in predicates if 'work' in p.lower() or 'affiliat' in p.lower() or 'partof' in p.lower()]
teach_preds = [p for p in predicates if 'teach' in p.lower()]
classes = sorted(set(str(o) for s, p, o in g if p == RDF.type))
person_class = [c for c in classes if 'person' in c.lower()][0]

# 2. Extract namespace prefix from TTL file
with open("/app/university_graph.ttl") as f:
    content = f.read()
prefix_match = re.search(r'@prefix\s+(\w+):\s+<([^>]+)>\s*\.', content)
if prefix_match:
    prefix_name = prefix_match.group(1)
    namespace = prefix_match.group(2)
    if not namespace.endswith('#'):
        namespace += '#'
else:
    namespace = predicates[0].rsplit('#', 1)[0] + '#'
    prefix_name = "ont"

# 3. Determine professor identification pattern
persons = list(g.subjects(RDF.type, URIRef(person_class)))
sample_roles = [list(g.objects(p, URIRef(role_preds[0]))) for p in persons[:3]]
roles_are_strings = all(hasattr(r, 'value') for roles in sample_roles for r in roles)

role_pred_local = role_preds[0].split("#")[-1]
if roles_are_strings:
    role_pattern = f'{prefix_name}:{role_pred_local} ?role .\n  FILTER(CONTAINS(?role, "Professor"))'
else:
    # Resource-based rank: need to find the label predicate for rank resources
    label_preds = [p for p in predicates if 'label' in p.lower()]
    label_local = label_preds[0].split("#")[-1] if label_preds else "rankLabel"
    role_pattern = (f'{prefix_name}:{role_pred_local} ?rank .\n'
                    f'  ?rank {prefix_name}:{label_local} ?rankLabel .\n'
                    f'  FILTER(CONTAINS(?rankLabel, "Professor"))')

# 4. Determine affiliation chain pattern
works_pred = [p for p in affil_preds if 'work' in p.lower()]
partof_pred = [p for p in affil_preds if 'partof' in p.lower()]
direct_affil = [p for p in affil_preds if 'affiliat' in p.lower() or 'employ' in p.lower()]

if works_pred and partof_pred:
    works_local = works_pred[0].split('#')[-1]
    partof_local = partof_pred[0].split('#')[-1]
    affil_chain = (f"?person {prefix_name}:{works_local} ?dept .\n"
                   f"  ?dept {prefix_name}:{partof_local} ?uni .")
elif direct_affil:
    direct_local = direct_affil[0].split('#')[-1]
    affil_chain = f"?person {prefix_name}:{direct_local} ?uni ."
elif teach_preds and partof_pred:
    teach_local = teach_preds[0].split('#')[-1]
    course_dept = [p for p in predicates if 'taughtin' in p.lower()]
    cd_local = course_dept[0].split('#')[-1] if course_dept else "isTaughtIn"
    partof_local = partof_pred[0].split('#')[-1]
    affil_chain = (f"?person {prefix_name}:{teach_local} ?course .\n"
                   f"  ?course {prefix_name}:{cd_local} ?dept .\n"
                   f"  ?dept {prefix_name}:{partof_local} ?uni .")

# 5. Build and save query
name_pred_local = name_preds[0].split("#")[-1]
query = f"""PREFIX {prefix_name}: <{namespace}>

SELECT DISTINCT ?professorName ?universityName
WHERE {{
  ?person a {prefix_name}:Person ;
          {prefix_name}:{name_pred_local} ?professorName ;
          {role_pattern}
  {affil_chain}
  ?uni {prefix_name}:{name_pred_local} ?universityName .
}}"""

with open("/app/solution.sparql", "w") as f:
    f.write(query)

# 6. Validate
results = g.query(query)
rows = sorted(results, key=lambda r: str(r[0]))
print(f"Result count: {len(rows)}")
for row in rows:
    print(f"  {row[0]} -> {row[1]}")

unique_rows = set((str(r[0]), str(r[1])) for r in rows)
assert len(rows) == len(unique_rows), "Duplicates found!"
print(f"\n✓ Query saved to /app/solution.sparql with {len(rows)} results")
```

## When the Script Needs Adjustment

The script handles common cases. Manual adjustment is needed when:

### Task instruction names specific predicates
If the task says "use `uni:role`" or similar, use those predicates directly.

### Professor identification is type-based
If professors have RDF types like `a uni:Professor`:
```sparql
?person a uni:Professor .
```
Or UNION of types: `{ ?person a uni:FullProfessor } UNION { ?person a uni:AssistantProfessor }`

### Multiple affiliation paths (preferred + fallback)
Use OPTIONAL + COALESCE to avoid duplicates:
```sparql
OPTIONAL { ?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uniW . }
OPTIONAL { ?person uni:teaches ?course . ?course uni:isTaughtIn ?d2 . ?d2 uni:partOfUniversity ?uniT . }
BIND(COALESCE(?uniW, ?uniT) AS ?uni)
```

### Professor filter edge cases
- `CONTAINS(?role, "Professor")` is case-sensitive — verify capitalization
- "Professor Emeritus", "Associate Professor", "Visiting Professor" — check task instructions for inclusion
- If both string roles AND resource ranks exist, use UNION of both patterns

## Validation Checklist

1. **Count**: How many professors should there be?
2. **No false positives**: No students, lecturers, or staff in results
3. **No false negatives**: No professors missing
4. **No duplicates**: Each professor appears exactly once
5. **Correct universities**: Names match the affiliation chain
6. **Run programmatically**: Use rdflib to execute and inspect

## v01 Concrete Reference

For the seed `university_graph.ttl`:
- Prefix: `uni:` → `http://university.org/ontology#`
- Person class: `uni:Person`, Name: `uni:hasName`
- Professor ID: `uni:role` containing "Professor"
- Affiliation: `uni:worksAt` → dept → `uni:partOfUniversity` → `uni:hasName`
- Expected: 7 professors (Alex Morgan, Thomas Berger, Felix Wagner, Martin Keller, John Smith, Marie Dubois, Stefan Mueller)
- Excluded: Jane Petterson (Lecturer), 3 Students
