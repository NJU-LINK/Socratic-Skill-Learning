---
name: sparql-professors-universities
description: Generate SPARQL queries to retrieve professor names and their affiliated university names from university knowledge graphs, handling variations in professor identification, affiliation structures, and avoiding cardinality bugs.
---

# SPARQL Professors-Universities Query Skill

## Overview

This skill addresses querying knowledge graphs to find professors and the universities they work at. The task involves identifying qualifying professors, navigating affiliation paths, and ensuring correct result cardinality.

## Core Task

Create a SPARQL query that returns `?professorName` and `?universityName` for each qualifying professor, with exactly one row per professor-university pair.

## Family Invariants

- **Input**: A Turtle file containing ontology and instance data
- **Output**: SPARQL query saved to `solution.sparql`
- **Projection variables**: `?professorName` and `?universityName`
- **Result cardinality**: Exactly one row per qualifying professor-university pair
- **Ontology namespace**: Typically `uni:` or similar university ontology prefix

## Variation Dimensions

### 1. Professor Identification Semantics

**Critical principle**: Derive the filter from **task instruction** + **observed values**, not assumptions.

**Step 1: Enumerate observed values**
```sparql
SELECT DISTINCT ?role WHERE { ?p a uni:Person ; uni:role ?role }
```

**Step 2: Analyze task instruction**
- What ranks qualify? (e.g., "Assistant Professors and Full Professors")
- What should be excluded? (e.g., "Lecturers", "Students", "Staff", "Emeritus")

**Step 3: Choose precise filter**

For string-valued roles (v01 pattern):
```sparql
# Strict pattern - matches "Professor" or "Assistant Professor" at start
# Requires "of " or end-of-string after "Professor"
# This excludes "Professor Emeritus", "Visiting Professor", etc.
FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))

# Alternative: Token-boundary with explicit exclusions
FILTER(REGEX(STR(?role), "^(Assistant )?Professor( |$)", "i"))
FILTER(!REGEX(STR(?role), "emeritus|visiting|adjunct", "i"))

# For exact rank matching with known closed vocabulary
FILTER(STR(?role) IN ("Professor", "Assistant Professor"))
```

For resource-valued ranks (spec-declared variant):
```sparql
?professor uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(?rankLabel IN ("Professor", "Assistant Professor"))
```

**Step 4: Validate both directions**
```sparql
# What qualifying ranks does my filter miss?
SELECT ?role WHERE {
  ?p uni:role ?role
  FILTER(?role IN ("Professor", "Assistant Professor"))  # expected
  FILTER(!REGEX(STR(?role), "^(Assistant )?Professor( |$)", "i"))  # but regex misses
}

# What non-target roles does my filter admit?
SELECT ?role WHERE {
  ?p uni:role ?role
  FILTER(?role NOT IN ("Professor", "Assistant Professor"))
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor( |$)", "i"))  # but regex includes
}
```

### 2. Affiliation Structure

**Critical principle**: Use UNION with NOT EXISTS guards, not OPTIONAL+COALESCE, to avoid cardinality bugs.

**The bug with OPTIONAL+COALESCE**:
When a professor teaches courses in multiple departments (even across universities), OPTIONALs create cross-product solutions, causing duplicates or multiple universities per professor.

**Why UNION+NOT EXISTS is superior to UNION alone**:
The NOT EXISTS guard serves dual purposes:
1. **Prevents fallback activation** when primary path exists
2. **Prevents path redundancy duplicates** - without the guard, both paths may resolve to the same university, creating duplicate rows

Example from v01: Without NOT EXISTS, UNION produces 15 rows (path redundancy); with NOT EXISTS, produces 7 rows (correct).

**Determining if fallback is needed**:
```sparql
# Check: Are there professors who teach but don't have worksAt?
SELECT ?name
WHERE {
  ?p a uni:Person ; uni:hasName ?name ; uni:role ?role .
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
  ?p uni:teaches ?c .
  FILTER NOT EXISTS { ?p uni:worksAt ?d }
}
```
- If results exist: Include UNION fallback
- If empty: Fallback optional but recommended for robustness

**Correct pattern**:
```sparql
# Primary path
{ ?professor uni:worksAt ?dept . ?dept uni:partOfUniversity ?university . }
UNION
# Fallback only when primary absent
{ ?professor uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?university .
  FILTER NOT EXISTS { ?professor uni:worksAt ?any } }
```

**Structural variants to handle**:

| Pattern | SPARQL Pattern |
|---------|----------------|
| Direct university | `?professor uni:worksAt ?university` |
| Via department (v01) | `?professor uni:worksAt/uni:partOfUniversity ?university` |
| Via appointment | `?professor uni:hasAppointment/uni:atInstitution ?university` |
| Teaching fallback | `?professor uni:teaches/uni:isTaughtIn/uni:partOfUniversity ?university` |
| Inverse containment | `?university ^uni:partOfUniversity/^uni:worksAt ?professor` |

### 3. Graph Noise and Cardinality

**Always use SELECT DISTINCT** for this family:
- The invariant requires exactly one row per professor-university pair
- Projection is exactly that pair
- DISTINCT never removes legitimate rows
- DISTINCT collapses duplicates from multiple departments/courses within same university

## Implementation Steps

1. **Load and inspect** the Turtle file
2. **Detect namespace/prefix** - verify ontology namespace (typically `uni:`)
3. **Enumerate role values** to understand professor identification
4. **Design precise role filter** based on instruction + observed values
5. **Trace affiliation paths** from person to university
6. **Implement UNION-based fallback** if multiple paths possible
7. **Add SELECT DISTINCT** and test
8. **Validate** expected professor count, no duplicates, correct exclusions

### Namespace Detection

Before writing the query, verify the ontology namespace:
```sparql
# Check what prefixes are used
SELECT DISTINCT ?ns
WHERE {
  ?s a ?type .
  FILTER(STRSTARTS(STR(?type), "http://"))
  BIND(STRBEFORE(STR(?type), "#") AS ?ns_base)
  BIND(IF(CONTAINS(STR(?type), "#"), CONCAT(?ns_base, "#"), 
         REPLACE(STR(?type), "^(.*)[/#].*$", "$1")) AS ?ns)
}
```

Common namespace patterns:
- `http://university.org/ontology#` → `PREFIX uni: <http://university.org/ontology#>`
- `http://example.org/university/` → `PREFIX uni: <http://example.org/university/>`

## Validation Query Templates

```sparql
# Enumerate all roles
SELECT DISTINCT ?role (COUNT(?p) AS ?count)
WHERE { ?p a uni:Person ; uni:role ?role }
GROUP BY ?role
ORDER BY ?role

# Check for professors without affiliation path
ASK {
  ?p a uni:Person ; uni:role ?role .
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
  FILTER NOT EXISTS { ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u }
  FILTER NOT EXISTS { ?p uni:teaches ?c . ?c uni:isTaughtIn ?d . ?d uni:partOfUniversity ?u }
}

# Count results before/after DISTINCT
SELECT (COUNT(*) AS ?total) (COUNT(DISTINCT ?professor) AS ?unique)
WHERE {
  ?professor a uni:Person ; uni:role ?role .
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
  # ... rest of query without DISTINCT
}

# Detect path redundancy: professors reachable by multiple paths
SELECT ?name (COUNT(*) AS ?paths)
WHERE {
  ?p a uni:Person ; uni:hasName ?name ; uni:role ?role .
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
  
  { ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u . }
  UNION
  { ?p uni:teaches ?c . ?c uni:isTaughtIn ?d . ?d uni:partOfUniversity ?u . }
}
GROUP BY ?name
HAVING (COUNT(*) > 1)
```

## Common Pitfalls

1. **Substring matching** (`CONTAINS(?role, "Professor")`) admits false positives like "Research Assistant to the Professor" or "Professor Emeritus"
2. **Token-boundary without validation** (`^(Assistant )?Professor( |$)`) still admits "Professor Emeritus" because space matches before "Emeritus"
3. **UNION without NOT EXISTS** produces 15 rows instead of 7 in v01 (path redundancy duplicates)
4. **OPTIONAL+COALESCE** causes cardinality multiplication when fallback path has multiple solutions
5. **Missing DISTINCT** causes duplicates when professor has multiple departments/courses
6. **Assuming direct paths** without checking for intermediate nodes (departments, colleges)
7. **Not testing both directions** of the filter (what's included vs what's excluded)
8. **Wrong namespace prefix** - variants may use different ontology URIs

## v01 Solution (Corrected)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
             uni:hasName ?professorName ;
             uni:role ?role .
  
  # Match "Professor" or "Assistant Professor" at start
  # Requires end-of-string or "of " after "Professor" (excludes "Professor Emeritus")
  FILTER(REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
  
  # Primary path: worksAt -> department -> university
  { ?professor uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?university . }
  
  # Fallback: teaches -> course -> department -> university (only if no worksAt)
  UNION
  { ?professor uni:teaches ?course .
    ?course uni:isTaughtIn ?dept2 .
    ?dept2 uni:partOfUniversity ?university .
    FILTER NOT EXISTS { ?professor uni:worksAt ?anyDept . } }
  
  ?university uni:hasName ?universityName .
}
```

**Test case demonstrating the OPTIONAL bug**: In v01, Felix Wagner teaches both Math101 (Mathematics_IST) and AI101 (ComputerScience_NTUA). Using OPTIONAL+COALESCE produces 8 rows instead of 7. The UNION+NOT EXISTS pattern correctly produces 7 rows.

## Validation Procedure

After constructing the query, run these checks:

```python
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# Load and execute your solution
with open("/app/solution.sparql") as f:
    query = f.read()
results = list(g.query(query))

# Check 1: Count matches expected
print(f"Results: {len(results)}")

# Check 2: No duplicates
names = [str(r.professorName) for r in results]
assert len(names) == len(set(names)), "Duplicate names found!"

# Check 3: All results have both variables
for r in results:
    assert r.professorName, "Missing professorName"
    assert r.universityName, "Missing universityName"

# Check 4: Verify filter exclusions
excluded_query = """
PREFIX uni: <http://university.org/ontology#>
SELECT ?name ?role
WHERE {
  ?p a uni:Person ; uni:hasName ?name ; uni:role ?role .
  FILTER(!REGEX(STR(?role), "^(Assistant )?Professor($| of )", "i"))
}
ORDER BY ?role
"""
print("Excluded persons (verify these should be excluded):")
for row in g.query(excluded_query):
    print(f"  {row.name}: '{row.role}'")
```
