---
name: sparql-professors-universities
description: >
  Construct a SPARQL query that retrieves all professors and the universities
  they work at from a Turtle knowledge graph. The skill handles variation in how
  professors are identified (string role vs. resource-based academic rank), how
  affiliation paths connect people to universities (direct links, department
  chains, appointment resources, or teaching-course fallbacks), and how graph
  noise and duplicate bindings are managed. Produces a .sparql file returning
  ?professorName and ?universityName with exactly one row per qualifying
  professor-university pair.
---

# SPARQL Professors-Universities Query Skill

## Task Invariants

Every member of this family shares these properties:

1. **Input**: A Turtle file at `/app/university_graph.ttl` containing ontology + instance data describing a university knowledge graph.
2. **Goal**: Write a SPARQL query that returns two variables: `?professorName` and `?universityName`.
3. **Output**: Save the query to `/app/solution.sparql`.
4. **Cardinality invariant**: Exactly one row per qualifying professor-university pair.
5. **Exclusions**: Non-professor roles (lecturers, students, staff, researchers without professor title, etc.) must be excluded.

## General Method

### Step 1: Inspect the Turtle File

Read the full Turtle file to discover:
- The namespace prefix (e.g., `uni:` → some URI)
- All class types present (Person, University, Department, etc.)
- All predicates used
- How persons relate to organizations
- How professor status is encoded

```bash
cat /app/university_graph.ttl
```

### Step 2: Identify the Professor Qualification Mechanism

There are two main patterns for identifying professors:

**Pattern A — String-valued role property** (seed v01):
- A predicate like `uni:role` with a string literal value
- Professor status determined by substring match: `CONTAINS(LCASE(?role), "professor")`
- This catches "Professor of X", "Assistant Professor of X", "Full Professor", etc.
- Excludes "Lecturer", "Student", "Staff", "Researcher" (unless they contain "professor")

**Pattern B — Resource-based academic rank**:
- A predicate like `uni:hasAcademicRank` pointing to a rank resource
- The rank resource has a label property like `uni:rankLabel` with a string value
- Filter on the label: `CONTAINS(LCASE(?rankLabel), "professor")`

**Diagnostic procedure**:
```python
from rdflib import Graph, Namespace, RDF
g = Graph().parse("/app/university_graph.ttl", format="turtle")

# Find all predicates used
predicates = set(str(p) for _, p, _ in g)

# Check for role-like string predicates on Person instances
for s, _, t in g.triples((None, RDF.type, EX.Person)):
    for p, o in g.predicate_objects(s):
        if isinstance(o, str) and "professor" in o.lower():
            print(f"String role pattern: {p} -> {o}")
        elif hasattr(o, 'n3'):
            # Check if object is a resource with a label
            for _, lp, lo in g.triples((o, None, None)):
                if "label" in str(lp).lower() and "professor" in str(lo).lower():
                    print(f"Resource rank pattern: {p} -> {o} via {lp} -> {lo}")
```

**Key decision**: Use a substring/regex match rather than exact match, because:
- "Professor of Computer Science" ≠ "Professor"
- "Assistant Professor of X" also qualifies
- This handles both "Professor" and "Assistant Professor" (and "Full Professor", etc.)

#### ⚠ CRITICAL: Enumerate-Before-You-Filter

**Never write a substring filter without first inspecting every distinct value it will operate on.** A naive `CONTAINS(LCASE(?role), "professor")` will match "professorial" (since "professor" is a substring of "professorial"), causing false positives like "Professorial Lecturer" — a non-professor role that contains the substring.

**Mandatory sub-step**: Before writing the filter, run:
```sparql
SELECT DISTINCT ?role WHERE { ?person uni:role ?role }
```
Then build a decision table:

| Role value                  | Should match? | `CONTAINS("professor")` matches? | Correct? |
|-----------------------------|---------------|----------------------------------|----------|
| Professor of CS             | YES           | YES                              | ✓        |
| Assistant Professor of CS   | YES           | YES                              | ✓        |
| Lecturer                    | NO            | NO                               | ✓        |
| Student                     | NO            | NO                               | ✓        |
| **Professorial Lecturer**   | **NO**        | **YES**                          | **✗ FALSE POSITIVE** |
| Visiting Professor          | YES           | YES                              | ✓        |
| Professor Emeritus          | YES           | YES                              | ✓        |

If any value creates a false positive, tighten the filter. Options:
- **Word-boundary regex**: `FILTER(REGEX(?role, "(^|\\s)[Pp]rofessor($|\\s)"))` — matches "professor" as a whole word bounded by start/end of string or whitespace, correctly excluding "professorial"
- **Explicit value list**: When the number of qualifying titles is small and known, use `FILTER(?role IN ("Professor of CS", "Assistant Professor of CS", ...))`
- **Negation list**: `FILTER(CONTAINS(LCASE(?role), "professor") && !CONTAINS(LCASE(?role), "lecturer"))` — fragile, prefer regex

The same enumerate-first principle applies to every string-based filter in any SPARQL query.

### Step 3: Trace the Affiliation Path to University

Discover how persons connect to universities. Common patterns:

**Pattern A — Department chain** (seed v01):
```
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
```

**Pattern B — Direct affiliation**:
```
?person uni:affiliatedWith ?uni .
```
or `uni:worksAt` directly to a University resource.

**Pattern C — Appointment resource**:
```
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?uni .
```

**Pattern D — Inverse containment**:
```
?uni uni:hasEmployee ?person .
```

**Pattern E — Teaching-course fallback**:
When `worksAt` may be absent, fall back to teaching path:
```
{ ?person uni:worksAt ?org . ?org uni:partOfUniversity ?uni . }
UNION
{ ?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni . }
```

**Discovery algorithm** (prioritized probe — use the first pattern that yields results):

```python
from rdflib import Graph, RDF, URIRef, Namespace

g = Graph().parse("/app/university_graph.ttl", format="turtle")
UNI = Namespace("http://university.org/ontology#")  # adapt to discovered prefix

unis = set(s for s, _, t in g.triples((None, RDF.type, UNI.University)))
persons = set(s for s, _, t in g.triples((None, RDF.type, UNI.Person)))

# Probe patterns in priority order. Each probe counts person→university links.
# Use the first pattern that returns results for ALL (or most) professors.
probes = [
    ("direct",       """?p a uni:Person . ?p ?pred ?u .
                        FILTER(?u IN ({unis}))"""),
    ("dept_chain",   """?p a uni:Person . ?p ?p1 ?mid . ?mid ?p2 ?u .
                        FILTER(?u IN ({unis}))"""),
    ("appointment",  """?p a uni:Person . ?p ?p1 ?appt . ?appt ?p2 ?u .
                        FILTER(?u IN ({unis}))"""),
    ("inverse",      """?p a uni:Person . ?u ?pred ?p .
                        FILTER(?u IN ({unis}))"""),
    ("teaching",     """?p a uni:Person . ?p ?p1 ?course . ?course ?p2 ?mid .
                        ?mid ?p3 ?u . FILTER(?u IN ({unis}))"""),
]

for name, pattern in probes:
    # Substitute unis and run count query via rdflib
    # (adapt to actual SPARQL engine)
    count = run_probe(pattern)  # SELECT (COUNT(*) AS ?c) WHERE { ... }
    if count > 0:
        print(f"Using pattern '{name}': {count} person→university links found")
        break
```

**Manual fallback** (if automated probing is unavailable):
```python
# For each Person, find paths to a University
for s in persons:
    for p, o in g.predicate_objects(s):
        if o in unis:
            print(f"Direct: {s} {p} -> {o}")
        elif isinstance(o, URIRef):
            for p2, o2 in g.predicate_objects(o):
                if o2 in unis:
                    print(f"Two-hop: {s} {p} -> {o} {p2} -> {o2}")
```

**Teaching-course fallback**: When the primary affiliation path is absent for some professors, add a UNION fallback:
```sparql
{ ?person uni:worksAt ?org . ?org uni:partOfUniversity ?uni . }
UNION
{ ?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni .
  FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . } }
```

### Step 4: Find the University Name Predicate

Universities have their name stored via some predicate. Common patterns:
- `uni:hasName` (seed v01)
- `rdfs:label`
- `foaf:name`
- `uni:name`

Check: `for s in unis: for p, o in g.predicate_objects(s): print(p, o)`

### Step 5: Construct the SPARQL Query

Assemble the query using discovered patterns:

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a uni:Person ;
            uni:hasName ?professorName ;
            # --- Professor identification ---
            # Pattern A: string role (use space-bounded regex to avoid false positives
            # like "Professorial Lecturer" — see Step 2 enumerate-first sub-step)
            uni:role ?role .
    FILTER(REGEX(?role, "(^|\\s)[Pp]rofessor($|\\s)"))

    # --- Affiliation path ---
    # Pattern A: department chain
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .

    # --- University name ---
    ?uni uni:hasName ?universityName .
}
ORDER BY ?professorName
```

**Note**: If the enumerate-first step (Step 2) confirms no false-positive values exist, `CONTAINS(LCASE(?role), "professor")` is also acceptable and slightly simpler. But word-boundary regex is the safer default.

**Critical: Use `SELECT DISTINCT`** to ensure exactly one row per professor-university pair, even when:
- A professor works at multiple departments within the same university
- A professor teaches multiple courses in the same department
- Multiple paths lead to the same university

### Step 6: Validate

Run the query against the graph using Python/rdflib to verify:

```python
from rdflib import Graph
g = Graph().parse("/app/university_graph.ttl", format="turtle")
with open("/app/solution.sparql") as f:
    query = f.read()
results = g.query(query)
for row in results:
    print(f"{row.professorName} | {row.universityName}")
print(f"Total rows: {len(list(g.query(query)))}")
```

Check:
- No students, lecturers, or staff appear
- All professors appear exactly once
- University names are human-readable strings (not URIs)
- **Enumerated all distinct values of the filtered property and verified each is correctly included/excluded** (see Step 2 enumerate-first sub-step)

## Handling UNION/Fallback Patterns

When the task specifies a primary path with a fallback (e.g., worksAt preferred, teaching-course as fallback when worksAt is absent), use:

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a uni:Person ;
            uni:hasName ?professorName .
    # Professor identification (adapt to discovered pattern)
    ?person uni:role ?role .
    FILTER(REGEX(?role, "(^|\\s)[Pp]rofessor($|\\s)"))

    # Affiliation: primary path UNION fallback
    {
        ?person uni:worksAt ?dept .
        ?dept uni:partOfUniversity ?uni .
    } UNION {
        ?person uni:teaches ?course .
        ?course uni:isTaughtIn ?dept .
        ?dept uni:partOfUniversity ?uni .
        FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
    }

    ?uni uni:hasName ?universityName .
}
```

## Handling Resource-Based Rank

When professors are identified via academic rank resources rather than string roles:

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a uni:Person ;
            uni:hasName ?professorName ;
            uni:hasAcademicRank ?rank .
    ?rank uni:rankLabel ?rankLabel .
    FILTER(REGEX(?rankLabel, "(^|\\s)[Pp]rofessor($|\\s)"))

    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
    ?uni uni:hasName ?universityName .
}
```

## Common Pitfalls

1. **Missing DISTINCT**: Without it, a professor teaching 2 courses in the same department yields 2 rows.
2. **Exact match on role**: `?role = "Professor"` misses "Assistant Professor of X". Use space-bounded regex `REGEX(?role, "(^|\\s)[Pp]rofessor($|\\s)")` (or `CONTAINS` only after enumerate-first validation).
3. **Hardcoded namespace**: Always read the `@prefix` from the Turtle file; the namespace URI may change.
4. **Wrong name predicate**: The university name might be `rdfs:label` instead of `uni:hasName`.
5. **Not filtering non-professors**: "Lecturer" and "Student" roles must be excluded — the CONTAINS("professor") filter handles this naturally.
6. **Over-matching with substring filters**: `CONTAINS(LCASE(?role), "professor")` matches "professorial" because "professor" is a substring of "professorial". This means "Professorial Lecturer" would be a false positive. Always enumerate distinct values first (see Step 2) and use space-bounded regex `REGEX(?role, "(^|\\s)[Pp]rofessor($|\\s)")` when near-miss titles are present. Note: `\b` word boundaries are not supported by all SPARQL engines (e.g., rdflib); use `(^|\\s)...($|\\s)` instead.

## Checklist Before Submitting

- [ ] Read the full Turtle file
- [ ] Identified the namespace prefix from `@prefix` declarations
- [ ] Identified how professor status is encoded (string role vs. resource rank)
- [ ] Traced the affiliation path from Person to University
- [ ] Found the university name predicate
- [ ] Used `SELECT DISTINCT` for cardinality
- [ ] Used regex or CONTAINS (after enumerate-first validation) for professor matching
- [ ] **Enumerated all distinct values of the filtered property; built decision table; verified no false positives**
- [ ] Validated query against the graph with rdflib
- [ ] Saved query to `/app/solution.sparql`
