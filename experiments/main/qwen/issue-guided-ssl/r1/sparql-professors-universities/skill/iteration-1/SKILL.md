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

## Core SPARQL Pattern Template

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # --- Step 1: Identify professors ---
  ?person  uni:hasName  ?professorName .
  # Professor identification varies by variant — see Axis 1 below.
  # Seed pattern (string-valued role):
  ?person  uni:role     ?role .
  FILTER( CONTAINS(?role, "Professor") )

  # --- Step 2: Traverse affiliation to university ---
  # Affiliation structure varies by variant — see Axis 2 below.
  # Seed pattern (two-hop through department):
  ?person  uni:worksAt           ?dept .
  ?dept    uni:partOfUniversity  ?uni  .

  # --- Step 3: Retrieve university name ---
  ?uni     uni:hasName  ?universityName .
}
```

Every variant in this family is solved by instantiating the three steps above with the
correct predicates and filters for the given ontology.

## Variation Axes

### Axis 1 — Professor Identification Semantics

**What varies:** How qualifying professors are represented and distinguished from
non-target roles (lecturers, students, staff, postdocs, etc.).

| Variant pattern | SPARQL handling |
|---|---|
| String-valued `uni:role` containing "Professor" (seed) | `FILTER(CONTAINS(?role, "Professor"))` |
| Abbreviated forms ("Prof.", "Asst. Prof.") | Extend filter: `FILTER(CONTAINS(?role, "Professor") \|\| CONTAINS(?role, "Prof."))` or use `REGEX(?role, "[Pp]rof")` |
| Resource-valued `uni:hasAcademicRank` with `uni:rankLabel` | Replace role pattern with: `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?rankLabel . FILTER(CONTAINS(?rankLabel, "Professor"))` |
| Explicit class-based typing (e.g., `a uni:FullProfessor`) | Use type triple: `?person a uni:FullProfessor` or a UNION of professor subclasses |
| Near-miss roles ("Professor Emeritus", "Visiting Professor") | Decide inclusion policy; CONTAINS("Professor") already catches these. Narrow with explicit exclusion if needed. |

**Key principle:** Always inspect the ontology to determine whether rank is a literal
string, a resource with a label, or an RDF class. Adapt the filter accordingly.

### Axis 2 — Affiliation Structure to University

**What varies:** How a person is linked to the university whose name should be returned.

| Variant pattern | SPARQL handling |
|---|---|
| Two-hop: worksAt → Department → partOfUniversity → University (seed) | As shown in template |
| Direct affiliation: `?person uni:affiliatedWith ?uni` | Single triple; skip intermediate |
| Longer chain through faculty/school: worksAt → Faculty → partOf → University | Add intermediate hop |
| Inverse containment: `?uni uni:hasDepartment ?dept . ?dept uni:hasMember ?person` | Reverse the triple direction |
| Appointment resources: `?person uni:hasAppointment ?appt . ?appt uni:atOrganization ?uni` | Traverse through appointment node |
| Preferred path with teaching-course fallback | Use OPTIONAL + COALESCE or UNION to try worksAt path first, then fall back to `?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni` |

**Key principle:** Trace the ontology's organizational hierarchy. The chain may be 1–3
hops and may use forward or inverse predicates. Always end at a node that has the
university name (typically via `uni:hasName` or equivalent `rdfs:label`).

### Axis 3 — Graph Noise and Result Cardinality

**What varies:** Amount of distracting data, duplicate-binding risk, and overlapping
organization paths.

**Invariant:** Exactly one row per qualifying professor–university pair with exactly
the requested projection variables.

| Noise source | Mitigation |
|---|---|
| Professor teaches multiple courses at same university | `SELECT DISTINCT` |
| Professor has multiple department affiliations within one university | `SELECT DISTINCT` |
| Non-professor roles (Lecturer, Student, Staff) in the graph | Professor-identification filter excludes them |
| Redundant containment triples | `SELECT DISTINCT` |
| Multiple universities per professor (spec says assume single) | If needed, add `GROUP BY ?professorName` with aggregation |

**Key principle:** Always use `SELECT DISTINCT` unless the task explicitly requires
multiset semantics. This is the single most common failure mode.

## Pitfalls

1. **Forgetting DISTINCT** — The most frequent error. A professor who teaches two
   courses or belongs to two departments will produce duplicate rows without it.
2. **Exact-match role filter** — Using `FILTER(?role = "Professor")` misses
   "Assistant Professor of X", "Full Professor", etc. Always use CONTAINS or REGEX.
3. **Hardcoding the prefix** — Different variants may use different namespace URIs.
   Always read the Turtle file's `@prefix` declarations.
4. **Wrong name predicate** — University name might be `uni:hasName`, `rdfs:label`,
   `foaf:name`, or `schema:name`. Check the ontology.
5. **Missing professor types** — Some variants distinguish "Full Professor" from
   "Assistant Professor" via separate classes rather than a role string.

## Worked v01 Solution

The v01 seed uses:
- String-valued `uni:role` with CONTAINS("Professor") for identification
- Two-hop chain: `uni:worksAt` → `uni:partOfUniversity` for affiliation
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

1. **Read the Turtle file** — Identify all `@prefix` declarations and the ontology structure.
2. **Identify professor representation** — Is it a role string, an academic-rank resource, or a class?
3. **Trace the affiliation path** — Follow predicates from Person to University; count hops.
4. **Find the name predicates** — How are person names and university names stored?
5. **Assess noise** — Are there duplicate paths? Multiple affiliations? Use DISTINCT.
6. **Write and test** — Instantiate the template, run against the data, verify row count.
