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

## General Methodology

1. **Read the TTL file** — Understand the ontology (prefixes, classes, predicates)
   and the instance data. Identify:
   - How professors are marked (role string vs. rank resource)
   - The person-to-university path (direct, via department, via course)
   - Potential noise sources (non-professors, duplicate paths)

2. **Build the role/rank filter** — Use substring/pattern matching, not exact
   equality. Test against all distinct role values in the data.

3. **Trace the affiliation chain** — Identify every predicate connecting a person
   to a university. Use property paths or UNION for alternatives. Always anchor
   the university end with a type or name check.

4. **Enforce cardinality** — `SELECT DISTINCT` with exactly the required
   projection variables (`?professorName`, `?universityName`).

5. **Validate** — Run the query against the data. Check:
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

## Validation

Use the provided script to test any `.sparql` query against a `.ttl` file:
```bash
python3 scripts/validate_sparql.py <ttl_file> <sparql_file>
```

This runs the query using `rdflib` and reports the result count, variables, and
all rows sorted for easy inspection.
