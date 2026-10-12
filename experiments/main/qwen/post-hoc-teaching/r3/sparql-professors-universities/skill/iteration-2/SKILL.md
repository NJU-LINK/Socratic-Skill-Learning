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

## General Method

### Step 0: Read the Task Instruction Carefully

The task instruction in `task.yaml` contains critical hints:
- **Which roles qualify**: e.g., "two kinds of professors: Assistant Professors and Full Professors"
- **How role is encoded**: e.g., "uni:role property... in the form of a string"
- **Output variables**: always `?professorName` and `?universityName`
- **Assumptions**: e.g., "each professor works at exactly one university"

Extract these before touching the data. They constrain what to look for.

### Step 1: Run the Discovery Script

An integrated discovery script is available at `discover_ontology.py` (in the skill package). It parses the Turtle file and outputs:
- Namespace prefix
- All classes and instance counts
- All predicates
- Person properties (sample)
- All distinct role/rank values with professor classification
- University name predicate
- Affiliation path pattern (direct, two-hop, or inverse)

```bash
python3 /skill/discover_ontology.py
```

If the script is unavailable, run the manual discovery steps below.

### Step 2: Identify the Professor Qualification Mechanism

From the discovery output, determine how professor status is encoded:

**Pattern A — String-valued role property** (seed v01):
- A predicate like `uni:role` with string literal values
- Filter with regex: `FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))`
- This matches "Professor of X", "Assistant Professor", "Visiting Professor", etc.
- Excludes "Lecturer", "Student", "Staff", and crucially "Professorial Lecturer"

**Pattern B — Resource-based academic rank**:
- A predicate like `uni:hasAcademicRank` pointing to a rank resource
- The rank resource has a label (e.g., `uni:rankLabel`)
- Filter the label with the same regex

**Why this regex?** The pattern `(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])` matches "professor" only when bounded by non-letter characters (start/end of string, whitespace, punctuation). This correctly:
- ✓ Matches: "Professor of CS", "Assistant Professor", "Professor, Emeritus"
- ✗ Rejects: "Professorial Lecturer" (the "i" after "professor" is a letter)
- ✗ Rejects: "Lecturer", "Student", "Staff"

**⚠ CRITICAL: Enumerate-Before-You-Filter**

Before finalizing the filter, verify every distinct value against your classification:

```sparql
SELECT DISTINCT ?role WHERE { ?person ?rolePred ?role }
```

Build a decision table:

| Role value                  | Should match? | Regex matches? | Correct? |
|-----------------------------|---------------|----------------|----------|
| Professor of CS             | YES           | YES            | ✓        |
| Assistant Professor of CS   | YES           | YES            | ✓        |
| Lecturer                    | NO            | NO             | ✓        |
| Student                     | NO            | NO             | ✓        |
| **Professorial Lecturer**   | **NO**        | **NO**         | ✓        |
| Visiting Professor          | YES           | YES            | ✓        |

If any value is misclassified, adjust the filter (use explicit value list or negation).

### Step 3: Trace the Affiliation Path to University

From the discovery script output, identify how persons connect to universities:

**Pattern A — Department chain** (seed v01):
```sparql
?person ?worksAtPred ?dept .
?dept ?partOfPred ?uni .
```

**Pattern B — Direct affiliation**:
```sparql
?person ?affiliationPred ?uni .
```

**Pattern C — Appointment resource**:
```sparql
?person ?hasApptPred ?appt .
?appt ?atOrgPred ?uni .
```

**Pattern D — Inverse containment**:
```sparql
?uni ?hasEmployeePred ?person .
```

**Pattern E — Teaching-course fallback** (when primary path is absent for some):
```sparql
{ ?person ?worksAt ?org . ?org ?partOf ?uni . }
UNION
{ ?person ?teaches ?course . ?course ?taughtIn ?dept . ?dept ?partOf ?uni .
  FILTER NOT EXISTS { ?person ?worksAt ?anyDept . } }
```

The discovery script probes all patterns and reports which one(s) yield results.

### Step 4: Find the University Name Predicate

From the discovery output, identify the predicate that stores university names. Common patterns:
- `uni:hasName` (seed v01)
- `rdfs:label`
- `foaf:name`

### Step 5: Construct the SPARQL Query

Assemble using discovered components. Template:

```sparql
PREFIX <prefix>: <namespace_uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName ;
            <prefix>:<rolePred> ?role .
    FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    # Affiliation path (adapt to discovered pattern)
    ?person <prefix>:<worksAtPred> ?dept .
    ?dept <prefix>:<partOfPred> ?uni .

    ?uni <prefix>:<uniNamePred> ?universityName .
}
ORDER BY ?professorName
```

Replace `<prefix>`, `<namePred>`, `<rolePred>`, `<worksAtPred>`, `<partOfPred>`, `<uniNamePred>` with values from the discovery output.

**Critical: Use `SELECT DISTINCT`** to ensure exactly one row per professor-university pair, even when:
- A professor works at multiple departments within the same university
- A professor teaches multiple courses in the same department
- Multiple paths lead to the same university

### Step 6: Validate

Run the query against the graph:

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

Check:
- No students, lecturers, or staff appear
- All professors appear exactly once
- University names are human-readable strings (not URIs)
- Row count matches expectations from the task instruction

## Handling UNION/Fallback Patterns

When the task specifies a primary path with a fallback (e.g., worksAt preferred, teaching-course as fallback when worksAt is absent), use:

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName .
    ?person <prefix>:<rolePred> ?role .
    FILTER(REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    {
        ?person <prefix>:<worksAt> ?dept .
        ?dept <prefix>:<partOf> ?uni .
    } UNION {
        ?person <prefix>:<teaches> ?course .
        ?course <prefix>:<taughtIn> ?dept .
        ?dept <prefix>:<partOf> ?uni .
        FILTER NOT EXISTS { ?person <prefix>:<worksAt> ?anyDept . }
    }

    ?uni <prefix>:<uniNamePred> ?universityName .
}
```

## Handling Resource-Based Rank

When professors are identified via academic rank resources rather than string roles:

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a <prefix>:Person ;
            <prefix>:<namePred> ?professorName ;
            <prefix>:<rankPred> ?rank .
    ?rank <prefix>:<rankLabelPred> ?rankLabel .
    FILTER(REGEX(?rankLabel, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])"))

    ?person <prefix>:<worksAt> ?dept .
    ?dept <prefix>:<partOf> ?uni .
    ?uni <prefix>:<uniNamePred> ?universityName .
}
```

## Common Pitfalls

1. **Missing DISTINCT**: Without it, a professor teaching 2 courses in the same department yields 2 rows.
2. **Exact match on role**: `?role = "Professor"` misses "Assistant Professor of X". Use regex with non-letter boundaries.
3. **Hardcoded namespace**: Always read the `@prefix` from the Turtle file; the namespace URI may change between variants.
4. **Wrong name predicate**: The university name might be `rdfs:label` instead of `uni:hasName`.
5. **Over-matching with substring filters**: `CONTAINS(LCASE(?role), "professor")` matches "professorial" because "professor" is a substring of "professorial". This means "Professorial Lecturer" would be a false positive. Use `REGEX(?role, "(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])")` which requires non-letter boundaries.
6. **Ignoring the task instruction**: The instruction text specifies which roles qualify. Always read it first.
7. **Not enumerating distinct values**: Before writing any filter, enumerate all distinct values and verify each is correctly included/excluded.

## Validation Suite

The skill has been validated against synthetic test cases covering all spec variation axes:

### Test Cases

1. **Near-miss title** (professor_identification_semantics axis)
   - Tests: "Professorial Lecturer" should be excluded
   - Regex: `(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])` correctly rejects it
   - Result: ✓ PASS

2. **Resource-based rank** (professor_identification_semantics axis)
   - Tests: `hasAcademicRank` → `rankLabel` pattern
   - Discovery script detects resource-based rank and follows to label
   - Result: ✓ PASS

3. **Direct affiliation** (affiliation_structure_to_university axis)
   - Tests: Person directly affiliated with University (no department)
   - Discovery script detects direct pattern
   - Result: ✓ PASS

4. **Punctuation boundaries** (professor_identification_semantics axis)
   - Tests: "Professor," and "Professor." (punctuation after)
   - Regex correctly handles non-letter boundaries
   - Result: ✓ PASS

5. **Teaching-course fallback** (affiliation_structure_to_university axis)
   - Tests: UNION pattern when worksAt is absent
   - Query finds professors via teaches → course → department → university
   - Result: ✓ PASS

6. **Graph noise** (graph_noise_and_result_cardinality axis)
   - Tests: Multiple departments, multiple courses, non-professors
   - SELECT DISTINCT ensures exactly 1 row per professor-university pair
   - Result: ✓ PASS

### Validation Procedure

To validate the skill against a new variant:

1. **Create minimal synthetic TTL** (5-10 triples) exercising the pattern
2. **Run discovery script**: `python3 /skill/discover_ontology.py variant.ttl`
3. **Verify detection**: Check that the script identifies the correct pattern
4. **Construct query**: Use the skill's template with discovered predicates
5. **Verify results**: Check that the query returns expected professors

This converts "I believe this handles all variants" into "I have evidence this handles all variants."

## Checklist Before Submitting

- [ ] Read the task instruction and extracted professor qualification criteria
- [ ] Ran discovery script (or manual discovery) to understand graph structure
- [ ] Identified the namespace prefix from `@prefix` declarations
- [ ] Identified how professor status is encoded (string role vs. resource rank)
- [ ] **Enumerated all distinct role/rank values; built decision table; verified no false positives**
- [ ] Traced the affiliation path from Person to University
- [ ] Found the university name predicate
- [ ] Used `SELECT DISTINCT` for cardinality
- [ ] Used regex with non-letter boundaries for professor matching
- [ ] Validated query against the graph with rdflib
- [ ] Saved query to `/app/solution.sparql`
