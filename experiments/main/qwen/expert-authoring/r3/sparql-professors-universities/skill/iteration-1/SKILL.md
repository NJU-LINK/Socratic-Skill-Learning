---
name: sparql-professors-universities
description: >
  Write a SPARQL query that retrieves professor names and their affiliated
  university names from a Turtle knowledge graph. The graph contains persons
  with academic roles (professors, lecturers, students, staff), organizational
  units (departments, universities), and relationships between them. The query
  must correctly identify qualifying professors, trace the affiliation path to
  the university, and return exactly one row per professor-university pair.
---

# SPARQL Professors–Universities Query

## Task Summary

Given a Turtle file at `/app/university_graph.ttl`, produce a SPARQL query
saved to `/app/solution.sparql` that returns two variables:

- `?professorName` — the name of each qualifying professor
- `?universityName` — the name of the university they work in

## Exploration Phase (mandatory)

Before writing any query, explore the graph to discover its actual ontology
and data. Use Python with `rdflib` (pre-installed):

```python
import rdflib
g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# 1. Discover all predicates
preds = sorted(set(str(p) for s, p, o in g))
for p in preds: print(p)

# 2. Discover all rdf:type values (classes)
from rdflib import RDF
classes = sorted(set(str(o) for s, p, o in g.triples((None, RDF.type, None))))
for c in classes: print(c)

# 3. List all role/rank values (see "Professor Identification" below)
```

This step reveals the actual predicate names, class names, role strings, and
affiliation structure that the query must target.

## Step 1 — Identify Qualifying Professors

### Decision rule: role-based identification

The most common representation uses a **string-valued role predicate** (e.g.,
`uni:role`). Qualifying professors have role strings that contain the word
"Professor" (in various forms: "Professor of X", "Assistant Professor of X",
"Associate Professor of X", "Full Professor of X", etc.).

**Exclusions**: Roles like "Lecturer", "Student", "Staff", "Researcher" do NOT
qualify, even if those persons also work at departments.

**Filter pattern** (case-insensitive for robustness):

```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
```

> Use `LCASE` to guard against variants that may use different casing.
> `CONTAINS` catches "Professor", "Assistant Professor", "Associate Professor",
> "Full Professor", and similar compounds while excluding "Lecturer" etc.

### Variant: rank-based identification

Some variants may represent academic rank as a **resource** rather than a
string. Look for predicates like `uni:hasAcademicRank` pointing to a resource
with a `uni:rankLabel`. In that case:

```sparql
?professor uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?role .
FILTER(CONTAINS(LCASE(?role), "professor"))
```

### Verification after identification

After building the filter, run a diagnostic count:

```python
results = g.query("""
  PREFIX uni: <http://university.org/ontology#>
  SELECT ?name ?role
  WHERE {
    ?p uni:hasName ?name ;
       uni:role ?role .
    FILTER(CONTAINS(LCASE(?role), "professor"))
  }
""")
for r in results: print(r)
```

Check that:
- All expected professors appear
- No lecturers, students, or staff appear
- The count matches expectations

## Step 2 — Trace the Affiliation Path to University

### Decision rule: follow the organization chain

The typical path is:

```
Person --[worksAt]--> Department --[partOfUniversity]--> University
```

But always verify by exploring the actual predicates. Common variations:

| Variant | Path |
|---------|------|
| Direct affiliation | `Person --[affiliatedWith]--> University` |
| Two-hop (seed) | `Person --[worksAt]--> Dept --[partOfUniversity]--> University` |
| Longer chain | `Person --[worksAt]--> Dept --[partOf]--> Faculty --[partOf]--> University` |
| Inverse containment | `University --[hasDepartment]--> Dept --[hasMember]--> Person` |

**Discovery query** — find which predicates connect a Person to a University:

```python
# Get all predicates outgoing from a known professor
for s, p, o in g.triples((professor_uri, None, None)):
    print(f"  {p} -> {o}")
```

Then check what connects the intermediate node to the university:

```python
# From the department, find outgoing links
for s, p, o in g.triples((dept_uri, None, None)):
    print(f"  {p} -> {o}")
```

### University name predicate

Usually `uni:hasName` on the University resource. Verify by checking:

```python
for s, p, o in g.triples((university_uri, None, None)):
    print(f"  {p} -> {o}")
```

## Step 3 — Assemble the Query

### Template (two-hop via department — most common):

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
```

### Template (direct affiliation variant):

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:hasName ?professorName ;
             uni:role ?role ;
             uni:affiliatedWith ?university .
  ?university uni:hasName ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
```

### Template (rank-resource variant):

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:hasName ?professorName ;
             uni:hasAcademicRank ?rank ;
             uni:worksAt ?dept .
  ?rank uni:rankLabel ?rankLabel .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  FILTER(CONTAINS(LCASE(?rankLabel), "professor"))
}
```

## Step 4 — Cardinality & Deduplication

**Always use `SELECT DISTINCT`** to guard against duplicate rows caused by:

- A professor teaching multiple courses (if `teaches` is in the pattern)
- A department belonging to multiple organizational parents
- Multiple role assertions for the same person

The invariant: **exactly one row per (professor, university) pair** with
exactly the two requested projection variables.

## Step 5 — Save and Verify

1. Write the query to `/app/solution.sparql`
2. Run it against the graph and inspect results:

```python
import rdflib
g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

with open("/app/solution.sparql") as f:
    query = f.read()

results = g.query(query)
print(f"Total rows: {len(results)}")
for row in results:
    print(f"  {row[0]}  ->  {row[1]}")
```

3. Verify:
   - [ ] Only professors appear (no lecturers, students, staff)
   - [ ] Every professor has a university name
   - [ ] No duplicate rows
   - [ ] Variables are named `?professorName` and `?universityName`
   - [ ] Query is valid SPARQL and parses without errors

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Forgetting `CONTAINS` and using exact match `?role = "Professor"` | Use `CONTAINS(LCASE(?role), "professor")` to catch "Assistant Professor", "Professor of X", etc. |
| Including lecturers or students | Filter requires "professor" substring |
| Missing `DISTINCT` | Always include `DISTINCT` in SELECT |
| Hardcoding namespace prefix | Extract from the Turtle file's `@prefix` declarations |
| Wrong affiliation path | Explore the graph first; follow actual predicates |
| Using `STRSTARTS` instead of `CONTAINS` | "Assistant Professor" starts with "Assistant", not "Professor" — use `CONTAINS` |
| Projecting extra variables | Only select `?professorName` and `?universityName` |

## Prefix Handling

Always extract the prefix from the Turtle file. The most common prefix is:

```
PREFIX uni: <http://university.org/ontology#>
```

But variants may use different namespace URIs. Read the `@prefix` lines from
the file:

```python
with open("/app/university_graph.ttl") as f:
    for line in f:
        if line.startswith("@prefix"):
            print(line.strip())
```

Use the discovered prefix in your query.
