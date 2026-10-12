---
name: sparql-professors-universities
description: >
  Generate SPARQL queries to retrieve professors and their affiliated universities
  from RDF knowledge graphs. Handles variation across three axes: professor identification
  semantics (string roles vs resource ranks, various spellings), affiliation structure
  (direct vs indirect links, different predicates), and graph noise/cardinality (duplicates,
  multiple affiliations). Produces a query returning ?professorName and ?universityName
  with exactly one row per qualifying professor-university pair.
---

# SPARQL Professors-Universities Query Skill

## Purpose

This skill generates SPARQL queries that extract professors and their affiliated universities
from RDF knowledge graphs. The task family spans graphs with different data layouts, role
representations, and affiliation structures. The skill provides a systematic procedure for
analyzing a new graph and assembling the correct query.

## Three-Axis Variation Framework

The task family varies along three independent axes. For each axis, identify which variant
applies to the target graph, then select the corresponding SPARQL pattern.

### Axis 1: Professor Identification Semantics

**What varies:** How qualifying professors are represented and distinguished from non-target roles.

**Variant detection:**
- Inspect role/rank predicates: `uni:role` (string), `uni:hasAcademicRank` (resource), or other
- Check role value format: plain strings ("Professor", "Assistant Professor"), resource URIs, or mixed
- Identify qualifying ranks: typically "Professor" and "Assistant Professor", but may include "Full Professor", "Associate Professor", etc.
- Identify non-qualifying roles: "Lecturer", "Student", "Staff", "Visiting Professor", "Professor Emeritus", etc.

**Pattern catalog:**

#### Pattern 1A: String-based roles (v01 default)
```sparql
?person a uni:Person ;
        uni:role ?role .
FILTER(CONTAINS(?role, "Professor"))
```
- Use when roles are string literals
- CONTAINS matches both "Professor" and "Assistant Professor"
- Adjust filter if variant requires exact matching or different qualifying terms

#### Pattern 1B: Exact string matching
```sparql
?person a uni:Person ;
        uni:role ?role .
FILTER(?role = "Professor" || ?role = "Assistant Professor" || ?role = "Full Professor")
```
- Use when CONTAINS is too broad (e.g., "Visiting Professor" should not qualify)
- Explicit enumeration of qualifying roles

#### Pattern 1C: Resource-based ranks
```sparql
?person a uni:Person ;
        uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
```
- Use when ranks are resources with label properties
- Follow the rank resource to its label, then filter

#### Pattern 1D: Union of string and resource patterns
```sparql
{
  ?person uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
}
UNION
{
  ?person uni:hasAcademicRank ?rank .
  ?rank uni:rankLabel ?rankLabel .
  FILTER(?rankLabel = "Professor" || ?rankLabel = "Assistant Professor")
}
```
- Use when graph may contain both representations
- Ensures no professors are missed

### Axis 2: Affiliation Structure to University

**What varies:** How a person is linked to the university name that should be returned.

**Variant detection:**
- Trace from person: does `uni:worksAt` lead to a department or directly to a university?
- Check department predicates: `uni:partOfUniversity`, `uni:memberOf`, or inverse `uni:hasDepartment`
- Look for appointment resources: `uni:hasAppointment`, `uni:affiliatedWith`
- Check for fallback paths: teaching a course at a department when worksAt is absent

**Pattern catalog:**

#### Pattern 2A: Two-hop via department (v01 default)
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?university .
?university uni:hasName ?universityName .
```
- Use when person → department → university chain exists
- Most common in academic ontologies

#### Pattern 2B: Direct affiliation
```sparql
?person uni:worksAt ?university .
?university a uni:University ;
            uni:hasName ?universityName .
```
- Use when person links directly to university
- Add type check to ensure target is a university

#### Pattern 2C: Union of two-hop and direct
```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:worksAt ?university .
  ?university a uni:University .
}
?university uni:hasName ?universityName .
```
- Use when graph may contain both structures
- Handles heterogeneous data

#### Pattern 2D: Inverse containment
```sparql
?person uni:worksAt ?dept .
?university uni:hasDepartment ?dept .
?university uni:hasName ?universityName .
```
- Use when department → university link is inverse
- Check for `uni:hasDepartment` or similar

#### Pattern 2E: Appointment resources
```sparql
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?university .
?university uni:hasName ?universityName .
```
- Use when affiliations are reified as appointment resources
- More complex but allows temporal/role metadata

#### Pattern 2F: Teaching fallback
```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?university .
}
?university uni:hasName ?universityName .
```
- Use when some professors lack worksAt but teach courses
- Primary path via worksAt, fallback via teaching

### Axis 3: Graph Noise and Result Cardinality

**What varies:** Amount of distracting data and duplicate-binding risk.

**Required invariant:** Exactly one row per qualifying professor-university pair, projecting
exactly `?professorName` and `?universityName`.

**Noise sources:**
- Multiple departments per university → professor appears in multiple departments of same university
- Multiple role assertions for same person
- Person matches both string-role and rank-resource patterns
- Multiple universities per professor (rare, but spec says "assume one")

**Deduplication strategy:**

Always use `SELECT DISTINCT` as baseline:
```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
```

This handles:
- Duplicate bindings from UNION patterns
- Multiple matching paths to same university
- Overlapping pattern matches

Avoid GROUP BY unless aggregation is needed. DISTINCT is simpler and more robust.

## Procedure for Query Generation

### Step 1: Inspect the Graph

Load the Turtle file and examine:
1. **Role representation:** What predicates link persons to roles/ranks? Are values strings or resources?
2. **Qualifying roles:** Which role values indicate a professor? (e.g., "Professor", "Assistant Professor")
3. **Affiliation structure:** What predicate links persons to organizations? Does it lead to departments or universities directly?
4. **University name:** What predicate provides the university name? (e.g., `uni:hasName`)

Example inspection queries:
```sparql
# Find role predicates and sample values
SELECT DISTINCT ?rolePred ?roleVal (COUNT(?p) AS ?count)
WHERE {
  ?p ?rolePred ?roleVal .
  FILTER(STRSTARTS(STR(?rolePred), "http://university.org/ontology#"))
  FILTER(CONTAINS(LCASE(STR(?roleVal)), "professor") || 
         CONTAINS(LCASE(STR(?roleVal)), "lecturer") ||
         CONTAINS(LCASE(STR(?roleVal)), "student"))
}
GROUP BY ?rolePred ?roleVal

# Trace affiliation paths from a professor
SELECT ?pred ?obj
WHERE {
  ?person uni:role ?role .
  FILTER(CONTAINS(?role, "Professor"))
  ?person ?pred ?obj .
  FILTER(?pred != uni:role && ?pred != uni:hasName)
}
LIMIT 20
```

### Step 2: Select Patterns

Based on inspection:
- **Axis 1:** Choose role identification pattern (1A, 1B, 1C, or 1D)
- **Axis 2:** Choose affiliation pattern (2A, 2B, 2C, 2D, 2E, or 2F)
- **Axis 3:** Always use SELECT DISTINCT

### Step 3: Assemble Query

Combine selected patterns:
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName .
  
  # Axis 1: Professor identification
  # [Insert selected pattern here]
  
  # Axis 2: Affiliation to university
  # [Insert selected pattern here]
  
  ?university uni:hasName ?universityName .
}
```

### Step 4: Validate

Run the query and check:
1. Results contain only professors (no lecturers, students, staff)
2. Each professor appears exactly once
3. University names are correct
4. No missing professors

## References

- `references/data-models.md` — Known data layouts with example triples
- `references/sparql-patterns.md` — Reusable SPARQL building blocks with when-to-use guidance

## v01 Instantiation

For the seed variant (v01):
- **Axis 1:** Pattern 1A (string-based roles with CONTAINS)
- **Axis 2:** Pattern 2A (two-hop via department)
- **Axis 3:** SELECT DISTINCT

Resulting query:
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  FILTER(CONTAINS(?role, "Professor"))
}
```

This query correctly retrieves 7 professors and their universities from the v01 graph.
