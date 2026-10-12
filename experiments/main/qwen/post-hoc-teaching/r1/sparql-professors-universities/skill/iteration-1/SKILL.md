---
name: sparql-professors-universities
description: >
  Write a SPARQL SELECT query over a Turtle knowledge graph to retrieve all
  qualifying professors and the universities they are affiliated with. The skill
  covers ontology discovery, professor identification (string-role matching or
  typed academic-rank resources), affiliation-path tracing (direct or via
  intermediate organizations/courses), noise handling, and correct variable
  projection with deduplication.
---

# SPARQL Professors–Universities Query Skill

## Task Summary

Given a Turtle file (typically at `/app/university_graph.ttl`) containing an
ontology and instance data about a university knowledge graph, produce a SPARQL
`SELECT` query that:

1. Identifies every **qualifying professor** in the graph.
2. For each professor, retrieves the **name of the university** they work at.
3. Returns exactly two variables: `?professorName` and `?universityName`.
4. Produces exactly one row per qualifying professor–university pair.
5. Saves the query to `/app/solution.sparql`.

## Step-by-Step Method

### Step 1: Discover the Ontology Structure

Before writing any query, **inspect the Turtle file** to understand:

- What **prefix/namespace** is used (e.g., `uni:`, `ex:`, `org:`).
- What **classes** exist (Person, University, Department, etc.).
- What **predicates** link people to roles/ranks and to organizations.
- What **literal properties** carry names.

Run an analysis script:

```python
import rdflib
g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# All predicates
predicates = sorted(set(str(p) for s, p, o in g))
# All rdf:type values
types = sorted(set(str(o) for s, p, o in g.triples((None, rdflib.RDF.type, None))))
# All role/rank values
# (search for any predicate containing "role" or "rank" in its local name)
```

This tells you the exact IRIs to use in the query.

### Step 2: Identify Professors

Professors can be identified in multiple ways depending on the variant:

#### Pattern A: String-valued role property (v01 seed)

The person has a `uni:role` (or similar) string property. Qualifying professors
have role strings where **"Professor" appears as a whole word** (case-insensitive).
This captures both "Professor of X" (full professors) and "Assistant Professor of X".

```sparql
?person uni:role ?role .
FILTER(REGEX(?role, "(^|\\s)Professor(\\s|$)", "i"))
```

**Key rules:**
- Use **whitespace-boundary regex** (`(^|\\s)Professor(\\s|$)`) rather than a
  plain substring match. A plain `REGEX(?role, "Professor", "i")` would also
  match near-miss roles like "Professor-in-Training" or "Post-Doctoral
  Professor-Fellow". The whitespace-boundary pattern requires "Professor" to be
  surrounded by start/end-of-string or whitespace, correctly rejecting
  hyphenated compounds.
- **Important**: SPARQL's regex engine is based on XPath/XQuery, which does
  **NOT** support Perl-style `\b` word boundaries. Use `(^|\\s)...(\\s|$)` instead.
- Use case-insensitive flag (`"i"`) to catch "professor", "Professor", etc.
- **Strategy choice — regex vs. enumeration:**
  - **Regex** (as above) is appropriate when the task says "all professors"
    without specifying exact titles, or when role strings are open-ended
    (e.g., "Professor of <any field>").
  - **Enumeration** is safer when the task explicitly names the qualifying
    ranks (e.g., "Assistant Professors and Full Professors"). Use `VALUES` or
    an exact-match FILTER:
    ```sparql
    FILTER(?role IN ("Professor of Computer Science",
                     "Assistant Professor of Engineering",
                     "Professor of Mathematics"))
    ```
    Or with VALUES:
    ```sparql
    VALUES ?role { "Professor of Computer Science"
                   "Assistant Professor of Engineering" }
    ```
  - **Hybrid**: Use regex for the general pattern plus negative FILTER to
    exclude specific non-qualifying ranks:
    ```sparql
    FILTER(REGEX(?role, "(^|\\s)Professor(\\s|$)", "i"))
    FILTER(!REGEX(?role, "Emeritus|Visiting|Adjunct", "i"))
    ```
- Always read the task instructions carefully to determine which ranks qualify.

#### Pattern B: Typed academic rank resources

The person has a `uni:hasAcademicRank` property pointing to a rank resource,
which has a `uni:rankLabel` string. Match against the label using whitespace-boundary
regex:

```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(REGEX(?rankLabel, "(^|\\s)Professor(\\s|$)", "i"))
```

#### Pattern C: RDF type-based identification

Professors might be instances of specific classes like `uni:FullProfessor` or
`uni:AssistantProfessor`:

```sparql
{ ?person a uni:FullProfessor }
UNION
{ ?person a uni:AssistantProfessor }
```

#### Pattern D: Mixed/hybrid

Some variants may combine patterns. Use `UNION` or `OPTIONAL` as needed.

**Always verify**: After identifying candidate professors, check that you are
not including non-professors (lecturers, students, researchers, staff) or
missing qualifying professors.

### Step 3: Trace the Affiliation Path to the University

The path from a person to their university varies by variant:

#### Pattern A: Two-hop via department (v01 seed)

```
person --worksAt--> department --partOfUniversity--> university
```

```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
?uni a uni:University .
```

**Why the type constraint matters**: Without `?uni a uni:University`, the
chain `?dept uni:partOfUniversity ?uni` binds `?uni` to whatever the predicate
points at. In variants with heterogeneous organization chains (e.g., a
ResearchConsortium that also has `partOfUniversity` pointing to the real
university, and also has `hasName`), omitting the type check would return the
wrong organization's name. The type constraint costs nothing when the data is
clean but prevents false matches in noisy variants.

#### Pattern B: Direct affiliation

```
person --worksAt--> university
```

```sparql
?person uni:worksAt ?uni .
?uni a uni:University .
```

#### Pattern C: Via intermediate organization chain

```
person --worksAt--> lab --partOf--> department --partOfUniversity--> university
```

Use property paths or multiple hops:

```sparql
?person uni:worksAt ?org .
?org uni:partOf+ ?uni .   # one or more hops
?uni a uni:University .
```

Or explicitly chain:

```sparql
?person uni:worksAt ?org .
?org uni:partOf ?dept .
?dept uni:partOfUniversity ?uni .
?uni a uni:University .
```

#### Pattern D: Course-based fallback

If `worksAt` is absent for some professors, fall back through their teaching:

```
person --teaches--> course --isTaughtIn--> department --partOfUniversity--> university
```

**Option 1 — UNION with FILTER NOT EXISTS** (use when `worksAt` may be entirely absent):

```sparql
{
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?uni .
  ?uni a uni:University .
}
UNION
{
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?dept2 .
  ?dept2 uni:partOfUniversity ?uni .
  ?uni a uni:University .
  FILTER NOT EXISTS { ?person uni:worksAt ?anyDept }
}
```

> **UNION duplication hazard**: UNION produces results from *both* branches
> without deduplication. The `FILTER NOT EXISTS` guard in the second branch
> prevents a professor with both `worksAt` and `teaches` from appearing twice.
> However, if the two branches could bind `?uni` to *different* organizations
> (e.g., in a heterogeneous chain where `worksAt` leads to a consortium and
> `teaches` leads to a department), even DISTINCT won't help because the
> bindings differ. In such cases, prefer Option 2.

**Option 2 — OPTIONAL + COALESCE** (preferred when you want exactly one path per person):

```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
?uni a uni:University .
OPTIONAL {
  ?person uni:teaches ?course .
  ?course uni:isTaughtIn ?teachingDept .
  ?teachingDept uni:partOfUniversity ?fallbackUni .
  ?fallbackUni a uni:University .
}
BIND(COALESCE(?uni, ?fallbackUni) AS ?finalUni)
```

This guarantees one primary path with a fallback, without UNION duplication
risk. Use `?finalUni` in place of `?uni` for the name retrieval step.

**Always verify**: Check that the path reaches a resource typed as
`uni:University` (or equivalent), not just any organization. The `?uni a uni:University`
constraint is essential — see Pattern A above for why.

### Step 4: Retrieve Names

- **Professor name**: Look for a `uni:hasName` (or similar) property on the
  person. The variable must be `?professorName`.
- **University name**: Look for a `uni:hasName` (or similar) property on the
  university resource. The variable must be `?universityName`.

```sparql
?person uni:hasName ?professorName .
?uni uni:hasName ?universityName .
```

### Step 5: Deduplicate and Project

Use `SELECT DISTINCT` to ensure exactly one row per professor–university pair,
especially when multiple paths could lead to duplicate bindings (e.g., a
professor teaches multiple courses in the same department).

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE { ... }
ORDER BY ?professorName
```

### Step 6: Assemble and Validate

1. Combine all patterns into a single query.
2. Use the correct prefix declarations discovered in Step 1.
3. Test the query against the graph using rdflib:

```python
import rdflib
g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")
with open("/app/solution.sparql") as f:
    query = f.read()
results = g.query(query)
for row in results:
    print(row)
```

4. Verify:
   - The result contains only professors (not lecturers, students, etc.).
   - Each professor appears exactly once.
   - The university names are correct.
   - The variables are named exactly `?professorName` and `?universityName`.

## Complete Query Template (v01 seed pattern)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    ?person a uni:Person ;
            uni:hasName ?professorName ;
            uni:role ?role ;
            uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
    ?uni a uni:University .
    ?uni uni:hasName ?universityName .
    FILTER(REGEX(?role, "(^|\\s)Professor(\\s|$)", "i"))
}
ORDER BY ?professorName
```

## Common Pitfalls

1. **Missing DISTINCT**: Multiple departments or courses at the same university
   can cause duplicate rows. Always use `SELECT DISTINCT`.
2. **Plain substring regex for professor matching**: Using
   `REGEX(?role, "Professor", "i")` (no boundaries) will match near-miss
   roles like "Professor-in-Training" or "Post-Doctoral Professor-Fellow".
   Always use `REGEX(?role, "(^|\\s)Professor(\\s|$)", "i")` for
   whitespace-boundary matching. Note: SPARQL's XPath regex engine does NOT
   support `\b` word boundaries — use `(^|\\s)...(\\s|$)` instead. Alternatively,
   enumerate exact qualifying roles when the task specifies them.
3. **Missing `?uni a uni:University` type constraint**: The affiliation chain
   (e.g., `?dept uni:partOfUniversity ?uni`) binds `?uni` to whatever the
   predicate points at. Without the type constraint, variants with
   heterogeneous organization chains (consortia, research centers, etc.) can
   cause the query to bind `?uni` to a non-university organization that also
   has a `hasName` property. Always include `?uni a uni:University .`.
4. **Including non-professors**: Word-boundary regex excludes "Lecturer",
   "Student", "Staff", etc. But be careful with roles like "Professor Emeritus"
   or "Visiting Professor" — check the task instructions for whether these
   should be included, and add negative FILTER conditions if needed.
5. **Wrong variable names**: The output variables must be exactly
   `?professorName` and `?universityName`.
6. **Hard-coded prefixes**: Always discover the actual prefix from the Turtle
   file; do not assume `uni:` — it could be `ex:`, `org:`, or a full IRI.
7. **Missing the intermediate node**: The affiliation path may have 1, 2, or
   more hops. Inspect the data to determine the correct chain length.
8. **Not handling variant rank representations**: If ranks are resources rather
   than strings, match on the resource type or label, not the role string.
9. **UNION duplication in fallback patterns**: When using UNION between
   `worksAt` and `teaches`-based paths, professors with both properties appear
   in both branches. Use `FILTER NOT EXISTS` in the fallback branch or prefer
   `OPTIONAL` + `COALESCE` to guarantee one path per person.

## Decision Flowchart

```
Read Turtle file
    │
    ├── What predicates link people to roles/ranks?
    │   ├── String property (e.g., uni:role)
    │   │   ├── Task names exact ranks → enumerate with VALUES/IN
    │   │   └── Task says "all professors" → REGEX whitespace-boundary "(^|\\s)Professor(\\s|$)"
    │   ├── Resource property (e.g., uni:hasAcademicRank) → match rank label
    │   └── RDF type (e.g., a uni:Professor) → type-based filter
    │
    ├── What predicates link people to organizations?
    │   ├── Direct to university → single hop + ?uni a uni:University
    │   ├── To department/school → follow partOfUniversity + ?uni a uni:University
    │   ├── To lab/team → follow multi-hop partOf chain + ?uni a uni:University
    │   └── Missing for some → OPTIONAL/COALESCE fallback via teaches/isTaughtIn
    │
    ├── What property gives names?
    │   └── Usually hasName on both person and university
    │
    └── Write query with DISTINCT, type constraints, whitespace-boundary regex,
        correct variables, test, validate
```
