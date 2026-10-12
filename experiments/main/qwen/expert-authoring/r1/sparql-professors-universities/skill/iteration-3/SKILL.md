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

# 1. Extract prefixes from the file
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

# 4. Role-like values with their RDF type (literal vs URI)
print("\n=== ROLE VALUES (with type) ===")
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
    val = row[1]
    kind = "LITERAL" if isinstance(val, Literal) else ("URI" if isinstance(val, URIRef) else "OTHER")
    print(f"  {row[0]}  =>  {val}  [{kind}]")

# 5. Rank-resource pattern: check if roles are resources with labels
print("\n=== RANK-RESOURCE PATTERN ===")
rank_q = """
SELECT DISTINCT ?rankPred ?labelPred ?labelVal WHERE {
    ?person ?rankPred ?rank .
    ?rank ?labelPred ?labelVal .
    FILTER(isURI(?rank))
    FILTER(
        CONTAINS(LCASE(STR(?rankPred)), "rank") ||
        CONTAINS(LCASE(STR(?rankPred)), "title") ||
        CONTAINS(LCASE(STR(?rankPred)), "position")
    )
    FILTER(!CONTAINS(LCASE(STR(?rankPred)), "work"))
}
"""
rank_rows = list(g.query(rank_q))
if rank_rows:
    for row in rank_rows:
        print(f"  person --{row[0]}--> rank --{row[1]}--> \"{row[2]}\"")
else:
    print("  (none detected — roles are likely string literals)")

# 6. Person-to-org affiliation links
print("\n=== AFFILIATION LINKS ===")
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

# 7. Name predicates
print("\n=== NAME PREDICATES ===")
for row in g.query("""
    SELECT DISTINCT ?pred WHERE {
        ?s ?pred ?name .
        FILTER(CONTAINS(LCASE(STR(?pred)), "name") ||
               CONTAINS(LCASE(STR(?pred)), "label"))
        FILTER(isLiteral(?name))
    }
"""):
    print(f"  {row[0]}")

# 8. Org-to-university hierarchy (containment or membership, not teaching)
print("\n=== ORG-TO-UNIVERSITY LINKS ===")
for row in g.query("""
    SELECT DISTINCT ?orgType ?pred ?uniType WHERE {
        ?org ?pred ?uni .
        ?org a ?orgType .
        ?uni a ?uniType .
        FILTER(CONTAINS(LCASE(STR(?uniType)), "university"))
        FILTER(!CONTAINS(LCASE(STR(?orgType)), "person"))
        FILTER(!CONTAINS(LCASE(STR(?orgType)), "course"))
        FILTER(!CONTAINS(LCASE(STR(?pred)), "type"))
        FILTER(!CONTAINS(LCASE(STR(?pred)), "taught"))
        FILTER(!CONTAINS(LCASE(STR(?pred)), "enrolled"))
    }
"""):
    print(f"  {row[0]} --{row[1]}--> {row[2]}")

# 9. Check for persons who have role but NO organizational affiliation
print("\n=== PERSONS WITH ROLE BUT NO AFFILIATION ===")
missing = list(g.query("""
    SELECT ?name ?role WHERE {
        ?person ?rolePred ?role .
        FILTER(CONTAINS(LCASE(STR(?rolePred)), "role") ||
               CONTAINS(LCASE(STR(?rolePred)), "rank"))
        FILTER NOT EXISTS {
            ?person ?workPred ?x .
            FILTER(CONTAINS(LCASE(STR(?workPred)), "work"))
        }
        FILTER NOT EXISTS {
            ?person ?teachPred ?x .
            FILTER(CONTAINS(LCASE(STR(?teachPred)), "teach"))
        }
        OPTIONAL { ?person ?namePred ?name . FILTER(CONTAINS(LCASE(STR(?namePred)), "name")) }
    }
"""))
if missing:
    print(f"  {len(missing)} person(s) have a role but no worksAt/teaches:")
    for r in missing:
        print(f"    {r[0]}  (role: {r[1]})")
    print("  These are likely students/staff — not candidates for fallback.")
else:
    print("  (none — all persons with roles have worksAt or teaches)")

# 10. Check for professors who have teaches but NO worksAt (fallback candidates)
print("\n=== TEACHES-ONLY PROFESSORS (fallback candidates) ===")
fb = list(g.query("""
    SELECT ?name WHERE {
        ?person ?rolePred ?role .
        FILTER(CONTAINS(LCASE(STR(?rolePred)), "role") ||
               CONTAINS(LCASE(STR(?rolePred)), "rank"))
        FILTER(CONTAINS(STR(?role), "Professor") || CONTAINS(LCASE(STR(?role)), "professor"))
        FILTER NOT EXISTS {
            ?person ?workPred ?x .
            FILTER(CONTAINS(LCASE(STR(?workPred)), "work"))
        }
        ?person ?teachPred ?course .
        FILTER(CONTAINS(LCASE(STR(?teachPred)), "teach"))
        OPTIONAL { ?person ?namePred ?name . FILTER(CONTAINS(LCASE(STR(?namePred)), "name")) }
    }
"""))
if fb:
    print(f"  {len(fb)} professor(s) use teaches but not worksAt — UNION fallback needed!")
    for r in fb:
        print(f"    {r[0]}")
else:
    print("  (none — all professors have worksAt)")

print("\nDone. Use these discoveries to build your query.")
PYEOF
```

---

## Step 2 — Identify Qualifying Professor Roles

From the Step 1 output, examine **ROLE VALUES** and **RANK-RESOURCE PATTERN**.

### Case A: Roles are string literals (most common)

Look for values like `"Professor of X"`, `"Assistant Professor of X"`.

- **Filter:** `FILTER(CONTAINS(?role, "Professor"))`
- If casing varies: `FILTER(CONTAINS(LCASE(?role), "professor"))`

### Case B: Roles are URI resources with labels

The RANK-RESOURCE PATTERN section will show something like:
```
person --uni:hasAcademicRank--> rank --uni:rankLabel--> "Professor"
```

- **Filter:** Join the rank resource and filter its label:
  `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?label .`
  `FILTER(CONTAINS(?label, "Professor"))`

### Case C: Exact enumeration needed

If role values are few and don't share a common substring, list them explicitly:
`FILTER(?role IN ("Full Professor", "Assistant Professor"))`

**Always include** anything with "Professor" in the name. **Always exclude** "Lecturer", "Student", "Staff", "Researcher", etc.

---

## Step 3 — Trace the Affiliation Path

From the Step 1 output, examine **AFFILIATION LINKS** and **ORG-TO-UNIVERSITY LINKS**.

### Common path patterns

| Pattern | When to use |
|---|---|
| `?person P1 ?dept . ?dept P2 ?uni . ?uni Pname ?universityName` | ORG-TO-UNIVERSITY shows Department --P2--> University |
| `?person P1 ?uni . ?uni Pname ?universityName` | AFFILIATION LINKS shows worksAt --> University directly |
| `?person Pteach ?course . ?course P3 ?dept . ?dept P2 ?uni` | Fallback when some persons lack worksAt |

### Fallback needed?

If **TEACHES-ONLY PROFESSORS (fallback candidates)** shows entries, you need a
UNION query that tries the preferred worksAt path first, then falls back to
the teaching path. See Step 4 for the UNION template.

---

## Step 4 — Construct the Query

### Key robustness rules

1. **Do NOT require `a uni:Person`** — the role filter + affiliation chain suffices.
2. **Always use `DISTINCT`** to prevent duplicates from one-to-many relations.
3. **Project exactly two variables:** `?professorName` and `?universityName`.
4. **Use the exact prefix IRI** from Step 1, not a guess.
5. **Both name variables must be bound** via their respective name predicates.
6. **Use `ORDER BY`** for deterministic output.

### Template A: String roles + dept→university path (standard)

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

### Template B: Direct person→university (no department intermediary)

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

### Template C: Resource-based academic rank

Use when RANK-RESOURCE PATTERN showed person→rank→label:

```sparql
PREFIX uni: <NAMESPACE_FROM_STEP_1>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:hasAcademicRank ?rank ;
          uni:worksAt ?dept .
  ?rank uni:rankLabel ?label .
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  FILTER(CONTAINS(?label, "Professor"))
}
ORDER BY ?professorName
```

### Template D: Heterogeneous affiliation (worksAt with teaching fallback)

Use when **TEACHES-ONLY PROFESSORS (fallback candidates)** shows entries,
meaning some professors have `worksAt` but others only have `teaches`:

```sparql
PREFIX uni: <NAMESPACE_FROM_STEP_1>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:hasName ?professorName ;
          uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
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
}
ORDER BY ?professorName
```

**UNION safety rules:**
- Put `FILTER` BEFORE the UNION (applies to both branches).
- Bind `?professorName` and `?uni uni:hasName ?universityName` OUTSIDE the UNION.
- Each UNION branch must bind the same variables (`?dept`, `?uni`).
- DISTINCT eliminates duplicates from professors appearing in both branches.

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

# Cross-check: count qualifying professors (handles both string and resource roles)
from rdflib import Literal as L

# Method 1: Direct string match on role value
count_q1 = """
SELECT (COUNT(DISTINCT ?p) AS ?c) WHERE {
    ?p ?rp ?rv .
    FILTER(CONTAINS(LCASE(STR(?rp)), "role"))
    FILTER(CONTAINS(STR(?rv), "Professor") || CONTAINS(LCASE(STR(?rv)), "professor"))
}
"""
c1 = int(list(g.query(count_q1))[0][0])

# Method 2: Resource-based rank with label
count_q2 = """
SELECT (COUNT(DISTINCT ?p) AS ?c) WHERE {
    ?p ?rp ?rank .
    ?rank ?lp ?lv .
    FILTER(CONTAINS(LCASE(STR(?rp)), "rank"))
    FILTER(CONTAINS(LCASE(STR(?lp)), "label") || CONTAINS(LCASE(STR(?lp)), "name"))
    FILTER(CONTAINS(STR(?lv), "Professor") || CONTAINS(LCASE(STR(?lv)), "professor"))
}
"""
c2 = int(list(g.query(count_q2))[0][0])

expected = max(c1, c2)
print(f"\nExpected professor count: {expected} (string:{c1}, resource:{c2})")
assert len(rows) == expected, f"Row count {len(rows)} != expected {expected}"
print("ALL CHECKS PASSED!")
PYEOF
```

3. If assertions fail, **fix and re-run** — do not submit a failing query.

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
| Forgetting to bind `?professorName` | Include `?person <namePred> ?professorName` in the WHERE clause |
| Role is a resource, not a string | Check RANK-RESOURCE PATTERN in Step 1 output; use Template C |
| Some professors lack worksAt | Check TEACHES-ONLY PROFESSORS section; use Template D (UNION) |
| FILTER inside only one UNION branch | Put FILTER before/after UNION so it applies to both branches |
