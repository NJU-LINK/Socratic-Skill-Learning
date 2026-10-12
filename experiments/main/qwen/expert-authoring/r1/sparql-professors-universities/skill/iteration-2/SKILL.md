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

Given a Turtle file at `/app/university_graph.ttl`, produce a SPARQL query
(saved to `/app/solution.sparql`) that returns exactly two variables:

- `?professorName` — the name of each qualifying professor
- `?universityName` — the name of the university they work at

One row per professor. No duplicates. No lecturers, students, or staff.

---

## Step 1 — Discover the Ontology (MUST DO FIRST)

**Do NOT guess predicates, types, or role values. Always discover them from the data.**

Run this exploration script to learn everything about the graph in one shot:

```bash
python3 << 'PYEOF'
from rdflib import Graph, URIRef, Literal

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# 1. Extract the prefix namespace from the file
with open("/app/university_graph.ttl") as f:
    for line in f:
        line = line.strip()
        if line.startswith("@prefix"):
            print("PREFIX:", line)
        elif line and not line.startswith("#"):
            break

# 2. All predicates
print("\n=== ALL PREDICATES ===")
for row in g.query("SELECT DISTINCT ?p WHERE { ?s ?p ?o } ORDER BY ?p"):
    print(f"  {row[0]}")

# 3. All type values
print("\n=== ALL TYPES ===")
for row in g.query("SELECT DISTINCT ?t WHERE { ?s a ?t } ORDER BY ?t"):
    print(f"  {row[0]}")

# 4. All role-like values (try common predicates)
print("\n=== ROLE VALUES ===")
for row in g.query("""
    SELECT DISTINCT ?pred ?val WHERE {
        ?s ?pred ?val .
        FILTER(
            CONTAINS(LCASE(STR(?pred)), "role") ||
            CONTAINS(LCASE(STR(?pred)), "rank") ||
            CONTAINS(LCASE(STR(?pred)), "title") ||
            CONTAINS(LCASE(STR(?pred)), "position")
        )
    } ORDER BY ?pred ?val
"""):
    print(f"  {row[0]}  =>  {row[1]}")

# 5. Sample person-to-org links
print("\n=== AFFILIATION LINKS (sample) ===")
for row in g.query("""
    SELECT DISTINCT ?pred ?objType WHERE {
        ?person ?pred ?obj .
        ?obj a ?objType .
        FILTER(CONTAINS(LCASE(STR(?pred)), "work") ||
               CONTAINS(LCASE(STR(?pred)), "employ") ||
               CONTAINS(LCASE(STR(?pred)), "affil") ||
               CONTAINS(LCASE(STR(?pred)), "teach") ||
               CONTAINS(LCASE(STR(?pred)), "member") ||
               CONTAINS(LCASE(STR(?pred)), "partof"))
    } ORDER BY ?pred
"""):
    print(f"  {row[0]}  =>  {row[1]}")

# 6. University name predicates
print("\n=== NAME PREDICATES ===")
for row in g.query("""
    SELECT DISTINCT ?pred WHERE {
        ?uni ?pred ?name .
        FILTER(CONTAINS(LCASE(STR(?pred)), "name") ||
               CONTAINS(LCASE(STR(?pred)), "label"))
    }
"""):
    print(f"  {row[0]}")

# 7. How orgs connect to universities
print("\n=== ORG-TO-UNIVERSITY LINKS ===")
for row in g.query("""
    SELECT DISTINCT ?pred WHERE {
        ?dept ?pred ?uni .
        ?uni a ?t .
        FILTER(CONTAINS(LCASE(STR(?t)), "university"))
    }
"""):
    print(f"  {row[0]}")

print("\nDone. Use these discoveries to build your query.")
PYEOF
```

This script answers every question you need before writing the query: the namespace, the role predicate, the role values, the affiliation path, and the name predicate.

---

## Step 2 — Identify Qualifying Professor Roles

From the Step 1 output, look at **ROLE VALUES** and classify each as professor or non-professor.

**Decision rules:**

| Role representation | How to detect professors | SPARQL filter |
|---|---|---|
| String literal (e.g., `"Professor of X"`, `"Assistant Professor of X"`) | String contains "Professor" | `FILTER(CONTAINS(?role, "Professor"))` |
| Lowercase or mixed case strings | Case-insensitive match | `FILTER(CONTAINS(LCASE(?role), "professor"))` |
| Resource-based rank (`uni:hasAcademicRank ?rank` with `uni:rankLabel ?label`) | Label contains "Professor" | Join rank resource, filter on label |
| Enumerated exact labels | Explicit value list | `FILTER(?role IN ("Professor", "Assistant Professor", ...))` |

**Include:** "Professor of X", "Assistant Professor of X", "Associate Professor of X", "Professor Emeritus", etc. — anything with "Professor" in the string.

**Exclude:** "Lecturer", "Student", "Staff", "Researcher", "Postdoc" — anything without "Professor".

---

## Step 3 — Trace the Affiliation Path

From the Step 1 output, look at **AFFILIATION LINKS** and **ORG-TO-UNIVERSITY LINKS** to build the path. Common patterns:

| Pattern | SPARQL |
|---|---|
| Person → dept → university | `?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni . ?uni uni:hasName ?universityName` |
| Person → university directly | `?person uni:worksAt ?uni . ?uni uni:hasName ?universityName` |
| Person → course → dept → university (fallback) | `?person uni:teaches ?c . ?c uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni . ?uni uni:hasName ?universityName` |
| Inverse containment | `?uni uni:hasDepartment ?dept . ?dept uni:hasMember ?person . ?uni uni:hasName ?universityName` |

**Priority:** Prefer `worksAt` when present. Use `teaches` only as fallback via `OPTIONAL`/`UNION` when some professors lack `worksAt`.

---

## Step 4 — Construct the Query

**Key robustness rules:**

1. **Do NOT require `a uni:Person`** unless you've confirmed every qualifying person has that type AND no other type is used. The role filter + affiliation chain is sufficient to identify professors. Requiring a specific type is a common failure point on variants.

2. **Always use `DISTINCT`** to prevent duplicates from one-to-many relations (teaches multiple courses, etc.).

3. **Project exactly two variables:** `?professorName` and `?universityName`. Nothing else.

4. **Use the exact prefix IRI** discovered in Step 1, not a guess.

5. **Use `ORDER BY`** for deterministic output.

**Template** (adapt predicates to what Step 1 discovered):

```sparql
PREFIX uni: <NAMESPACE_FROM_STEP_1>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  FILTER(CONTAINS(?role, "Professor"))
}
ORDER BY ?professorName
```

**If the affiliation is direct** (person → university, no department):

```sparql
PREFIX uni: <NAMESPACE_FROM_STEP_1>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?uni .
  ?uni uni:hasName ?universityName .
  FILTER(CONTAINS(?role, "Professor"))
}
ORDER BY ?professorName
```

**CRITICAL:** Both `?professorName` and `?universityName` must be bound via their respective name predicates. The person and the university each need their own name lookup.

---

## Step 5 — Save and Verify

1. **Save** the query to `/app/solution.sparql`.

2. **Verify immediately** by running this:

```bash
python3 << 'PYEOF'
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

with open("/app/solution.sparql") as f:
    query = f.read()

results = g.query(query)
vars_list = [str(v) for v in results.vars]
rows = [(str(r[0]), str(r[1])) for r in results]

print(f"Variables: {vars_list}")
print(f"Row count: {len(rows)}")
print(f"Unique rows: {len(set(rows))}")
print()
for prof, uni in sorted(rows):
    print(f"  {prof}  |  {uni}")

# Validate
assert vars_list == ["professorName", "universityName"], f"Wrong variables: {vars_list}"
assert len(rows) > 0, "No results!"
assert len(rows) == len(set(rows)), f"Duplicates: {len(rows)} rows but {len(set(rows))} unique"
print("\nAll checks passed!")
PYEOF
```

3. **Cross-check the results against the TTL data:**
   - Count people whose role contains "Professor" in the TTL — does it match the row count?
   - Are any "Lecturer", "Student", or "Staff" names in the results? (They should not be.)
   - Are university names (human-readable strings) returned, not URIs?

---

## Quick Reference: Common Pitfalls

| Pitfall | Fix |
|---|---|
| Hard-coding `a uni:Person` type constraint | Omit the type; rely on role filter + affiliation path |
| Missing "Assistant Professor" | Use `CONTAINS(?role, "Professor")`, not exact match |
| Duplicate rows from `teaches` multi-valued | Use `SELECT DISTINCT` |
| Returning URI instead of name | Follow the name predicate (`uni:hasName`, `rdfs:label`, etc.) |
| Guessing the prefix IRI | Extract it from the `@prefix` line in the TTL file |
| Wrong affiliation chain depth | Discover it from Step 1 exploration, don't assume |
| Case-sensitive role filter missing matches | Use `LCASE` if casing varies |
| Placeholder in exploration code | Use the concrete script in Step 1 |
| Forgetting to bind `?professorName` | Include `?person <namePred> ?professorName` in the WHERE clause |
| University name re-used as person name | Use separate name lookups for person and university |
