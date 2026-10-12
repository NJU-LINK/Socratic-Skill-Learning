---
name: sparql-professors-universities
description: >
  Build SPARQL queries that retrieve professors and their affiliated universities
  from Turtle knowledge graphs. Handles variant representations of academic rank
  (role strings vs. hasAcademicRank resources), variant affiliation structures
  (worksAt→department→university, direct worksAt→university, or teaches-based
  fallback), and enforces exactly-one-row-per-pair cardinality with preference
  logic to prevent spurious affiliations.
---

# SPARQL Professors-Universities Query Construction

## Task Pattern

Given a Turtle (.ttl) knowledge graph containing universities, departments, people,
and their relationships, produce a SPARQL query that returns each qualifying professor
and the university they work at, with exactly one row per professor-university pair.

## Core Methodology

### Step 1: Inspect the Graph Structure

Before writing the query, explore the data to understand:
- What predicates link people to their roles/ranks
- What predicates link people to organizations (departments, universities)
- Whether roles are string literals or structured resources
- Whether there are multiple affiliation paths that could create ambiguity

Use a SPARQL exploration query or rdflib to enumerate all persons and their properties.

### Step 2: Professor Identification (Two Representation Patterns)

Professors may be identified by:

**Pattern A — Role string:**
```sparql
?person uni:role ?role .
FILTER(CONTAINS(?role, "Professor"))
```
This matches "Professor of X", "Assistant Professor of Y", etc.
Excludes "Lecturer", "Student", "Staff", etc.

**Pattern B — Academic rank resource:**
```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(CONTAINS(?rankLabel, "Professor"))
```
This matches when rank is a structured resource rather than a plain string.

**Combine with UNION** — a person won't have both in the same variant, but if they
did, either correctly confirms professorship:
```sparql
{
    ?person uni:role ?role .
    FILTER(CONTAINS(?role, "Professor"))
} UNION {
    ?person uni:hasAcademicRank ?rank .
    ?rank uni:rankLabel ?rankLabel .
    FILTER(CONTAINS(?rankLabel, "Professor"))
}
```

### Step 3: Affiliation Path with Preference Logic

**Critical insight:** A person may have multiple paths to universities (e.g., worksAt
one department but teaches a course in another). A flat UNION creates spurious
affiliations. Use preference: worksAt is primary, teaches is fallback only when
worksAt is absent.

**Preferred paths (worksAt):**
```sparql
# Path A: worksAt -> department -> partOfUniversity
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .

# Path B: worksAt directly to University
?person uni:worksAt ?uni .
?uni a uni:University .
```

**Fallback path (teaches) — gated by FILTER NOT EXISTS:**
```sparql
?person uni:teaches ?course .
?course uni:isTaughtIn ?dept .
?dept uni:partOfUniversity ?uni .
FILTER NOT EXISTS {
    ?person uni:worksAt ?anyWorksAt .
}
```

The FILTER NOT EXISTS ensures the fallback only fires when the person has NO worksAt
link at all. This prevents a professor who works at University A but teaches a course
at University B from being incorrectly affiliated with University B.

**Combine with UNION:**
```sparql
{
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
} UNION {
    ?person uni:worksAt ?uni .
    ?uni a uni:University .
} UNION {
    ?person uni:teaches ?course .
    ?course uni:isTaughtIn ?dept .
    ?dept uni:partOfUniversity ?uni .
    FILTER NOT EXISTS {
        ?person uni:worksAt ?anyWorksAt .
    }
}
```

### Step 4: Project and Deduplicate

Project the required variables and use DISTINCT to guarantee one row per
professor-university pair:
```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
```

If the university name is stored as `uni:hasName`, retrieve it:
```sparql
?uni uni:hasName ?universityName .
```

### Step 5: Validate Cardinality

After constructing the query, test it against the data:
1. Count the results — should match the number of qualifying professors
2. Verify exclusions — ensure non-professors (Lecturers, Students, Staff) are excluded
3. Check for spurious affiliations — if a professor has multiple affiliation paths,
   ensure they map to the correct university (the one from worksAt, not teaches)

Use rdflib or a SPARQL endpoint to execute and inspect results.

## Common Pitfalls

1. **Flat UNION on affiliation paths:** Creates duplicate rows when a person has
   multiple paths to different universities. Always use preference logic.

2. **Overly broad role matching:** Using `FILTER(STRSTARTS(?role, "Professor"))`
   excludes "Assistant Professor". Use `CONTAINS` instead.

3. **Missing DISTINCT:** If multiple departments link to the same university, a
   professor could appear multiple times. DISTINCT on projection variables collapses
   these.

4. **Hardcoding predicates:** Variants may use different predicate names. Inspect
   the graph first, then adapt the query to the actual predicates present.

## Example Query Template

```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a uni:Person ;
            uni:hasName ?professorName .

    # Professor identification
    {
        ?person uni:role ?role .
        FILTER(CONTAINS(?role, "Professor"))
    } UNION {
        ?person uni:hasAcademicRank ?rank .
        ?rank uni:rankLabel ?rankLabel .
        FILTER(CONTAINS(?rankLabel, "Professor"))
    }

    # Affiliation with preference
    {
        ?person uni:worksAt ?dept .
        ?dept uni:partOfUniversity ?uni .
    } UNION {
        ?person uni:worksAt ?uni .
        ?uni a uni:University .
    } UNION {
        ?person uni:teaches ?course .
        ?course uni:isTaughtIn ?dept .
        ?dept uni:partOfUniversity ?uni .
        FILTER NOT EXISTS {
            ?person uni:worksAt ?anyWorksAt .
        }
    }

    ?uni uni:hasName ?universityName .
}
ORDER BY ?professorName
```

## Adaptation Guide

When facing a new variant:
1. **Inspect the Turtle file** to identify actual predicates and structure
2. **Map to the patterns above** — if role is a string, use Pattern A; if rank is a
   resource, use Pattern B; if both exist, UNION them
3. **Trace affiliation paths** — if worksAt goes directly to University, use Path B;
   if it goes to Department, use Path A; if worksAt is absent but teaches exists, use
   the fallback
4. **Test and validate** — execute the query, count results, check for exclusions and
   spurious affiliations

The key invariant across all variants: exactly one row per qualifying
professor-university pair, with professors correctly identified and correctly
affiliated to their primary university.
