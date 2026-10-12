---
name: sparql-professors-universities
description: >
  Build SPARQL queries that retrieve professor names and their affiliated university names
  from a university knowledge graph. Covers professor identification via role strings or
  academic-rank resources, multi-hop affiliation traversal to universities, and
  deduplication to guarantee one row per professor-university pair.
---

# SPARQL Professors–Universities

## Problem Statement

Given an RDF/Turtle knowledge graph describing universities, departments, and people,
write a SPARQL query that returns **all qualifying professors** together with the **name
of the university they work at**. The result must contain exactly two variables
(`?professorName`, `?universityName`) and exactly one row per professor–university pair.

## Ontology Discovery Procedure

When facing a new variant, **always run these probe queries first** to determine which
pattern template applies. Do not guess predicates from the namespace prefix alone.

### Probe 1: Extract the namespace prefix

```bash
grep '@prefix' /app/university_graph.ttl
```

Identify the base namespace (e.g., `uni:` → `http://university.org/ontology#`).

### Probe 2: Find all predicates used on Person instances

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
SELECT DISTINCT ?predicate WHERE {
  ?person a uni:Person .
  ?person ?predicate ?object .
}
```

This reveals how roles/ranks are stored (`uni:role`, `uni:hasAcademicRank`, etc.)
and how affiliation is expressed (`uni:worksAt`, `uni:affiliatedWith`, etc.).

### Probe 3: Inspect role/rank values

If a string-valued role predicate was found (e.g., `uni:role`):

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
SELECT DISTINCT ?role WHERE { ?person uni:role ?role }
```

This shows exact role strings — check for case variations, abbreviations, and
near-miss values (e.g., "Professor Emeritus", "Prof.", "professor").

If a resource-valued rank predicate was found (e.g., `uni:hasAcademicRank`):

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
SELECT DISTINCT ?rank ?label WHERE {
  ?person uni:hasAcademicRank ?rank .
  OPTIONAL { ?rank uni:rankLabel ?label }
  OPTIONAL { ?rank rdfs:label ?label }
}
```

### Probe 4: Trace the affiliation path from Person to University

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
# One-hop paths
SELECT DISTINCT ?p1 WHERE {
  ?person a uni:Person .
  ?person ?p1 ?uni .
  ?uni a uni:University .
}
```

If no one-hop path exists, try two-hop:

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
SELECT DISTINCT ?p1 ?p2 WHERE {
  ?person a uni:Person .
  ?person ?p1 ?mid .
  ?mid ?p2 ?uni .
  ?uni a uni:University .
}
```

This reveals the exact predicate chain (e.g., `worksAt → partOfUniversity`).

### Probe 5: Find the name predicate for universities

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>
SELECT DISTINCT ?pred ?name WHERE {
  ?uni a uni:University .
  ?uni ?pred ?name .
  FILTER(isLiteral(?name))
}
LIMIT 10
```

This reveals whether names use `uni:hasName`, `rdfs:label`, `foaf:name`, etc.

## Core SPARQL Pattern Template

After running the discovery probes, instantiate this template:

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # --- Step 1: Identify professors ---
  ?person  :namePredicate  ?professorName .
  # Use the role/rank predicate and filter discovered in Probes 2-3.
  # ROBUST DEFAULT (case-insensitive):
  ?person  :rolePredicate  ?role .
  FILTER( REGEX(?role, "professor", "i") )

  # --- Step 2: Traverse affiliation to university ---
  # Use the predicate chain discovered in Probe 4.
  ?person  :affiliationPredicate  ?intermediate .
  ?intermediate :containmentPredicate  ?uni .

  # --- Step 3: Retrieve university name ---
  # Use the name predicate discovered in Probe 5.
  ?uni     :namePredicate  ?universityName .
}
```

## Variation Axes

### Axis 1 — Professor Identification Semantics

**What varies:** How qualifying professors are represented and distinguished from
non-target roles (lecturers, students, staff, postdocs, etc.).

| Variant pattern | SPARQL handling |
|---|---|
| String-valued role containing "Professor" (seed) | `FILTER(REGEX(?role, "professor", "i"))` — case-insensitive |
| Abbreviated forms ("Prof.", "Asst. Prof.") | `FILTER(REGEX(?role, "prof", "i"))` catches both "Professor" and "Prof." |
| Resource-valued rank with label | `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?label . FILTER(REGEX(?label, "professor", "i"))` |
| Explicit class-based typing | `?person a uni:FullProfessor` or UNION of professor subclasses |
| Near-miss roles ("Professor Emeritus", "Visiting Professor") | REGEX("professor", "i") catches these; add explicit exclusion if task requires |

**Critical: case sensitivity.** SPARQL `CONTAINS` is case-sensitive. Always prefer
`REGEX(?var, "professor", "i")` or `CONTAINS(LCASE(?var), "professor")` to handle
variants that use lowercase or mixed-case role strings.

**Verified:** In v01, `CONTAINS(?role, "Professor")` works because all role strings
use title case. But a variant with `"professor of biology"` would be silently missed
by case-sensitive CONTAINS — confirmed by direct test where lowercase `"professor of
testing"` was excluded by `CONTAINS(?r, "Professor")` but included by
`REGEX(?r, "professor", "i")`.

### Axis 2 — Affiliation Structure to University

**What varies:** How a person is linked to the university whose name should be returned.

| Variant pattern | SPARQL handling |
|---|---|
| Two-hop: worksAt → Department → partOfUniversity → University (seed) | As shown in template |
| Direct affiliation: `?person uni:affiliatedWith ?uni` | Single triple; skip intermediate |
| Longer chain through faculty/school | Add intermediate hop(s) |
| Inverse containment: `?uni uni:hasDepartment ?dept` | Reverse the triple direction |
| Appointment resources | Traverse through appointment node |
| Preferred path with teaching-course fallback | UNION: try worksAt path first, then `?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni` |

**Key principle:** Use Probe 4 to discover the exact chain. Do not assume the seed
pattern applies.

### Axis 3 — Graph Noise and Result Cardinality

**Invariant:** Exactly one row per qualifying professor–university pair.

| Noise source | Mitigation |
|---|---|
| Multiple courses/departments per professor at same university | `SELECT DISTINCT` |
| Non-professor roles in the graph | Professor-identification filter |
| Redundant containment triples | `SELECT DISTINCT` |
| Multiple universities per professor | `GROUP BY` with aggregation if needed |

**Key principle:** Always use `SELECT DISTINCT`. This is the single most common
failure mode in this family.

## Pitfalls

1. **Forgetting DISTINCT** — A professor teaching two courses produces duplicate rows.
2. **Case-sensitive CONTAINS** — `CONTAINS(?role, "Professor")` misses lowercase
   "professor". Use `REGEX(?role, "professor", "i")` as the robust default.
3. **Exact-match role filter** — `FILTER(?role = "Professor")` misses "Assistant
   Professor of X". Always use substring/regex matching.
4. **Hardcoding the prefix** — Different variants use different namespace URIs.
   Always extract from the Turtle file's `@prefix` declarations.
5. **Wrong name predicate** — Could be `uni:hasName`, `rdfs:label`, `foaf:name`,
   `schema:name`. Use Probe 5 to discover it.
6. **Assuming the seed affiliation chain** — Use Probe 4 to discover the actual
   predicate path from Person to University.

## Worked v01 Solution

The v01 seed uses:
- String-valued `uni:role` with case-sensitive `CONTAINS("Professor")` (sufficient
  because v01 uses title case consistently)
- Two-hop chain: `uni:worksAt` → `uni:partOfUniversity`
- `uni:hasName` for both person and university names

See `assets/solution.sparql` for the concrete query.

**Verification against v01 data:** Returns exactly 7 rows:

| Professor | University |
|---|---|
| Alex Morgan | National Technical University of Athens |
| Thomas Berger | National Technical University of Athens |
| Felix Wagner | Instituto Superior Técnico |
| Martin Keller | National and Kapodistrian University of Athens |
| John Smith | Massachusetts Institute of Technology |
| Marie Dubois | Sorbonne University |
| Stefan Mueller | Ludwig Maximilian University of Munich |

Excluded: Jane Petterson (Lecturer), three Students — correctly filtered out.

## Generalization Checklist for New Variants

When facing a new member of this family:

1. **Run Discovery Probes 1-5** — Determine namespace, predicates, role values,
   affiliation chain, and name predicates.
2. **Choose professor identification** — String role (use REGEX case-insensitive),
   resource rank (traverse to label), or class type (use rdf:type).
3. **Instantiate affiliation chain** — From Probe 4 results, write the correct
   number of hops with the correct predicates.
4. **Set name predicates** — From Probes 2 and 5, use the correct name predicates
   for persons and universities.
5. **Add SELECT DISTINCT** — Always.
6. **Write and test** — Run against the data, verify row count and content.
