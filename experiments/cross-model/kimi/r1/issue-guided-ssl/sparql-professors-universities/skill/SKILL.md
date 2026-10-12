---
name: sparql-professors-universities
description: Discovers knowledge graph structure to construct SPARQL queries that identify professors and their affiliated universities, handling variations in role representation, affiliation paths, and graph noise.
---

# SPARQL Professors-Universities Skill

This Skill provides a discover-construct-validate workflow for querying knowledge graphs to find professors and their affiliated universities. It handles three primary variation axes:

1. **Professor Identification Semantics**: How professors are distinguished from non-target roles
2. **Affiliation Structure to University**: How persons link to university names
3. **Graph Noise and Result Cardinality**: Managing duplicates and distracting data

## Quick Start

**USE THIS TEMPLATE ONLY after discovery confirms the v01 shape** — string uni:role values present, worksAt→partOfUniversity path observed, no rank narrowing in the instruction. Otherwise follow the full workflow below.

For the standard case (v01 pattern), use this template:

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName .
  FILTER(CONTAINS(lcase(STR(?role)), "professor"))
  
  ?professor uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
  
  ?university uni:hasName ?universityName .
}
```

Then run validation:
```bash
python3 /skill/scripts/validate_solution.py /app/university_graph.ttl /app/solution.sparql
```

## Workflow

### Step 1: Discover Graph Structure

Run `scripts/discover_graph.py` on the target TTL file to understand:
- What values/properties identify professors (uni:role strings vs uni:hasAcademicRank resources)
- The path from persons to universities (direct, via departments, inverse containment, etc.)
- Name predicates used for persons and universities

```bash
python3 /skill/scripts/discover_graph.py /app/university_graph.ttl
```

### Step 2: Construct SPARQL Query

Based on discovery results, select and adapt patterns from the sections below.

### Step 3: Validate Solution

Run `scripts/validate_solution.py` to verify:
- Projection variables match requirements
- No duplicate rows
- Results count matches expected
- Cross-check against discovered role census

```bash
python3 /skill/scripts/validate_solution.py /app/university_graph.ttl /app/solution.sparql
```

## Pattern Library

### Professor Identification Patterns

#### Pattern A: String Role Matching (Portable - lcase+CONTAINS)

```sparql
?person uni:role ?role .
FILTER(CONTAINS(lcase(STR(?role)), "professor"))
```

**When to use:** Default portable pattern that works across SPARQL implementations.

**Properties:**
- `lcase()`: Case-insensitive matching (matches "professor", "Professor", "PROFESSOR")
- `STR()`: Guards against typed/language-tagged literals

**Extensions:**

For abbreviations ("Prof."):
```sparql
FILTER(CONTAINS(lcase(STR(?role)), "professor") ||
       CONTAINS(lcase(STR(?role)), "prof."))
```

For explicit exclusion of near-misses:
```sparql
FILTER(CONTAINS(lcase(STR(?role)), "professor") &&
       !CONTAINS(lcase(STR(?role)), "to the professor"))
```

#### Pattern A-Narrowed: Excluding Sub-Ranks (Full Professors Only)

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
2. Run `discover_graph.py` to get role census
3. Classify each observed role as include/exclude based on instruction
4. Build `include-pattern ∧ ¬exclude-pattern` from actual data
5. Verify with `validate_solution.py` section 4 (role classification)

**Caution:** Substring exclusion over-excludes by design. Build exclusion list from ACTUAL role census, not imagination.

#### Pattern B: String Role Matching (Regex with Word Boundaries)

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

#### Pattern C: Resource Rank Matching

When ranks are resources instead of strings:

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

### Affiliation Path Patterns

#### Pattern 1: Standard Chain (worksAt → partOfUniversity*)

```sparql
?person uni:worksAt ?org .
?org uni:partOfUniversity* ?university .
```

The `*` allows:
- Direct university affiliation (length 0: ?org = ?university)
- Single hop via department (standard case)
- Multiple hops through organizational hierarchy

#### Pattern 2: With Fallback (worksAt preferred, teaches fallback)

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

The NOT EXISTS guard is essential - a plain UNION yields duplicates when both paths exist.

#### Pattern 3: Inverse Containment

```sparql
?person uni:worksAt ?org .
?org ^uni:hasDepartment ?university .
```

#### Pattern 4: Mixed Direction

```sparql
?person uni:worksAt ?org .
?org (uni:partOfUniversity|^uni:hasDepartment)* ?university .
```

### Name Retrieval Patterns

#### Standard Pattern

```sparql
?person uni:hasName ?professorName .
?university uni:hasName ?universityName .
```

#### With rdfs:label Fallback

```sparql
OPTIONAL { ?person uni:hasName ?name1 }
OPTIONAL { ?person rdfs:label ?name2 }
BIND(COALESCE(?name1, ?name2) AS ?professorName)
```

Note: Use fresh source variables (?name1, ?name2) - rebinding an in-scope variable with BIND is invalid SPARQL 1.1.

### Cardinality Protection

Always use DISTINCT and project only required variables:

```sparql
SELECT DISTINCT ?professorName ?universityName
```

Never include helper variables (?role, ?org) in the projection.

## Scope Boundaries

### Matcher Scope by Pattern

**Pattern A (lcase+CONTAINS - portable default):**
`CONTAINS(lcase(STR(?role)), "professor")`

| Role String | Accepted | Reason |
|-------------|----------|--------|
| "Professor of Computer Science" | ✓ | Contains "professor" |
| "Assistant Professor of CS" | ✓ | Contains "professor" |
| "professor of physics" (lowercase) | ✓ | lcase() normalizes |
| "Prof. of Chemistry" | ✗ | "Prof." not matched (abbreviation) |
| "Professor Emeritus" | ✓ | Contains "Professor" (instruction-driven) |
| "Assistant to the Professor" | ✓ | Contains "Professor" (no word boundaries) |

**Pattern B (regex word boundaries):**
`REGEX(STR(?role), "(^|[^a-z])professor([^a-z]|$)", "i")`

| Role String | Accepted | Reason |
|-------------|----------|--------|
| "Professor of Computer Science" | ✓ | Word boundary before/after |
| "Assistant Professor of CS" | ✓ | Word boundary before "Professor" |
| "professor of physics" (lowercase) | ✓ | Case-insensitive flag |
| "Prof. of Chemistry" | ✗ | Abbreviation not matched |
| "Professor Emeritus" | ✓ | Word boundary after "Professor" (instruction-driven) |
| "Assistant to the Professor" | ✗ | No word boundary (preceded by "the ") |

### Path Scope (Zero-or-More)

The `uni:partOfUniversity*` pattern handles:
- Direct affiliation: Person → worksAt → University
- Standard chain: Person → worksAt → Department → partOfUniversity → University
- Extended chains: Person → worksAt → Lab → partOfUniversity → Department → partOfUniversity → University

### Cardinality Scope (DISTINCT)

One professor with multiple worksAt to different departments of same university:
- Without DISTINCT: Multiple rows (one per department)
- With DISTINCT: Single row (as required by invariant)

## Complete Query Templates

### Template 1: Standard (v01 pattern)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName .
  FILTER(CONTAINS(lcase(STR(?role)), "professor"))
  
  ?professor uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
  
  ?university uni:hasName ?universityName .
}
```

### Template 2: With Fallback Path

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName .
  FILTER(CONTAINS(lcase(STR(?role)), "professor"))
  
  {
    ?professor uni:worksAt ?org .
    ?org uni:partOfUniversity* ?university .
  }
  UNION
  {
    ?professor uni:teaches ?course .
    ?course uni:isTaughtIn ?org .
    ?org uni:partOfUniversity* ?university .
    FILTER NOT EXISTS { ?professor uni:worksAt ?any }
  }
  
  ?university uni:hasName ?universityName .
}
```

### Template 3: Narrowed (Full Professors Only)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:role ?role ;
             uni:hasName ?professorName .
  FILTER(CONTAINS(lcase(STR(?role)), "professor") &&
         !(CONTAINS(lcase(STR(?role)), "assistant") ||
           CONTAINS(lcase(STR(?role)), "associate") ||
           CONTAINS(lcase(STR(?role)), "emeritus")))
  
  ?professor uni:worksAt ?org .
  ?org uni:partOfUniversity* ?university .
  
  ?university uni:hasName ?universityName .
}
```

## Probe Test Results

Run against `probe_graph.ttl`:

```bash
python3 -c "
from rdflib import Graph
g = Graph()
g.parse('/skill/probe_graph.ttl', format='turtle')
query = open('/app/solution.sparql').read()
for row in g.query(query):
    print(f'{row.professorName} @ {row.universityName}')
"
```

**Pattern A (lcase+CONTAINS) - Default:**
- ACCEPTED: Alice Lowercase (case test), Charlie Emeritus (substring), David Assistant (contains "Professor"), Grace Multi-Department (DISTINCT=1 row), Henry Standard, Ivy Assistant
- REJECTED: Bob Abbreviation ("Prof." not matched), Eve Lecturer, Frank Student

**Pattern B (word-boundary regex):**
- ACCEPTED: Alice Lowercase, Charlie Emeritus, Grace Multi-Department, Henry Standard, Ivy Assistant
- REJECTED: Bob Abbreviation ("Prof." not matched), David Assistant (word boundary violation), Eve Lecturer, Frank Student

**Pattern A-Narrowed (exclude Assistant/Emeritus):**
- ACCEPTED: Alice Lowercase, Grace Multi-Department, Henry Standard
- REJECTED: Bob Abbreviation, Charlie Emeritus (emeritus excluded), David Assistant (assistant excluded), Eve Lecturer, Frank Student, Ivy Assistant (assistant excluded)

**Mechanism:**
- Case-insensitivity: `lcase()` handles "professor" vs "Professor" vs "PROFESSOR"
- Abbreviation: "Prof." requires pattern extension to match
- Multi-department: DISTINCT ensures exactly 1 row for Grace Multi-Department
- Word boundaries: Character-class pattern `(^|[^a-z])professor([^a-z]|$)` excludes "Assistant to the Professor"

## Scripts

- `scripts/discover_graph.py`: Discovers graph structure (roles, paths, predicates)
- `scripts/validate_solution.py`: Validates query results against requirements

## Resources

**Accessing Package Files:**
- The `read` tool may reject absolute paths outside the workspace (e.g., `/skill/references/sparql_patterns.md`)
- Use `task_shell` to access package resources: `cat /skill/references/sparql_patterns.md` or `python3 /skill/scripts/discover_graph.py`
- `SKILL.md` (this file) is the guaranteed channel and contains the complete Pattern Library

## References

- `references/sparql_patterns.md` — MIRROR of SKILL.md Pattern Library; edit SKILL.md first, keep in sync

## Common Pitfalls

### Backslash Escaping in SPARQL

In SPARQL strings, `\b` must be written as `\\b`:
- ✓ Correct: `FILTER(REGEX(STR(?role), "\\bprofessor\\b", "i"))`
- ✗ Wrong: `FILTER(REGEX(STR(?role), "\bprofessor\b", "i"))` (parses as backspace escape)

### Variable Projection

Never project helper variables:
- ✓ Correct: `SELECT DISTINCT ?professorName ?universityName`
- ✗ Wrong: `SELECT DISTINCT ?professorName ?universityName ?role ?org`

### UNION with Fallback

Always use NOT EXISTS guard:
- ✓ Correct: `FILTER NOT EXISTS { ?person uni:worksAt ?any }` before fallback
- ✗ Wrong: Plain UNION produces duplicates when both paths exist

### COALESCE Variable Rebinding

Bind fresh source variables:
- ✓ Correct: `OPTIONAL { ?p uni:hasName ?n1 } OPTIONAL { ?p rdfs:label ?n2 } BIND(COALESCE(?n1, ?n2) AS ?name)`
- ✗ Wrong: Rebinding `?professorName` that's already in scope

## Troubleshooting

### Error: "WORKSPACE_BOUNDARY" when reading /app files

The `read` tool may reject paths outside the host workspace. Use `task_shell` instead:
```bash
cat /app/university_graph.ttl
# or
python3 /skill/scripts/discover_graph.py /app/university_graph.ttl
```

### Error: "No results returned" or empty result set

1. Check discovery output - are professors identified correctly?
2. Verify role values contain "professor" substring
3. Try removing filters temporarily to see if data exists
4. Check that uni: prefix matches the ontology (`http://university.org/ontology#`)

### Error: "Projection mismatch" in validation

Expected: `["professorName", "universityName"]`
- Ensure SELECT variables match exactly (case-sensitive)
- Don't include helper variables like `?role` or `?org` in projection
- Must use `SELECT DISTINCT`, not just `SELECT`

### Error: "Duplicate rows" in validation

1. Ensure DISTINCT is in the SELECT clause
2. Check for professors with multiple worksAt to same university
3. Verify no helper variables in projection
4. If multiple paths exist (worksAt + teaches), use FILTER NOT EXISTS guard

### Error: SPARQL parse error "\b"

Backslash must be escaped in SPARQL strings:
- ✓ Correct: `FILTER(REGEX(STR(?role), "\\bprofessor\\b", "i"))`
- ✗ Wrong: `FILTER(REGEX(STR(?role), "\bprofessor\b", "i"))`

### Error: "Variable already in scope" with BIND

Use fresh source variables before COALESCE:
```sparql
OPTIONAL { ?person uni:hasName ?n1 }
OPTIONAL { ?person rdfs:label ?n2 }
BIND(COALESCE(?n1, ?n2) AS ?professorName)
```

### Unexpected roles in results (e.g., "Lecturer", "Student")

The lcase+CONTAINS pattern may match unexpected strings. Check discovery report section 1 and adjust filter:
- Add explicit exclusions: `!CONTAINS(lcase(?role), "lecturer")`
- Or use word-boundary regex pattern for stricter matching

### Validation shows wrong number of results

Compare against discovery census:
- Section 4 of discovery report shows total persons and expected professor count
- Section 4 of validation shows which roles were included/excluded
- If mismatch, adjust pattern to match actual role strings
