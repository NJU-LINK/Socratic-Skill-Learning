---
name: sparql-professors-universities
description: >
  Construct a SPARQL query that retrieves all professors and the universities
  they work at from a Turtle knowledge graph. The skill handles variation in how
  professors are identified (string role vs. resource-based academic rank), how
  affiliation paths connect people to universities (direct links, department
  chains, appointment resources, or teaching-course fallbacks), and how graph
  noise and duplicate bindings are managed. Produces a .sparql file returning
  ?professorName and ?universityName with exactly one row per qualifying
  professor-university pair.
---

# SPARQL Professors-Universities Query Skill

## Task Invariants

Every member of this family shares these properties:

1. **Input**: A Turtle file at `/app/university_graph.ttl` containing ontology + instance data.
2. **Goal**: Write a SPARQL query returning `?professorName` and `?universityName`.
3. **Output**: Save the query to `/app/solution.sparql`.
4. **Cardinality invariant**: Exactly one row per qualifying professor-university pair.
5. **Exclusions**: Non-professor roles (lecturers, students, staff, etc.) must be excluded.

## Method

### Step 1: Read the Task Instruction

Extract from `task.yaml`:
- Which roles qualify (e.g., "Assistant Professors and Full Professors")
- How role is encoded (e.g., "uni:role property... in the form of a string")
- Output variables (always `?professorName` and `?universityName`)

### Step 2: Run the Discovery Script

```bash
python3 /skill/discover_ontology.py
```

This outputs:
- Namespace prefix
- Role/rank predicate and values (with professor classification)
- Affiliation path pattern
- University name predicate

### Step 3: Use the Decision Tree

Based on the discovery output, follow this decision tree:

**Q1: How is professor status encoded?**

- **String-valued role property** (e.g., `uni:role "Professor of CS"`) → Use **Template A**
- **Resource-based rank** (e.g., `uni:hasAcademicRank uni:FullProf` where `uni:FullProf uni:rankLabel "Full Professor"`) → Use **Template B**

**Q2: How do persons connect to universities?**

- **Department chain** (e.g., `?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni .`) → Use the affiliation block from **Template A**
- **Direct affiliation** (e.g., `?person uni:affiliatedWith ?uni .`) → Use the affiliation block from **Template C**
- **Teaching fallback** (some professors have `worksAt`, others only have `teaches`) → Use **Template D**

**Q3: What predicate stores university names?**

- Check discovery output for the predicate (e.g., `uni:hasName`, `rdfs:label`, `foaf:name`)

### Step 4: Construct the Query

Use the appropriate template below, substituting discovered predicates.

**Critical rules:**
- Always use `SELECT DISTINCT` to prevent duplicate rows
- Always use regex `(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])` for professor matching (not `CONTAINS`)
- Always enumerate distinct role/rank values first to verify no false positives

### Step 5: Validate

```bash
cd /app && python3 -c "
from rdflib import Graph
g = Graph().parse('university_graph.ttl', format='turtle')
with open('solution.sparql') as f:
    query = f.read()
results = list(g.query(query))
print(f'Total rows: {len(results)}')
for row in results:
    print(f'  {row.professorName} | {row.universityName}')
"
```

Verify:
- No students, lecturers, or staff appear
- All professors appear exactly once
- University names are human-readable strings (not URIs)

## Query Templates

### Template A: String Role + Department Chain (seed v01)

```sparql
PREFIX <prefix>: <namespace_uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName ;
            <prefix>:<rolePred> ?role .
    FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    ?person <prefix>:<worksAtPred> ?dept .
    ?dept <prefix>:<partOfPred> ?uni .

    ?uni <prefix>:<uniNamePred> ?universityName .
}
ORDER BY ?professorName
```

**Example substitutions for v01:**
- `<prefix>` = `uni`
- `<namespace_uri>` = `http://university.org/ontology#`
- `<namePred>` = `hasName`
- `<rolePred>` = `role`
- `<worksAtPred>` = `worksAt`
- `<partOfPred>` = `partOfUniversity`
- `<uniNamePred>` = `hasName`

### Template B: Resource-Based Rank + Department Chain

```sparql
PREFIX <prefix>: <namespace_uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName ;
            <prefix>:<rankPred> ?rank .
    ?rank <prefix>:<rankLabelPred> ?rankLabel .
    FILTER(REGEX(?rankLabel, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    ?person <prefix>:<worksAtPred> ?dept .
    ?dept <prefix>:<partOfPred> ?uni .

    ?uni <prefix>:<uniNamePred> ?universityName .
}
ORDER BY ?professorName
```

### Template C: String Role + Direct Affiliation

```sparql
PREFIX <prefix>: <namespace_uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName ;
            <prefix>:<rolePred> ?role .
    FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    ?person <prefix>:<affiliationPred> ?uni .

    ?uni <prefix>:<uniNamePred> ?universityName .
}
ORDER BY ?professorName
```

### Template D: String Role + Teaching Fallback

```sparql
PREFIX <prefix>: <namespace_uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName .
    ?person <prefix>:<rolePred> ?role .
    FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    {
        ?person <prefix>:<worksAtPred> ?dept .
        ?dept <prefix>:<partOfPred> ?uni .
    } UNION {
        ?person <prefix>:<teachesPred> ?course .
        ?course <prefix>:<taughtInPred> ?dept .
        ?dept <prefix>:<partOfPred> ?uni .
        FILTER NOT EXISTS { ?person <prefix>:<worksAtPred> ?anyDept . }
    }

    ?uni <prefix>:<uniNamePred> ?universityName .
}
ORDER BY ?professorName
```

## The Professor Regex

**Pattern:** `(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])`

**Why this regex?** It matches "professor" only when bounded by non-letter characters (start/end of string, whitespace, punctuation).

**Correct behavior:**
- ✓ Matches: "Professor of CS", "Assistant Professor", "Professor, Emeritus", "Professor."
- ✗ Rejects: "Professorial Lecturer" (the "i" after "professor" is a letter)
- ✗ Rejects: "Lecturer", "Student", "Staff"

**⚠ CRITICAL: Enumerate-Before-You-Filter**

Before finalizing the filter, verify every distinct value:

```sparql
SELECT DISTINCT ?role WHERE { ?person ?rolePred ?role }
```

Build a decision table and verify each value is correctly classified. If any value is misclassified, adjust the filter (use explicit value list or negation).

## Common Pitfalls

1. **Missing DISTINCT**: Without it, a professor teaching 2 courses yields 2 rows.
2. **Exact match on role**: `?role = "Professor"` misses "Assistant Professor of X". Use regex.
3. **Hardcoded namespace**: Always read the `@prefix` from the Turtle file.
4. **Wrong name predicate**: University name might be `rdfs:label` instead of `uni:hasName`.
5. **Over-matching with CONTAINS**: `CONTAINS(LCASE(?role), "professor")` matches "professorial". Use regex with non-letter boundaries.
6. **Not enumerating distinct values**: Always enumerate and verify before writing the filter.

## Checklist Before Submitting

- [ ] Read the task instruction and extracted professor qualification criteria
- [ ] Ran discovery script to understand graph structure
- [ ] Identified the namespace prefix
- [ ] Identified how professor status is encoded (string role vs. resource rank)
- [ ] **Enumerated all distinct role/rank values; verified no false positives**
- [ ] Traced the affiliation path from Person to University
- [ ] Found the university name predicate
- [ ] Used `SELECT DISTINCT` for cardinality
- [ ] Used regex with non-letter boundaries for professor matching
- [ ] Validated query against the graph with rdflib
- [ ] Saved query to `/app/solution.sparql`
