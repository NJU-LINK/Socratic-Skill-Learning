---
name: sparql-professors-universities
description: >
  Construct SPARQL queries that retrieve professor names and their affiliated
  university names from a Turtle knowledge graph. Handles variation in how
  professor roles are represented (string-valued role predicates vs. linked
  academic-rank resources), how persons connect to universities (direct
  affiliation, multi-hop department chains, or teaching-course fallbacks), and
  graph noise that can cause duplicate bindings.
---

# SPARQL Professors–Universities Query Construction

## Quick Decision Tree

```
1. How are professors identified?
   ├─ String role (e.g., uni:role "Professor of X") → Pattern A
   ├─ Resource rank (e.g., uni:hasAcademicRank → uni:rankLabel) → Pattern B
   └─ Both/unknown → Pattern C (UNION)

2. How does Person connect to University?
   ├─ Direct (e.g., uni:affiliatedWith) → 1-hop
   ├─ Via department (e.g., uni:worksAt → uni:partOfUniversity) → 2-hop
   └─ Missing for some → Add teaching-course fallback (UNION)

3. What predicate gives university name?
   ├─ uni:hasName (most common)
   ├─ uni:name
   └─ rdfs:label
```

## Discovery: Two Approaches

Choose based on file size and complexity:

### Approach A: Text Inspection (small files < 500 lines)
For small TTL files, directly inspect the file:
```bash
# Find role predicates and values
grep -n "role\|Person\|Professor" /app/university_graph.ttl | head -30

# Find affiliation patterns
grep -n "worksAt\|partOfUniversity\|affiliatedWith" /app/university_graph.ttl | head -20

# Find university name predicates
grep -n "hasName\|University" /app/university_graph.ttl | head -20
```

### Approach B: SPARQL Probes (large files or complex structure)
For large TTL files or when text inspection is unclear, run these SPARQL queries:

#### Probe 1: Role representation
```sparql
SELECT DISTINCT ?pred WHERE {
  ?person a uni:Person ; ?pred ?val .
  FILTER(isLiteral(?val))
}
```
If you find `uni:role` or similar with string values containing "professor" → **Pattern A**

#### Probe 2: Affiliation path
```sparql
SELECT DISTINCT ?p1 ?p2 WHERE {
  ?person a uni:Person .
  ?person ?p1 ?mid .
  ?mid ?p2 ?uni .
  ?uni a uni:University .
}
```
This reveals the 2-hop path (e.g., `worksAt` → `partOfUniversity`)

#### Probe 3: University name predicate
```sparql
SELECT DISTINCT ?pred WHERE {
  ?uni a uni:University ; ?pred ?name .
  FILTER(isLiteral(?name))
}
```

## Query Patterns

### Pattern A: String-valued role (most common)
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          <AFFILIATION_PATH> .
  
  ?uni <NAME_PREDICATE> ?universityName .
  
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
```

**Replace** `<AFFILIATION_PATH>` and `<NAME_PREDICATE>` with values discovered in Step 1 (e.g., `uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni` and `uni:hasName`).

**Filter:** `(^|[^a-zA-Z])prof` matches "prof" at start or after non-letter (handles "Prof.", "Prof", "Professor", etc.)

**Fallback filter** (if regex unsupported):
```sparql
FILTER(CONTAINS(LCASE(?role), "professor") || 
       CONTAINS(LCASE(?role), "prof.") || 
       CONTAINS(LCASE(?role), "prof ") ||
       STRSTARTS(LCASE(?role), "prof"))
```

### Pattern B: Resource-based academic rank
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:hasAcademicRank ?rank ;
          <AFFILIATION_PATH> .
  
  ?rank uni:rankLabel ?rankLabel .
  ?uni <NAME_PREDICATE> ?universityName .
  
  FILTER(REGEX(LCASE(?rankLabel), "(^|[^a-zA-Z])prof"))
}
```

**Replace** `<AFFILIATION_PATH>` and `<NAME_PREDICATE>` with discovered values.

### Pattern C: UNION fallback (both patterns)
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          <AFFILIATION_PATH> .
  
  ?uni <NAME_PREDICATE> ?universityName .
  
  {
    ?person uni:role ?role .
    FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
  }
  UNION
  {
    ?person uni:hasAcademicRank ?rank .
    ?rank uni:rankLabel ?rankLabel .
    FILTER(REGEX(LCASE(?rankLabel), "(^|[^a-zA-Z])prof"))
  }
}
```

**Replace** `<AFFILIATION_PATH>` and `<NAME_PREDICATE>` with discovered values.

### Teaching-course fallback (if worksAt missing)
Add this UNION branch to the affiliation path:
```sparql
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
```

## Validation

After executing the query, run this check:
```python
python3 << 'EOF'
from rdflib import Graph
g = Graph().parse("/app/university_graph.ttl", format="turtle")
with open("/app/solution.sparql") as f:
    results = list(g.query(f.read()))
print(f"Found {len(results)} professors")
for row in sorted(results, key=lambda r: str(r.professorName)):
    print(f"  {row.professorName} → {row.universityName}")
EOF
```

**Check:**
- No lecturers/students in results
- No duplicates (DISTINCT working)
- Both variables bound for all rows

## Key Invariants

- **Always use `SELECT DISTINCT`** (professors teaching multiple courses cause duplicates)
- **Professor filter:** `(^|[^a-zA-Z])prof` (XPath-compatible, handles abbreviations)
- **Output variables:** `?professorName` and `?universityName`
- **Prefix must match TTL:** Check `@prefix uni:` in the file

## Common Pitfalls

1. **Hardcoding paths** — Always discover the actual affiliation structure
2. **Case-sensitive matching** — Always use `LCASE()` with regex
3. **Using `\b` word boundary** — Not XPath-compatible; use `(^|[^a-zA-Z])` instead
4. **Missing DISTINCT** — Multi-valued properties cause duplicates
5. **Wrong prefix** — Must match TTL's `@prefix` declaration
6. **Over-filtering** — "Assistant Professor" contains "professor" — include it
