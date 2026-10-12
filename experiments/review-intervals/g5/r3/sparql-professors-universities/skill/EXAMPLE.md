# Example: Applying the Skill to v01

This example demonstrates how the schema-discovery procedure from SKILL.md
produces the correct query for the v01 task.

## Input

Turtle file at `/app/university_graph.ttl` containing:
- 9 universities
- 11 departments
- 9 courses
- 7 professors (2 Assistant Professors, 5 Full Professors)
- 1 Lecturer (non-qualifying)
- 3 Students (non-qualifying)

## Discovery Process

### Step 1a: How are professor roles represented?

**Probe query:**
```sparql
SELECT DISTINCT ?pred WHERE {
  ?person a uni:Person ; ?pred ?val .
  FILTER(isLiteral(?val))
}
```

**Result:** Found `uni:role` with string values like:
- "Professor of Computer Science" ✓
- "Assistant Professor of Computer Science" ✓
- "Lecturer" ✗
- "Student" ✗

**Decision:** Use Pattern A (string-valued role filter)

### Step 1b: How does Person connect to University?

**Probe query:**
```sparql
SELECT DISTINCT ?p1 ?p2 WHERE {
  ?person a uni:Person .
  ?person ?p1 ?mid .
  ?mid ?p2 ?uni .
  ?uni a uni:University .
}
```

**Result:** Found 2-hop path:
- `uni:worksAt` → `uni:partOfUniversity`

**Decision:** Use two-hop affiliation path

### Step 1c: How is university name stored?

**Probe query:**
```sparql
SELECT DISTINCT ?pred WHERE {
  ?uni a uni:University ; ?pred ?name .
  FILTER(isLiteral(?name))
}
```

**Result:** Found `uni:hasName`

**Decision:** Use `uni:hasName` for university name

## Constructed Query

Based on discoveries, the skill produces:

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role ;
          uni:worksAt ?dept .
  
  ?dept uni:partOfUniversity ?uni .
  ?uni uni:hasName ?universityName .
  
  FILTER(REGEX(LCASE(?role), "(^|[^a-zA-Z])prof"))
}
```

## Results

| Professor Name | University Name |
|----------------|-----------------|
| Alex Morgan | National Technical University of Athens |
| Thomas Berger | National Technical University of Athens |
| Felix Wagner | Instituto Superior Técnico |
| Martin Keller | National and Kapodistrian University of Athens |
| John Smith | Massachusetts Institute of Technology |
| Marie Dubois | Sorbonne University |
| Stefan Mueller | Ludwig Maximilian University of Munich |

**Total:** 7 professors (correct)

## Validation

✓ No lecturers/students in results  
✓ No duplicates (DISTINCT working correctly)  
✓ Both variables bound for all rows  
✓ All expected professors found  

## Key Observations

1. **Assistant Professors included**: "Assistant Professor of Computer Science" 
   contains "professor", so it passes the filter (correct per spec).

2. **Lecturer excluded**: "Lecturer" does not contain "professor", correctly filtered out.

3. **Students excluded**: "Student" does not contain "professor", correctly filtered out.

4. **DISTINCT necessary**: Felix Wagner teaches both Math101 and AI101, which 
   would cause duplicates without DISTINCT.

5. **Prefix matching**: The query uses the same `uni:` prefix as the TTL file.
