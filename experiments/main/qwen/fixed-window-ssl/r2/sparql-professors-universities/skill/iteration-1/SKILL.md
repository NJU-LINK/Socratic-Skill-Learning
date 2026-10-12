---
name: sparql-professors-universities
description: SPARQL query construction for retrieving professors and their affiliated universities from knowledge graphs with varying role representations, affiliation structures, and noise levels.
---

# SPARQL Professors-Universities Query Skill

## Purpose

Construct SPARQL queries that retrieve all qualifying professors and their affiliated universities from knowledge graphs. This skill handles variation across three axes:
1. **Professor identification semantics**: How professors are represented (string roles vs. structured rank resources)
2. **Affiliation structure**: How persons link to universities (direct, via departments, via courses)
3. **Graph noise and cardinality**: Handling duplicates, non-professor roles, and overlapping paths

## Decision Framework

### Step 1: Inspect the Ontology

Before writing the query, examine the Turtle/RDF file to determine:

**A. How are professors identified?**
- **Pattern A**: `uni:role` with string values (e.g., "Professor of X", "Assistant Professor")
- **Pattern B**: `uni:hasAcademicRank` → rank resource → `uni:rankLabel`
- **Pattern C**: Both (use UNION to cover both)

**B. What affiliation predicates exist?**
- `uni:worksAt` → Department → `uni:partOfUniversity` → University (most common)
- `uni:worksAt` → University directly
- `uni:affiliatedWith` → University
- `uni:teaches` → Course → `uni:isTaughtIn` → Department → `uni:partOfUniversity` (fallback only)

**C. What non-professor roles exist?**
- Lecturers, Students, Staff, Researchers, etc.
- Ensure your professor filter excludes these

### Step 2: Build Layered Query

Structure the query as **layered UNION branches** where each branch is a named strategy with explicit guard conditions.

#### Layer 1: Professor Identification

```sparql
# Strategy 1: String-based role
{
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role .
  FILTER( REGEX(LCASE(?role), "professor") )
}
UNION
# Strategy 2: Structured academic rank
{
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:hasAcademicRank ?rank .
  ?rank uni:rankLabel ?rankLabel .
  FILTER( REGEX(LCASE(?rankLabel), "professor") )
}
```

**Key invariants:**
- Case-insensitive matching: `LCASE(?role)` or `LCASE(?rankLabel)`
- Substring matching: `REGEX(..., "professor")` catches "Professor", "Assistant Professor", "Full Professor", "Prof.", etc.
- Type constraint: `?person a uni:Person` ensures we're querying persons

#### Layer 2: Affiliation Traversal

Use **prioritized UNION** with guard conditions to prevent duplicates:

```sparql
# Preferred path: worksAt → Department → partOfUniversity → University
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
}
UNION
# Fallback A: worksAt → University directly
{
  ?person uni:worksAt ?uni .
  ?uni a uni:University ;
       uni:hasName ?universityName .
}
UNION
# Fallback B: affiliatedWith predicate
{
  ?person uni:affiliatedWith ?uni .
  ?uni a uni:University ;
       uni:hasName ?universityName .
}
UNION
# Fallback C: teaching-course path (ONLY if no preferred path exists)
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept .
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  FILTER NOT EXISTS {
    # Guard: no preferred affiliation path exists
    { ?person uni:worksAt ?o . ?o uni:partOfUniversity ?anyUni . }
    UNION
    { ?person uni:worksAt ?anyUni . ?anyUni a uni:University . }
    UNION
    { ?person uni:affiliatedWith ?anyUni . ?anyUni a uni:University . }
  }
}
```

**Critical invariant for teaching fallback:** The `FILTER NOT EXISTS` must check **ALL** preferred paths, not just one. Otherwise, a professor with `worksAt → University_X` who teaches a course in `University_Y`'s department would match both, producing duplicate rows with different universities.

#### Layer 3: Cardinality Control

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
ORDER BY ?professorName
```

**Why DISTINCT is necessary:**
- A professor teaching multiple courses in the same university (via teaching fallback)
- Multiple affiliation paths to the same university
- Overlapping organization structures

**Invariant:** Exactly one row per qualifying professor-university pair.

### Step 3: Validate Results

After constructing the query:

1. **Count check**: Verify the number of results matches expected professor count
2. **Exclusion check**: Confirm non-professors (Lecturers, Students, Staff) are excluded
3. **Duplicate check**: Ensure no professor appears multiple times with the same university
4. **Cross-university check**: Ensure no professor appears with multiple universities (unless the spec explicitly allows it)

## Reference Query Template

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # === LAYER 1: Professor Identification ===
  {
    # Strategy 1: String-based role
    ?person a uni:Person ;
            uni:hasName ?professorName ;
            uni:role ?role .
    FILTER( REGEX(LCASE(?role), "professor") )
  }
  UNION
  {
    # Strategy 2: Structured academic rank
    ?person a uni:Person ;
            uni:hasName ?professorName ;
            uni:hasAcademicRank ?rank .
    ?rank uni:rankLabel ?rankLabel .
    FILTER( REGEX(LCASE(?rankLabel), "professor") )
  }

  # === LAYER 2: Affiliation Traversal ===
  {
    # Preferred: worksAt → Department → partOfUniversity → University
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
    ?uni uni:hasName ?universityName .
  }
  UNION
  {
    # Fallback A: worksAt → University directly
    ?person uni:worksAt ?uni .
    ?uni a uni:University ;
         uni:hasName ?universityName .
  }
  UNION
  {
    # Fallback B: affiliatedWith predicate
    ?person uni:affiliatedWith ?uni .
    ?uni a uni:University ;
         uni:hasName ?universityName .
  }
  UNION
  {
    # Fallback C: teaching-course path (guarded)
    ?person uni:teaches ?course .
    ?course uni:isTaughtIn ?dept .
    ?dept uni:partOfUniversity ?uni .
    ?uni uni:hasName ?universityName .
    FILTER NOT EXISTS {
      { ?person uni:worksAt ?o . ?o uni:partOfUniversity ?anyUni . }
      UNION
      { ?person uni:worksAt ?anyUni . ?anyUni a uni:University . }
      UNION
      { ?person uni:affiliatedWith ?anyUni . ?anyUni a uni:University . }
    }
  }
}
ORDER BY ?professorName
```

## Common Pitfalls

1. **Case-sensitive matching**: Using `CONTAINS(?role, "Professor")` fails on "professor" or "PROFESSOR". Always use `LCASE()` or case-insensitive regex.

2. **Incomplete FILTER NOT EXISTS**: If the teaching fallback's guard only checks one preferred path, variants with mixed affiliation structures produce cross-university duplicates.

3. **Missing DISTINCT**: Without it, professors with multiple courses or multiple affiliation paths produce duplicate rows.

4. **Overly broad professor filter**: Matching any string containing "professor" might include "Professor Emeritus" or "Visiting Professor" when the spec intends to exclude them. Check the spec's definition of "qualifying professor".

5. **Hardcoding predicates**: Variants may use different predicate names (e.g., `uni:employedAt` instead of `uni:worksAt`). Inspect the ontology before writing the query.

6. **Cross-product between identification and affiliation layers**: If a professor has multiple affiliation paths to **different** universities (e.g., `worksAt University_X` AND `affiliatedWith University_Y`), the UNION in Layer 2 produces multiple rows with different university names. DISTINCT cannot deduplicate these because the values differ.

   **Defensive fix**: If the task does NOT guarantee one university per professor, wrap the affiliation traversal in an inner subquery with GROUP BY:
   ```sparql
   SELECT DISTINCT ?professorName ?universityName
   WHERE {
     # Layer 1: Professor identification
     { ... } UNION { ... }

     # Layer 2: Affiliation via subquery to enforce one-university-per-professor
     {
       SELECT ?person ?universityName WHERE {
         { ... preferred path ... }
         UNION
         { ... fallback paths with guards ... }
       }
       GROUP BY ?person ?universityName
     }
   }
   ```
   This ensures exactly one row per professor-university pair even when multiple affiliation paths exist.

   **When to use**: If the task explicitly states "each professor works at exactly one university," DISTINCT is sufficient. But for variants without this guarantee, use the inner-subquery pattern.

## Variant Adaptation Guide

When encountering a new variant:

1. **Check professor representation**: Does it use `uni:role` strings, `uni:hasAcademicRank` resources, or both?
2. **Map affiliation predicates**: What predicates link persons to organizations? What predicates link organizations to universities?
3. **Identify fallback conditions**: When should the teaching-course path be used? Only when no direct affiliation exists?
4. **Test with edge cases**: Create test queries to verify exclusions (non-professors) and cardinality (no duplicates).

## Testing Procedure

```python
from rdflib import Graph

# Load the graph
g = Graph()
g.parse("university_graph.ttl", format="turtle")

# Load and execute the query
with open("solution.sparql") as f:
    query = f.read()

results = g.query(query)

# Validate
print(f"Result count: {len(results)}")
for row in sorted(results, key=lambda r: str(r.professorName)):
    print(f"{row.professorName} -> {row.universityName}")

# Check for duplicates
from collections import Counter
pairs = [(str(r.professorName), str(r.universityName)) for r in results]
duplicates = [p for p, count in Counter(pairs).items() if count > 1]
if duplicates:
    print(f"ERROR: Duplicate pairs found: {duplicates}")
```
