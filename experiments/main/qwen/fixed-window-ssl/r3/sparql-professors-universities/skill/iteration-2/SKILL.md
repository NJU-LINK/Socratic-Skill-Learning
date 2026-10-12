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

### Step 1: Systematic Graph Discovery Protocol

**Critical:** Before writing any query, you MUST systematically discover the ontology structure. Do not assume predicate names. Use this discovery protocol:

**A. Discover all classes and predicates:**
```python
from rdflib import Graph, RDF
g = Graph()
g.parse("university_graph.ttl", format="turtle")

# Find all classes (rdf:type targets)
classes = set(str(o) for s, p, o in g.triples((None, RDF.type, None)))

# Find all predicates
predicates = set(str(p) for s, p, o in g)
```

**B. Identify role/rank predicates:**
```python
role_predicates = [p for p in predicates if any(x in p.lower() for x in ["role", "rank", "position", "title", "appointment"])]
```

**C. Identify affiliation predicates:**
```python
affil_predicates = [p for p in predicates if any(x in p.lower() for x in ["work", "affil", "employ", "member", "partof", "belongs"])]
```

**D. Identify teaching/instruction predicates:**
```python
teach_predicates = [p for p in predicates if any(x in p.lower() for x in ["teach", "instruct", "course", "lectur"])]
```

**E. Identify name predicates:**
```python
name_predicates = [p for p in predicates if any(x in p.lower() for x in ["name", "label", "title"])]
```

**F. Sample instances to understand structure:**
```python
# Find Person instances
persons = [s for s, p, o in g.triples((None, RDF.type, None)) if "Person" in str(o)]

# Sample a few to see their properties
for person in persons[:3]:
    for p, o in g.predicate_objects(person):
        print(f"{p} -> {o}")
```

This discovery process reveals the actual predicates used in the variant, which you then map to the patterns below.

**G. Map discovered predicates to patterns:**
Once you've discovered the predicates, map them:
- Role/rank predicate → use in Professor Identification (Step 2)
- Affiliation predicate(s) → use in Affiliation Path (Step 3)
- Teaching predicate(s) → use as fallback in Affiliation Path (Step 3)
- Name predicate → use in projection (Step 4)

Example mapping:
```
Discovered: uni:role, uni:worksAt, uni:partOfUniversity, uni:teaches, uni:hasName
Mapped to:
  - uni:role → Professor identification (Pattern A)
  - uni:worksAt → Primary affiliation path
  - uni:partOfUniversity → Department-to-university link
  - uni:teaches → Fallback affiliation path
  - uni:hasName → Name projection
```

**H. Discover organization chain depth and direction:**
Variants may use different containment structures. Check:

```python
# Find containment predicates (partOf, hasMember, etc.)
containment_preds = [p for p in predicates if any(x in p.lower() for x in ["partof", "hasdepartment", "hasfaculty", "memberof", "contains"])]

# Check chain depth: sample a department and trace upward
for dept in [s for s, p, o in g.triples((None, RDF.type, None)) if "Department" in str(o)][:1]:
    print(f"\nDepartment: {dept}")
    # Trace upward (partOfUniversity)
    for p, o in g.predicate_objects(dept):
        if "partof" in str(p).lower():
            print(f"  {p} -> {o}")
            # Check if intermediate has another partOfUniversity
            for p2, o2 in g.predicate_objects(o):
                if "partof" in str(p2).lower():
                    print(f"    {p2} -> {o2}")
    
    # Check for inverse containment (University hasDepartment)
    for s, p, o in g.triples((None, None, dept)):
        if "hasdepartment" in str(p).lower() or "hasfaculty" in str(p).lower():
            print(f"  Inverse: {s} {p} -> {o}")
```

This reveals:
- **Depth**: Is it 1-hop (dept → university) or 2+ hops (dept → faculty → university)?
- **Direction**: Does the chain go UP via `partOfUniversity` or DOWN via `hasDepartment`?
- **Heterogeneity**: Are there mixed predicates (e.g., `partOfUniversity` then `partOfFaculty`)?

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
# Path A: worksAt -> department -> partOfUniversity (1-hop)
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .

# Path B: worksAt directly to University
?person uni:worksAt ?uni .
?uni a uni:University .

# Path C: worksAt -> department -> partOfUniversity+ (variable-depth chain)
# Handles 1-hop, 2-hop, and longer chains (e.g., dept -> faculty -> university)
?person uni:worksAt ?dept .
?dept uni:partOfUniversity+ ?uni .
?uni a uni:University .

# Path D: Inverse containment (University hasDepartment)
# For variants where the university points down to the department
?person uni:worksAt ?dept .
?uni uni:hasDepartment ?dept .
?uni a uni:University .
```

**Combine all preferred paths with UNION:**
```sparql
{
    # Path A: 1-hop containment
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
} UNION {
    # Path B: direct affiliation
    ?person uni:worksAt ?uni .
    ?uni a uni:University .
} UNION {
    # Path C: variable-depth containment (1-hop, 2-hop, longer)
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity+ ?uni .
    ?uni a uni:University .
} UNION {
    # Path D: inverse containment
    ?person uni:worksAt ?dept .
    ?uni uni:hasDepartment ?dept .
    ?uni a uni:University .
}
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

**Combine preferred paths with fallback using UNION:**
```sparql
{
    # Preferred paths (any of these)
    {
        ?person uni:worksAt ?dept .
        ?dept uni:partOfUniversity ?uni .
    } UNION {
        ?person uni:worksAt ?uni .
        ?uni a uni:University .
    } UNION {
        ?person uni:worksAt ?dept .
        ?dept uni:partOfUniversity+ ?uni .
        ?uni a uni:University .
    } UNION {
        ?person uni:worksAt ?dept .
        ?uni uni:hasDepartment ?dept .
        ?uni a uni:University .
    }
} UNION {
    # Fallback: only when no worksAt exists
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

5. **Professor-like near misses:** Variants may introduce roles like "Professor of
   Practice" (adjunct, may not be a real professor), "Visiting Professor" (temporary),
   or "Professorship Administrator" (staff, not a professor). CONTAINS("Professor")
   will match all of these. If the task specifies which ranks qualify, use more
   specific filters:
   ```sparql
   FILTER(CONTAINS(?role, "Professor") && !CONTAINS(?role, "Administrator"))
   ```
   Or use explicit enumeration if the variant defines exact rank labels:
   ```sparql
   FILTER(?role IN ("Professor", "Assistant Professor", "Associate Professor"))
   ```

6. **Variant name predicates:** The university name might be stored with different
   predicates: `uni:hasName`, `rdfs:label`, `uni:name`, `uni:universityName`, etc.
   Use the discovery protocol to find the correct predicate. If multiple exist,
   prefer the one used for University instances.

7. **Missing rdf:type assertions:** Some variants may not use `a uni:Person`.
   Instead, identify professors by the presence of role/rank predicates:
   ```sparql
   ?person uni:role ?role .
   FILTER(CONTAINS(?role, "Professor"))
   # No need for ?person a uni:Person
   ```

8. **Determining preference vs fallback:** When the variant uses unfamiliar
   predicates, determine preference by examining the data:
   - If a person has both a direct affiliation link AND a teaching link to
     different universities, the direct affiliation is likely the primary one.
   - Check which predicate is used more consistently across persons.
   - The task instruction may hint at the preferred path (e.g., "works at" vs
     "teaches at").
   - When in doubt, prefer the predicate that links directly to an organization
     over one that links through a course.

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

    # Affiliation with preference and fallback
    {
        # Preferred paths (any of these)
        {
            # Path A: 1-hop containment
            ?person uni:worksAt ?dept .
            ?dept uni:partOfUniversity ?uni .
        } UNION {
            # Path B: direct affiliation
            ?person uni:worksAt ?uni .
            ?uni a uni:University .
        } UNION {
            # Path C: variable-depth containment
            ?person uni:worksAt ?dept .
            ?dept uni:partOfUniversity+ ?uni .
            ?uni a uni:University .
        } UNION {
            # Path D: inverse containment
            ?person uni:worksAt ?dept .
            ?uni uni:hasDepartment ?dept .
            ?uni a uni:University .
        }
    } UNION {
        # Fallback: only when no worksAt exists
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
