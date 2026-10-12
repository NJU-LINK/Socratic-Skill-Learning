---
name: sparql-professors-universities
description: >
  Construct SPARQL queries that retrieve professor names paired with their
  university names from a Turtle knowledge graph. Handles variation in how
  professors are identified (string roles vs. resource-based academic ranks),
  how affiliation chains connect people to universities (direct links,
  department intermediaries, appointment resources, teaching fallbacks), and
  varying levels of graph noise (duplicate bindings, multiple departments,
  non-professor distractors).
---

# SPARQL Professors–Universities Query Construction

## Task Shape

Given a Turtle (`.ttl`) file containing ontology + instance data for a university knowledge graph, produce a SPARQL query that:

1. Identifies all qualifying professors
2. For each, retrieves the name of the university they work at
3. Returns exactly two variables: `?professorName` and `?universityName`
4. Produces exactly one row per professor–university pair (no duplicates)

## General Procedure

### Step 1: Inspect the Turtle file

Before writing any SPARQL, read the `.ttl` file and identify:

- **The prefix namespace** (e.g., `uni:` → `http://university.org/ontology#`)
- **Person representation**: What class are people? (`uni:Person`, `foaf:Person`, etc.)
- **Name predicate**: How are names stored? (`uni:hasName`, `foaf:name`, `rdfs:label`, etc.)
- **Professor identification mechanism** — see Axis 1 below
- **Affiliation structure** — see Axis 2 below
- **Noise sources** — see Axis 3 below

### Step 2: Determine Professor Identification (Axis 1)

Professors must be distinguished from non-target roles (students, lecturers, staff, researchers, etc.). Two main patterns:

#### Pattern A: String-valued role property
```sparql
?person uni:role ?role .
FILTER(CONTAINS(?role, "Professor"))
```
- Works when roles are literal strings like `"Professor of Computer Science"` or `"Assistant Professor of Mathematics"`
- `CONTAINS` is case-sensitive in SPARQL — verify capitalization in the data
- This matches both "Professor" and "Assistant Professor" while excluding "Lecturer", "Student", etc.
- **Pitfall**: If the data contains role strings like "Professor Emeritus" or "Associate Professor" that should or shouldn't be included, adjust the filter accordingly
- **Pitfall**: A role like "Visiting Professor" may or may not qualify — check task instructions

#### Pattern B: Resource-based academic rank
```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(CONTAINS(?rankLabel, "Professor"))
```
- Used when rank is modeled as a resource rather than a plain string
- The rank resource may have a `rdf:type` (e.g., `uni:FullProfessor`, `uni:AssistantProfessor`) instead of or in addition to a label

#### Pattern C: Type-based classification
```sparql
?person a uni:Professor .
# or
?person a uni:FullProfessor .
# or UNION of professor types
```

#### Robust combined pattern (when uncertain):
```sparql
{
  ?person uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
}
UNION
{
  ?person uni:hasAcademicRank ?rank .
  ?rank uni:rankLabel ?rankLabel .
  FILTER(CONTAINS(?rankLabel, "Professor"))
}
```

### Step 3: Determine Affiliation Chain (Axis 2)

Link each professor to their university name. Multiple structural patterns:

#### Pattern A: Person → Department → University (most common in seed)
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
?uni uni:hasName ?universityName .
```

#### Pattern B: Direct person → university link
```sparql
?person uni:affiliatedWith ?uni .
?uni uni:hasName ?universityName .
```

#### Pattern C: Via appointment resource
```sparql
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?uni .
?uni uni:hasName ?universityName .
```

#### Pattern D: Teaching-course fallback
When `worksAt` may be absent for some professors, use a fallback through courses they teach:
```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?uni .
}
?uni uni:hasName ?universityName .
```
**Critical**: When using UNION or multiple paths, `SELECT DISTINCT` becomes essential to avoid duplicate rows.

#### Pattern E: Inverse containment
```sparql
?uni uni:hasDepartment ?dept .
?dept uni:hasMember ?person .
```

#### Pattern F: Preferred path with OPTIONAL + COALESCE fallback
When the spec says "preferred worksAt path with a teaching-course fallback when the preferred relation is absent", use OPTIONAL blocks with COALESCE instead of UNION:
```sparql
OPTIONAL {
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uniViaWorks .
}
OPTIONAL {
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept2 .
  ?dept2 uni:partOfUniversity ?uniViaTeaches .
}
BIND(COALESCE(?uniViaWorks, ?uniViaTeaches) AS ?uni)
?uni uni:hasName ?universityName .
```
**Why this is better than UNION for fallbacks**: UNION produces a cross-product of all matching paths, generating duplicates that must be collapsed with DISTINCT. OPTIONAL + COALESCE is semantically "try the first path; if it fails, use the second" — no duplicates are generated in the first place. COALESCE returns the first bound (non-error) value from its arguments.

**Generalization**: This pattern applies to any "preferred relation with fallback" scenario across any axis — e.g., preferred name predicate with a label fallback, or preferred rank property with a type-based fallback.

### Step 4: Handle Noise and Cardinality (Axis 3)

- **Multiple courses per professor**: If a professor teaches N courses and your query joins through `uni:teaches`, you get N rows. Use `SELECT DISTINCT` to collapse.
- **Multiple departments per university**: A professor might have appointments in multiple departments of the same university. `SELECT DISTINCT` handles this.
- **Non-professor distractors**: Students, lecturers, postdocs, administrative staff — all may have `worksAt` or `teaches` properties. The professor filter (Step 2) must exclude them.
- **Overlapping organization paths**: Ensure the chain leads to a `uni:University` (or equivalent), not just any organization.

### Step 5: Assemble and validate

Template:
```sparql
PREFIX <prefix>: <namespace>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a <PersonClass> ;
          <namePredicate> ?professorName ;
          <professorIdentificationPattern> .
  <affiliationChain> .
  <universityNameBinding> .
}
```

**Validation checklist**:
1. Count expected professors manually from the TTL file
2. Verify no non-professors appear in results
3. Verify no professors are missing
4. Verify each professor appears exactly once
5. Verify university names match expected values
6. If possible, run the query programmatically (e.g., with `rdflib` in Python)

## Programmatic Testing

When `rdflib` is available in Python:
```python
from rdflib import Graph

g = Graph()
g.parse("path/to/graph.ttl", format="turtle")

with open("solution.sparql") as f:
    query = f.read()

results = g.query(query)
for row in sorted(results, key=lambda r: str(r[0])):
    print(f"{row[0]} -> {row[1]}")
```

If `rdflib` is not installed, try `python3 -c "import rdflib"` first — it may already be available. If truly unavailable, validate by manual inspection of the TTL data.

## v01 Concrete Reference

For the seed task with the given `university_graph.ttl`:
- Prefix: `uni:` → `http://university.org/ontology#`
- Person class: `uni:Person`
- Name: `uni:hasName`
- Professor ID: `uni:role` string containing "Professor"
- Affiliation: `uni:worksAt` → department → `uni:partOfUniversity` → `uni:hasName`
- Expected: 7 professors (Alex Morgan, Thomas Berger, Felix Wagner, Martin Keller, John Smith, Marie Dubois, Stefan Mueller)
- Excluded: Jane Petterson (Lecturer), 3 Students
