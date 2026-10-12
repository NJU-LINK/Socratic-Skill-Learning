---
name: sparql-professors-universities
description: >
  Construct SPARQL queries that retrieve professor names paired with their
  university names from a Turtle knowledge graph. Provides a systematic
  predicate-discovery methodology to handle variation in how professors are
  identified (string roles vs. resource-based academic ranks), how affiliation
  chains connect people to universities (direct links, department intermediaries,
  appointment resources, teaching fallbacks), and varying levels of graph noise
  (duplicate bindings, multiple departments, non-professor distractors).
---

# SPARQL Professors–Universities Query Construction

## Task Shape

Given a Turtle (`.ttl`) file containing ontology + instance data for a university knowledge graph, produce a SPARQL query that:

1. Identifies all qualifying professors
2. For each, retrieves the name of the university they work at
3. Returns exactly two variables: `?professorName` and `?universityName`
4. Produces exactly one row per professor–university pair (no duplicates)

## General Procedure

### Step 0: Predicate Discovery (CRITICAL for variants)

**Before writing any SPARQL, systematically discover the actual predicates in the data.** Do not assume predicate names — variants use different namespaces and property names.

#### Method A: rdflib-based discovery (preferred when available)
```python
from rdflib import Graph, URIRef, RDF

g = Graph()
g.parse("path/to/graph.ttl", format="turtle")

# Extract all unique predicates
predicates = sorted(set(str(p) for s, p, o in g))

# Categorize by semantic role
name_preds = [p for p in predicates if 'name' in p.lower() or 'label' in p.lower()]
role_preds = [p for p in predicates if 'role' in p.lower() or 'rank' in p.lower() or 'position' in p.lower()]
affil_preds = [p for p in predicates if 'work' in p.lower() or 'affiliat' in p.lower() or 
               'employ' in p.lower() or 'member' in p.lower() or 'partof' in p.lower()]
teach_preds = [p for p in predicates if 'teach' in p.lower() or 'course' in p.lower()]

# Discover classes
classes = sorted(set(str(o) for s, p, o in g if p == RDF.type))

# Count person instances
person_class = [c for c in classes if 'person' in c.lower()][0] if any('person' in c.lower() for c in classes) else None
if person_class:
    persons = list(g.subjects(RDF.type, URIRef(person_class)))
    print(f"Total persons: {len(persons)}")
```

#### Method B: Text-based discovery (when rdflib unavailable)
```bash
# Extract all predicates (lines with a predicate between subject and object)
grep -oP '(?<=\s)[a-zA-Z]+:[a-zA-Z]+(?=\s)' university_graph.ttl | sort -u

# Extract all class declarations
grep -oP '(?<=a\s)[a-zA-Z]+:[a-zA-Z]+(?=\s*[;,])' university_graph.ttl | sort -u

# Extract prefix declarations
grep '@prefix' university_graph.ttl
```

#### What to discover:
1. **Namespace prefix**: What prefix maps to the ontology? (e.g., `uni:` → `http://university.org/ontology#`)
2. **Person class**: What class represents people? (e.g., `uni:Person`, `foaf:Person`)
3. **Name predicate**: How are names stored? (e.g., `uni:hasName`, `foaf:name`, `rdfs:label`)
4. **Role/rank predicate**: How is academic rank represented? (e.g., `uni:role`, `uni:hasAcademicRank`)
5. **Affiliation predicates**: How do people link to organizations? (e.g., `uni:worksAt`, `uni:affiliatedWith`, `uni:employedBy`)
6. **Organization hierarchy**: How do departments link to universities? (e.g., `uni:partOfUniversity`, `uni:hasUniversity`)
7. **Teaching predicates**: How do people link to courses? (e.g., `uni:teaches`, `uni:instructorOf`)

### Step 1: Determine Professor Identification (Axis 1)

Using the discovered role/rank predicate, choose the appropriate pattern:

#### Pattern A: String-valued role property
```sparql
?person <rolePredicate> ?role .
FILTER(CONTAINS(?role, "Professor"))
```
- Works when roles are literal strings like `"Professor of Computer Science"` or `"Assistant Professor of Mathematics"`
- `CONTAINS` is case-sensitive in SPARQL — verify capitalization in the data
- This matches both "Professor" and "Assistant Professor" while excluding "Lecturer", "Student", etc.
- **Pitfall**: If the data contains role strings like "Professor Emeritus" or "Associate Professor" that should or shouldn't be included, adjust the filter accordingly
- **Pitfall**: A role like "Visiting Professor" may or may not qualify — check task instructions

#### Pattern B: Resource-based academic rank
```sparql
?person <rankPredicate> ?rank .
?rank <rankLabelPredicate> ?rankLabel .
FILTER(CONTAINS(?rankLabel, "Professor"))
```
- Used when rank is modeled as a resource rather than a plain string
- The rank resource may have a `rdf:type` (e.g., `uni:FullProfessor`, `uni:AssistantProfessor`) instead of or in addition to a label

#### Pattern C: Type-based classification
```sparql
?person a <ProfessorClass> .
# or
?person a <FullProfessorClass> .
# or UNION of professor types
```

#### Robust combined pattern (when uncertain):
```sparql
{
  ?person <rolePredicate> ?role .
  FILTER(CONTAINS(?role, "Professor"))
}
UNION
{
  ?person <rankPredicate> ?rank .
  ?rank <rankLabelPredicate> ?rankLabel .
  FILTER(CONTAINS(?rankLabel, "Professor"))
}
```

### Step 2: Determine Affiliation Chain (Axis 2)

Using the discovered affiliation predicates, link each professor to their university name:

#### Pattern A: Person → Department → University (most common in seed)
```sparql
?person <worksAtPredicate> ?dept .
?dept <partOfUniversityPredicate> ?uni .
?uni <namePredicate> ?universityName .
```

#### Pattern B: Direct person → university link
```sparql
?person <affiliatedWithPredicate> ?uni .
?uni <namePredicate> ?universityName .
```

#### Pattern C: Via appointment resource
```sparql
?person <hasAppointmentPredicate> ?appt .
?appt <atOrganizationPredicate> ?uni .
?uni <namePredicate> ?universityName .
```

#### Pattern D: Teaching-course fallback
When the primary affiliation predicate may be absent for some professors, use a fallback through courses they teach:
```sparql
{
  ?person <worksAtPredicate> ?dept .
  ?dept <partOfUniversityPredicate> ?uni .
}
UNION
{
  ?person <teachesPredicate> ?course .
  ?course <isTaughtInPredicate> ?dept .
  ?dept <partOfUniversityPredicate> ?uni .
}
?uni <namePredicate> ?universityName .
```
**Critical**: When using UNION or multiple paths, `SELECT DISTINCT` becomes essential to avoid duplicate rows.

#### Pattern E: Inverse containment
```sparql
?uni <hasDepartmentPredicate> ?dept .
?dept <hasMemberPredicate> ?person .
```

#### Pattern F: Preferred path with OPTIONAL + COALESCE fallback
When the spec says "preferred worksAt path with a teaching-course fallback when the preferred relation is absent", use OPTIONAL blocks with COALESCE instead of UNION:
```sparql
OPTIONAL {
  ?person <worksAtPredicate> ?dept .
  ?dept <partOfUniversityPredicate> ?uniViaWorks .
}
OPTIONAL {
  ?person <teachesPredicate> ?course .
  ?course <isTaughtInPredicate> ?dept2 .
  ?dept2 <partOfUniversityPredicate> ?uniViaTeaches .
}
BIND(COALESCE(?uniViaWorks, ?uniViaTeaches) AS ?uni)
?uni <namePredicate> ?universityName .
```
**Why this is better than UNION for fallbacks**: UNION produces a cross-product of all matching paths, generating duplicates that must be collapsed with DISTINCT. OPTIONAL + COALESCE is semantically "try the first path; if it fails, use the second" — no duplicates are generated in the first place. COALESCE returns the first bound (non-error) value from its arguments.

**Generalization**: This pattern applies to any "preferred relation with fallback" scenario across any axis — e.g., preferred name predicate with a label fallback, or preferred rank property with a type-based fallback.

### Step 3: Handle Noise and Cardinality (Axis 3)

- **Multiple courses per professor**: If a professor teaches N courses and your query joins through the teaching predicate, you get N rows. Use `SELECT DISTINCT` to collapse.
- **Multiple departments per university**: A professor might have appointments in multiple departments of the same university. `SELECT DISTINCT` handles this.
- **Non-professor distractors**: Students, lecturers, postdocs, administrative staff — all may have affiliation or teaching properties. The professor filter (Step 1) must exclude them.
- **Overlapping organization paths**: Ensure the chain leads to a university class (or equivalent), not just any organization.

### Step 4: Assemble and validate

Template:
```sparql
PREFIX <prefix>: <namespace>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a <PersonClass> ;
          <namePredicate> ?professorName ;
          <professorIdentificationPattern> .
  <affiliationChain> .
  <universityNameBinding> .
}
```

**Validation checklist**:
1. Count expected professors manually from the TTL file
2. Verify no non-professors appear in results
3. Verify no professors are missing
4. Verify each professor appears exactly once
5. Verify university names match expected values
6. Run the query programmatically (see below)

## Programmatic Testing

### Basic validation script
```python
from rdflib import Graph

g = Graph()
g.parse("path/to/graph.ttl", format="turtle")

with open("solution.sparql") as f:
    query = f.read()

results = g.query(query)
rows = sorted(results, key=lambda r: str(r[0]))

print(f"Result count: {len(rows)}")
for row in rows:
    print(f"  {row[0]} → {row[1]}")
```

### Comprehensive validation script
```python
from rdflib import Graph, URIRef, RDF

g = Graph()
g.parse("path/to/graph.ttl", format="turtle")

with open("solution.sparql") as f:
    query = f.read()

results = g.query(query)
rows = list(results)

# Check result count
print(f"Result count: {len(rows)}")

# Check for duplicates
unique_rows = set((str(r[0]), str(r[1])) for r in rows)
assert len(rows) == len(unique_rows), f"Found {len(rows) - len(unique_rows)} duplicate rows!"

# Check that all results are actually professors (manual verification)
# This requires knowing which persons are professors from the data
print("\nAll results:")
for row in sorted(rows, key=lambda r: str(r[0])):
    print(f"  {row[0]} → {row[1]}")

# Check that no professors are missing (requires manual count from TTL)
# Count persons with "Professor" in their role
prof_count = 0
for s, p, o in g:
    if 'role' in str(p).lower() and 'Professor' in str(o):
        prof_count += 1
print(f"\nExpected professor count (from role filter): {prof_count}")
assert len(rows) == prof_count, f"Result count {len(rows)} != expected {prof_count}"

print("\n✓ All validation checks passed")
```

If `rdflib` is not installed, try `python3 -c "import rdflib"` first — it may already be available. If truly unavailable, validate by manual inspection of the TTL data.

## Decision Tree

When uncertain which pattern to use, follow this decision tree:

```
1. Does the task specify the exact predicates to use?
   YES → Use those predicates directly
   NO → Go to Step 0 (Predicate Discovery)

2. After discovery, how is professor rank represented?
   - String literal (e.g., "Professor of X") → Pattern A (CONTAINS filter)
   - Resource with label → Pattern B (join to rankLabel)
   - RDF type (e.g., a uni:Professor) → Pattern C (type check)
   - Unclear → Use robust combined pattern (UNION of A and B)

3. How do people link to universities?
   - Direct link (person → university) → Pattern B
   - Via department (person → dept → university) → Pattern A
   - Via appointment resource → Pattern C
   - Via teaching (person → course → dept → university) → Pattern D
   - Multiple possible paths → Pattern F (OPTIONAL + COALESCE)

4. Are there duplicate-binding risks?
   - Professor teaches multiple courses → Use SELECT DISTINCT
   - Professor in multiple departments → Use SELECT DISTINCT
   - Multiple paths in UNION → Use SELECT DISTINCT
   - Using OPTIONAL + COALESCE → No DISTINCT needed (already unique)
```

## v01 Concrete Reference

For the seed task with the given `university_graph.ttl`:
- Prefix: `uni:` → `http://university.org/ontology#`
- Person class: `uni:Person`
- Name: `uni:hasName`
- Professor ID: `uni:role` string containing "Professor"
- Affiliation: `uni:worksAt` → department → `uni:partOfUniversity` → `uni:hasName`
- Expected: 7 professors (Alex Morgan, Thomas Berger, Felix Wagner, Martin Keller, John Smith, Marie Dubois, Stefan Mueller)
- Excluded: Jane Petterson (Lecturer), 3 Students
