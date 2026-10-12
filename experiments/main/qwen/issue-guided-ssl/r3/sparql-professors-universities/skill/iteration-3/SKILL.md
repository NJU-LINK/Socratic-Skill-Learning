---
name: sparql-professors-universities
description: >
  Reusable methodology for writing SPARQL queries that retrieve professor names
  paired with their university names from university knowledge graphs. Covers
  three variation axes: (1) professor identification semantics (string roles vs
  resource-based academic ranks), (2) affiliation chain structure from person to
  university (direct links, multi-hop chains, property paths, fallback paths),
  and (3) graph noise and result cardinality (DISTINCT enforcement, correct
  projection). Includes a validation script for testing queries against Turtle
  data using rdflib.
---

# SPARQL Professors-Universities Query Skill

## Task Family Definition

Given a Turtle (`.ttl`) knowledge graph describing universities, departments,
people, and their relationships, produce a SPARQL query that:

1. Identifies all qualifying professors
2. For each professor, retrieves the name of the university they work at
3. Returns exactly one row per (professor, university) pair
4. Projects exactly two variables: `?professorName` and `?universityName`

## Three Variation Axes

### Axis 1: Professor Identification Semantics

How qualifying professors are represented and distinguished from non-target roles.

**v01 mechanism**: `uni:role` is a string literal. Qualifying values contain the
substring "professor" (case-insensitive): `"Professor of X"`,
`"Assistant Professor of X"`, `"Full Professor"`, etc. Non-qualifying roles:
`"Lecturer"`, `"Student"`, `"Staff"`.

**Variant possibilities**:
- Different role strings or abbreviations (`"Prof."`, `"Asst. Prof."`)
- Resource-based representation: `uni:hasAcademicRank` pointing to a rank
  resource with `uni:rankLabel`
- Professor-like near misses that must be excluded

**General strategy**: Use substring/pattern matching rather than exact equality.
For string-valued roles:
```sparql
FILTER(CONTAINS(LCASE(?roleStr), "professor"))
```
For resource-based ranks:
```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(CONTAINS(LCASE(?rankLabel), "professor"))
```

**Diagnostic**: Before writing the query, inspect the TTL to find:
- Which predicate carries the role/rank information
- Whether it's a literal string or a resource reference
- All distinct role/rank values present in the data
- Which values should qualify vs. not qualify

### Axis 2: Affiliation Structure to University

How a person is linked to the university whose name should be returned.

**v01 mechanism**: Two-hop chain:
```
?person uni:worksAt ?department .
?department uni:partOfUniversity ?university .
```

**Variant possibilities**:
- Direct affiliation: `?person uni:affiliatedWith ?university`
- Longer chains through intermediate organizations
- Inverse containment: `?university uni:hasDepartment ?dept . ?dept uni:hasMember ?person`
- Appointment resources as intermediaries
- Fallback paths (e.g., via `uni:teaches` course when `uni:worksAt` is absent)

**General strategy**: Use SPARQL property paths with alternatives:
```sparql
# Primary: two-hop via department
?person uni:worksAt/uni:partOfUniversity ?university .

# Alternative: direct affiliation
?person uni:affiliatedWith ?university .

# Alternative: inverse containment
?university uni:hasDepartment+/uni:hasMember ?person .
```

For fallback patterns, use `OPTIONAL` or `UNION`:
```sparql
{
  ?person uni:worksAt/uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?university .
  FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
}
```

**Key invariant**: Always anchor the university end with a type check or name
pattern to ensure you land on a university entity:
```sparql
?university a uni:University .
?university uni:hasName ?universityName .
```

**Diagnostic**: Before writing the query, trace all paths from a known professor
to a known university in the TTL. Identify every predicate involved.

### Axis 3: Graph Noise and Result Cardinality

How distracting data and duplicate-binding risk is managed.

**Noise sources**:
- Non-professor people (students, lecturers, staff)
- Multiple departments within one university
- Multiple role assertions per person
- Overlapping organization paths

**Invariant**: Exactly one row per qualifying (professor, university) pair,
projecting exactly `?professorName` and `?universityName`.

**General strategy**: Always use `SELECT DISTINCT`:
```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
```

**Diagnostic**: After writing the query, check:
- Are there any people who might match the professor filter but shouldn't?
- Could any professor bind to multiple universities?
- Does the result count match the expected number of qualifying professors?

## TTL Discovery Protocol

When facing a non-v01 variant, use these diagnostic SPARQL queries to automatically discover the ontology structure. Run them in order before writing your solution query.

### Step 1: Discover Role/Rank Predicates

Find which predicates carry role or rank information for people. Run **both** queries in parallel to catch both string-valued roles and resource-based ranks:

**Query 1a: Literal-valued predicates** (catches string roles like `uni:role`):

```sparql
SELECT DISTINCT ?predicate (COUNT(?value) AS ?count)
WHERE {
  ?person a ?personType .
  FILTER(CONTAINS(STR(?personType), "Person"))
  ?person ?predicate ?value .
  FILTER(isLiteral(?value))
}
GROUP BY ?predicate
ORDER BY DESC(?count)
```

**Query 1b: IRI-valued predicates** (catches resource-based ranks like `uni:hasAcademicRank`):

```sparql
SELECT DISTINCT ?predicate (COUNT(?object) AS ?count)
WHERE {
  ?person a ?personType .
  FILTER(CONTAINS(STR(?personType), "Person"))
  ?person ?predicate ?object .
  FILTER(isIRI(?object))
  FILTER(?predicate != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
}
GROUP BY ?predicate
ORDER BY DESC(?count)
```

**Interpretation**:
- Query 1a: If you see a predicate with string datatype (xsd:string or no datatype), it's likely a role string like `uni:role`
- Query 1b: If you see a predicate with IRI values (not rdf:type), it's likely a resource-based rank like `uni:hasAcademicRank`
- Run both queries. If 1a returns results, you have string-valued roles. If 1b returns results (excluding rdf:type), you have resource-based ranks. Both may be present.

### Step 2: Discover Distinct Role/Rank Values

Once you've identified the role/rank predicate, find all distinct values:

```sparql
# For string-valued roles (e.g., uni:role)
SELECT DISTINCT ?role
WHERE {
  ?person uni:role ?role .
}
ORDER BY ?role
```

```sparql
# For resource-valued ranks (e.g., uni:hasAcademicRank)
SELECT DISTINCT ?rank ?rankLabel
WHERE {
  ?person uni:hasAcademicRank ?rank .
  OPTIONAL { ?rank uni:rankLabel ?rankLabel . }
}
ORDER BY ?rankLabel
```

**Interpretation**: Identify which values contain "professor" (case-insensitive) and which should be excluded.

### Step 3: Discover Person-to-University Paths

Trace paths from professors to universities. Use a **generic starting point** that works for both string-valued roles and resource-based ranks:

**Query 3a: If you discovered string-valued roles (from Step 1a)**:

```sparql
# Find all predicates linking professors (identified by string role) to other entities
SELECT DISTINCT ?predicate ?object
WHERE {
  ?person <DISCOVERED_ROLE_PREDICATE> ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  ?person ?predicate ?object .
}
ORDER BY ?predicate
```

**Query 3b: If you discovered resource-based ranks (from Step 1b)**:

```sparql
# Find all predicates linking people with rank resources to other entities
SELECT DISTINCT ?predicate ?object
WHERE {
  ?person <DISCOVERED_RANK_PREDICATE> ?rank .
  FILTER(isIRI(?rank))
  ?person ?predicate ?object .
}
ORDER BY ?predicate
```

**Query 3c: Generic fallback (if uncertain which variant)**:

```sparql
# Find predicates from any person who has either a string role or IRI rank
SELECT DISTINCT ?predicate ?object
WHERE {
  {
    ?person ?rolePred ?role .
    FILTER(isLiteral(?role))
    FILTER(CONTAINS(LCASE(?role), "professor"))
  }
  UNION
  {
    ?person ?rankPred ?rank .
    FILTER(isIRI(?rank))
    FILTER(?rankPred != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
  }
  ?person ?predicate ?object .
}
ORDER BY ?predicate
```

**Interpretation**: Look for predicates that might lead to a university:
- `uni:worksAt` → likely leads to a department
- `uni:affiliatedWith` → might lead directly to a university
- `uni:teaches` → leads to a course, which might lead to a department

Then follow the chain:

```sparql
# If worksAt leads to a department, find how departments connect to universities
SELECT DISTINCT ?deptPredicate ?university
WHERE {
  ?person <DISCOVERED_WORKSAT_PREDICATE> ?dept .
  ?dept ?deptPredicate ?university .
  ?university a ?uniType .
  FILTER(CONTAINS(STR(?uniType), "University"))
}
```

### Step 4: Discover University Name Predicate

Find which predicate carries the university name:

```sparql
SELECT DISTINCT ?namePredicate ?name
WHERE {
  ?university a ?uniType .
  FILTER(CONTAINS(STR(?uniType), "University"))
  ?university ?namePredicate ?name .
  FILTER(isLiteral(?name))
}
ORDER BY ?namePredicate
```

**Interpretation**: Look for predicates like `uni:hasName`, `rdfs:label`, `uni:name`, etc.

### Step 5: Validate Discovery

After discovering the structure, run a test query to verify:

```sparql
# Test query using discovered predicates
SELECT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          <DISCOVERED_ROLE_PREDICATE> ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  ?person <DISCOVERED_AFFILIATION_PREDICATE> ?org .
  ?org <DISCOVERED_ORG_TO_UNI_PREDICATE> ?university .
  ?university <DISCOVERED_NAME_PREDICATE> ?universityName .
}
LIMIT 5
```

Replace the placeholders with the predicates you discovered.

## General Methodology

**Execution context**: The task runs inside an isolated container at `/app`.
Skill resources are mounted read-only at `/skill`. Use `task_shell` for all
commands inside the container. The TTL data is at `/app/university_graph.ttl`;
write your query to `/app/solution.sparql`.

1. **Run TTL Discovery Protocol** (see above) — Use diagnostic queries to automatically discover:
   - Which predicate carries role/rank information (string vs. resource)
   - All distinct role/rank values and which qualify as "professor"
   - The person-to-university path (direct, via department, via course)
   - Which predicate carries the university name

2. **Build the role/rank filter** — Based on discovery results:
   - For string-valued roles: use `FILTER(CONTAINS(LCASE(?role), "professor"))`
   - For resource-valued ranks: join to rank resource and filter on rankLabel
   - Test against all distinct values found in Step 1

3. **Construct the affiliation chain** — Based on discovery results:
   - Use the discovered predicates for person→organization→university path
   - If multiple paths exist, use UNION or property path alternatives
   - Always anchor the university end with a type check or name pattern

4. **Enforce cardinality** — `SELECT DISTINCT` with exactly the required
   projection variables (`?professorName`, `?universityName`).

5. **Validate** — Run the query against the data using the validation script:
   ```bash
   python3 /skill/scripts/validate_sparql.py /app/university_graph.ttl /app/solution.sparql
   ```
   Check:
   - Row count matches expected professor count
   - No non-professors appear in results
   - Each professor maps to the correct university
   - No duplicate rows

## v01 Worked Example

**Data characteristics**:
- Prefix: `uni: <http://university.org/ontology#>`
- 9 universities, 11 departments, 9 courses
- 7 professors (roles contain "Professor"), 1 lecturer, 3 students
- Affiliation: `uni:worksAt` → department → `uni:partOfUniversity` → university
- University name: `uni:hasName`

**Solution query** (`/app/solution.sparql`):
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
```

**v01 results** (7 rows):
| professorName | universityName |
|---|---|
| Alex Morgan | National Technical University of Athens |
| Thomas Berger | National Technical University of Athens |
| Felix Wagner | Instituto Superior Técnico |
| Martin Keller | National and Kapodistrian University of Athens |
| John Smith | Massachusetts Institute of Technology |
| Marie Dubois | Sorbonne University |
| Stefan Mueller | Ludwig Maximilian University of Munich |

**Excluded**: Jane Petterson (role "Lecturer"), 3 students (role "Student").

## Execution Environment & Validation

### Container Mount Points

When solving tasks inside the isolated `/app` container via `task_shell`:
- The TTL data file is at `/app/university_graph.ttl` (or similar)
- The skill package is mounted read-only at **`/skill`**
- Your solution file goes to `/app/solution.sparql`

**Important**: Do NOT use host workspace paths from within `task_shell`. The
container filesystem is isolated. Use the `/skill` mount point for skill
resources.

### Validation Script

Use the provided script to test any `.sparql` query against a `.ttl` file:
```bash
python3 /skill/scripts/validate_sparql.py /app/university_graph.ttl /app/solution.sparql
```

This runs the query using `rdflib` and reports the result count, variables, and
all rows sorted for easy inspection.

### Quick Inline Validation (no script needed)

If the validation script is unavailable, you can validate inline:
```bash
python3 -c "
from rdflib import Graph
g = Graph().parse('/app/university_graph.ttl')
with open('/app/solution.sparql') as f: q = f.read()
for row in g.query(q): print(row)
"
```
