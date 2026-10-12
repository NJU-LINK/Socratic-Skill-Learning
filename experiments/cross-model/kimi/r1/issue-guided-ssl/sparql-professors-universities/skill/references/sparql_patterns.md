# SPARQL Pattern Reference

**MIRROR of SKILL.md Pattern Library — edit SKILL.md first, keep in sync**

Reusable patterns for sparql-professors-universities queries.
This file mirrors the Pattern Library section from SKILL.md for convenience.
SKILL.md is the single source of truth; edit there first, then sync here.

## Professor Identification Patterns

### Pattern A: String Role Matching (Portable - lcase+CONTAINS)

```sparql
?person uni:role ?role .
FILTER(CONTAINS(lcase(STR(?role)), "professor"))
```

**Properties:**
- `lcase()`: Case-insensitive matching (matches "professor", "Professor", "PROFESSOR")
- `STR()`: Guards against typed/language-tagged literals
- Portable across SPARQL implementations including rdflib

**Extensions:**

For abbreviations (extend the substring list):
```sparql
FILTER(CONTAINS(lcase(STR(?role)), "professor") ||
       CONTAINS(lcase(STR(?role)), "prof."))
```

For explicit exclusion of near-misses:
```sparql
FILTER(CONTAINS(lcase(STR(?role)), "professor") &&
       !CONTAINS(lcase(STR(?role)), "to the professor"))
```

### Pattern A-Narrowed: Excluding Sub-Ranks (Full Professors Only)

When the task narrows accepted ranks (e.g., "only Full Professors"):

```sparql
?person uni:role ?role .
FILTER(CONTAINS(lcase(STR(?role)), "professor") &&
       !(CONTAINS(lcase(STR(?role)), "assistant") ||
         CONTAINS(lcase(STR(?role)), "associate") ||
         CONTAINS(lcase(STR(?role)), "adjunct") ||
         CONTAINS(lcase(STR(?role)), "visiting") ||
         CONTAINS(lcase(STR(?role)), "emeritus")))
```

**Operational loop:**
1. Read task instruction for rank constraints
2. Classify EVERY distinct role from discover_graph.py census as in/out
3. Build include-pattern ∧ ¬exclude-pattern from actual observed roles
4. Verify with validate_solution.py section 4 (role classification report)

**Caution:** Substring exclusion over-excludes by design. Build exclusion list from ACTUAL role census, not imagination. "assistant" kills "Assistant Professor" but also any title containing that substring.

### Pattern B: String Role Matching (Regex with Word Boundaries)

Where regex word boundaries are supported:
```sparql
?person uni:role ?role .
FILTER(REGEX(STR(?role), "\\bprofessor\\b", "i"))
```

For rdflib (character class boundaries):
```sparql
FILTER(REGEX(STR(?role), "(^|[^a-z])professor([^a-z]|$)", "i"))
```

For abbreviations:
```sparql
FILTER(REGEX(STR(?role), "(^|[^a-z])(professor|prof\\.)([^a-z]|$)", "i"))
```

### Pattern C: Resource Rank Matching

```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(REGEX(STR(?rankLabel), "\\bprofessor\\b", "i"))
```

Or with explicit IRI matching:
```sparql
?person uni:hasAcademicRank ?rank .
FILTER(?rank IN (uni:FullProfessor, uni:AssistantProfessor))
```

## Affiliation Path Patterns

### Pattern A: Standard Chain

```sparql
?person uni:worksAt ?org .
?org uni:partOfUniversity* ?university .
```

### Pattern B: With Fallback

```sparql
{
  ?person uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?org .
  ?org uni:partOfUniversity* ?university .
  FILTER NOT EXISTS { ?person uni:worksAt ?any }
}
```

### Pattern C: Inverse Containment

```sparql
?person uni:worksAt ?org .
?org ^uni:hasDepartment ?university .
```

### Pattern D: Mixed Direction

```sparql
?person uni:worksAt ?org .
?org (uni:partOfUniversity|^uni:hasDepartment)* ?university .
```

## Name Retrieval Patterns

### Standard Pattern

```sparql
?person uni:hasName ?professorName .
?university uni:hasName ?universityName .
```

### With rdfs:label Fallback

```sparql
OPTIONAL { ?person uni:hasName ?name1 }
OPTIONAL { ?person rdfs:label ?name2 }
BIND(COALESCE(?name1, ?name2) AS ?professorName)
```

**Note:** Use fresh source variables (?name1, ?name2) - rebinding an in-scope variable with BIND is invalid SPARQL 1.1.

## Cardinality Protection Patterns

### Essential DISTINCT

```sparql
SELECT DISTINCT ?professorName ?universityName
```

Never include helper vars (?role, ?org) in the projection.

### Group Concat Alternative (if needed)

```sparql
SELECT ?professorName 
       (GROUP_CONCAT(DISTINCT ?universityName; SEPARATOR=", ") AS ?universities)
```

## Complete Query Template (Portable)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # Professor identification
  ?person uni:role ?role ;
          uni:hasName ?professorName .
  FILTER(CONTAINS(lcase(STR(?role)), "professor"))
  
  # Affiliation path (flexible)
  ?person uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
  
  # University name
  ?university uni:hasName ?universityName .
}
```

## Complete Query Template (Regex with Word Boundaries)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person uni:role ?role ;
          uni:hasName ?professorName .
  FILTER(REGEX(STR(?role), "(^|[^a-z])professor([^a-z]|$)", "i"))
  
  ?person uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
  
  ?university uni:hasName ?universityName .
}
```

## Common Pitfalls

### Case Sensitivity

- ✓ Correct: `lcase(STR(?role))` or regex with `"i"` flag
- ✗ Wrong: Plain `CONTAINS(?role, "Professor")` misses "professor"

### Variable Projection

Never project helper variables:
- ✓ Correct: `SELECT DISTINCT ?professorName ?universityName`
- ✗ Wrong: `SELECT DISTINCT ?professorName ?universityName ?role ?org`

### UNION with Fallback

Always use NOT EXISTS guard:
- ✓ Correct: `FILTER NOT EXISTS { ?person uni:worksAt ?any }` before fallback
- ✗ Wrong: Plain UNION produces duplicates when both paths exist

### Abbreviation Handling

"Prof." abbreviation is not matched by "professor":
- Default pattern rejects: "Prof. of Chemistry"
- Extension required: Add `|| CONTAINS(lcase(STR(?role)), "prof.")`
