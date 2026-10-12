---
name: sparql-professors-universities
description: >
  Write a SPARQL query that returns the names of all professors (full and
  assistant professors, excluding lecturers/students/staff) and the universities
  they work at, from a Turtle knowledge graph. The agent must explore the graph
  to discover the actual ontology, identify qualifying academic roles, trace the
  person-to-university affiliation chain, and produce a correct, deduplicated
  result saved to /app/solution.sparql.
---

# SPARQL Professors & Universities

## Task Summary

Given a Turtle file at `/app/university_graph.ttl` containing a knowledge graph
of universities, departments, people, courses, and roles, produce a SPARQL query
(saved to `/app/solution.sparql`) that returns two variables:

- `?professorName` — the name of each qualifying professor
- `?universityName` — the name of the university that professor works at

Exactly one row per professor–university pair. No duplicates.

---

## Step-by-Step Strategy

### Step 1 — Explore the Ontology and Data

Before writing any query, **read the TTL file** and extract:

1. **All class types** (`?s a ?class`) — find what entity types exist.
2. **All predicates** (`?s ?p ?o`) — understand the vocabulary.
3. **All role values** — list every distinct value of the role property to
   classify which are professors and which are not.

```python
from rdflib import Graph
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# Distinct role values
for row in g.query("SELECT DISTINCT ?r WHERE { ?s <ROLE_PREDICATE> ?r } ORDER BY ?r"):
    print(row[0])
```

### Step 2 — Identify Qualifying Professor Roles

**Decision rule (string-based roles):**
If roles are stored as string literals on a predicate like `uni:role`:
- A person qualifies if their role string **contains "Professor"** (covers
  "Professor of X", "Assistant Professor of X", "Associate Professor of X", etc.)
- Exclude strings that do NOT contain "Professor" (e.g., "Lecturer", "Student",
  "Staff", "Researcher").
- Use SPARQL: `FILTER(CONTAINS(?role, "Professor"))`

**Decision rule (rank-resource roles):**
If roles are modeled as resources linked via `uni:hasAcademicRank` with a
`uni:rankLabel`, apply the same CONTAINS logic on the label string.

**Edge cases to watch for:**
- "Professor Emeritus" — still contains "Professor", qualifies.
- "Visiting Professor" — contains "Professor", qualifies (unless spec says otherwise).
- Near-miss strings like "Proffesor" or "professor" (lowercase) — check the
  actual data for casing before committing to the filter.
- If case is uncertain, use `FILTER(CONTAINS(LCASE(?role), "professor"))`.

### Step 3 — Trace the Affiliation Path

Determine how a person is linked to a university name. **Always verify by
reading the TTL**; common patterns include:

| Pattern | SPARQL Path |
|---------|-------------|
| Direct | `?person uni:worksAt ?uni . ?uni uni:hasName ?universityName` |
| Via department | `?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni . ?uni uni:hasName ?universityName` |
| Via course (fallback) | `?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni . ?uni uni:hasName ?universityName` |
| Inverse containment | `?uni uni:hasDepartment ?dept . ?dept uni:hasMember ?person` |

**Priority rule:** Prefer the `worksAt` path when present. Use the teaching
path only as a fallback when a person lacks `worksAt` but has `teaches`. If
both must be supported, use `OPTIONAL` or `UNION`.

**Discover the chain empirically:**
```python
# Find how persons connect to universities
for row in g.query("""
    PREFIX uni: <http://university.org/ontology#>
    SELECT ?person ?dept ?uni WHERE {
        ?person uni:worksAt ?dept .
        ?dept uni:partOfUniversity ?uni .
    } LIMIT 5
"""):
    print(row)
```

### Step 4 — Construct the Query

Template (adapt predicates and path to discovered ontology):

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  FILTER(CONTAINS(?role, "Professor"))
}
ORDER BY ?professorName
```

**Key points:**
- Always use `DISTINCT` to prevent duplicate rows from multiple teachings,
  courses, or other one-to-many relations.
- Use `ORDER BY` for deterministic output.
- Match the exact PREFIX IRI from the TTL file (read it, don't guess).
- Project **only** `?professorName` and `?universityName` — no extra variables.

### Step 5 — Save and Self-Verify

1. **Save** the query to `/app/solution.sparql`.

2. **Verify** by running it with rdflib:

```python
from rdflib import Graph

g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

with open('/app/solution.sparql') as f:
    query = f.read()

results = g.query(query)
print(f"Columns: {[str(v) for v in results.vars]}")
print(f"Row count: {len(results)}")
for row in results:
    print(f"  {row[0]}  |  {row[1]}")
```

3. **Check:**
   - `?professorName` and `?universityName` are the only variables.
   - No lecturers, students, or staff appear.
   - Every expected professor appears exactly once.
   - University names (not URIs) are returned.
   - Row count matches the number of qualifying professors in the data.

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Matching "Lecturer" or "Student" | Verify filter on actual role strings |
| Missing "Assistant Professor" | Use `CONTAINS(?role, "Professor")`, not exact match |
| Duplicate rows from `teaches` | Use `SELECT DISTINCT` |
| Returning URI instead of name | Follow `uni:hasName` on the university resource |
| Hard-coding a prefix IRI | Read the actual `@prefix` from the TTL |
| Wrong affiliation path | Trace empirically; don't assume direct link |
| Case-sensitive miss | Use `LCASE` if role casing varies |
| Forgetting to handle rank-resource variants | Check if roles are strings or resources |

---

## Variation Handling Checklist

Before finalizing the query, answer these from the data:

- [ ] What predicate holds the role? (`uni:role`, `uni:hasAcademicRank`, other?)
- [ ] Are role values strings or resources?
- [ ] What string(s) identify professors? (contains "Professor", exact labels?)
- [ ] What is the person → university path? (direct, via dept, via course?)
- [ ] Is the university name on `uni:hasName`, `rdfs:label`, or other?
- [ ] Are there any one-to-many edges that could cause duplicates?
- [ ] Does the data use a different namespace than `uni:`?
