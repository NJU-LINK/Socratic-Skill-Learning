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

### Step 2: Identify Professors — Role Discovery and Verification

**CRITICAL**: Before choosing a matching pattern, you MUST empirically discover
what role/rank values actually exist in the data and cross-reference them with
the task instructions. Do not assume the data matches v01's patterns.

**Procedure:**

1. **Extract all unique role/rank values** from the graph:
   ```python
   import rdflib
   g = rdflib.Graph()
   g.parse("/app/university_graph.ttl", format="turtle")
   
   # Find predicates that might carry role/rank info
   role_predicates = []
   for s, p, o in g:
       if 'role' in str(p).lower() or 'rank' in str(p).lower():
           role_predicates.append(str(p))
   
   # Extract all values for those predicates
   all_roles = set()
   for pred in role_predicates:
       for s, p, o in g.triples((None, rdflib.URIRef(pred), None)):
           all_roles.add(str(o))
   
   print("All role/rank values in data:")
   for role in sorted(all_roles):
       print(f"  '{role}'")
   ```

2. **For each role value, determine if it qualifies** based on the task
   instructions. Create a mental (or written) list:
   - Qualifying: e.g., "Professor of X", "Assistant Professor of X"
   - Non-qualifying: e.g., "Lecturer", "Student", "Professor Emeritus"
   - Ambiguous: check task instructions carefully

3. **Choose the matching strategy** based on what you found:
   - If roles are simple strings with "Professor" as a word → use whitespace-boundary regex
   - If roles use abbreviations ("Prof.", "Asst. Prof.") → adjust regex or enumerate
   - If task explicitly names qualifying ranks → use VALUES/IN enumeration
   - If ranks are resources (not strings) → match on resource type or label

4. **Verify your filter** by running a test query that shows which roles match:
   ```sparql
   SELECT DISTINCT ?role WHERE {
       ?person uni:role ?role .
       FILTER(/* your professor filter here */)
   }
   ```
   Compare the results against your expected qualifying roles. If there's a
   mismatch, adjust your filter.

5. **Two-sided verification** (CRITICAL): After the positive check above,
   you MUST also check which roles did NOT match your filter. This catches
   false negatives — qualifying professors your filter is incorrectly excluding.
   
   **Procedure**: Compare the full set of roles (from sub-step 1) against the
   matched set (from sub-step 4):
   ```python
   all_roles = {...}  # from sub-step 1
   matched_roles = {...}  # from your filter query
   unmatched = all_roles - matched_roles
   
   print("Roles that matched your filter:")
   for r in sorted(matched_roles):
       print(f"  ✓ '{r}'")
   
   print("\nRoles that did NOT match:")
   for r in sorted(unmatched):
       print(f"  ✗ '{r}' — is this correct? (professor excluded? or non-professor correctly filtered?)")
   ```
   
   For each unmatched role, explicitly decide: "Is this a professor role I'm
   missing, or a non-professor role I'm correctly excluding?" If you find
   false negatives, adjust your filter (e.g., add abbreviation handling, expand
   the regex, or switch to enumeration).

   **Why this matters**: A one-sided check only shows what passes your filter.
   If the data contains `"Prof. of Chemistry"` and your regex only matches
   `"Professor"`, you'd see 6 professors instead of 7 but wouldn't immediately
   know which role you're missing. The two-sided check makes false negatives
   explicit and forces you to evaluate each one.

**Why this matters**: Variants may include roles like "Prof. of Chemistry",
"Associate Professor", "Professor Emeritus", or "Professor-in-Training". Your
filter must match exactly the qualifying roles specified in the task. Blindly
applying a template without checking the actual data will fail on variants.

---

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
- **Handling abbreviations and spelling variations**: If the data uses
  abbreviations like "Prof." or "Asst. Prof.", adjust your regex:
  ```sparql
  FILTER(REGEX(?role, "(^|\\s)(Professor|Prof\\.)(\\s|$)", "i"))
  ```
  Or enumerate exact values if the task specifies them.
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

**Handling inverse containment relations**: Some variants may use inverse
predicates (e.g., `uni:hasDepartment` from university to department instead of
`uni:partOfUniversity` from department to university). If you discover that the
affiliation chain uses inverse relations, reverse the triple pattern:
```sparql
# Instead of: ?dept uni:partOfUniversity ?uni .
# Use:        ?uni uni:hasDepartment ?dept .
?uni uni:hasDepartment ?dept .
?uni a uni:University .
```
Always inspect the actual predicates in the data to determine the direction.

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

Build the query using the patterns from Steps 2-3 with the predicates you discovered in Step 1. Test it against the graph, verify the results match your expected count from Step 2, and save to `/app/solution.sparql`.

## Reference Template (v01 seed)

This example uses `uni:` predicates and a two-hop affiliation path. Adapt it to your discovered ontology structure.

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
5. **Professor-like near misses**: Variants may introduce roles that contain
   "Professor" but are not qualifying professors. Examples:
   - "Professor-in-Training" (hyphenated compound — rejected by whitespace boundary)
   - "Post-Doctoral Professor-Fellow" (hyphenated — rejected by whitespace boundary)
   - "Professorial Fellow" (adjective form — does NOT contain "Professor" as a word)
   - "Professor Emeritus" or "Visiting Professor" (may or may not qualify — check task)
   - "Prof. of Chemistry" (abbreviation — needs adjusted regex or enumeration)
   Always verify your filter against the actual data (see Step 2 procedure).
6. **Wrong variable names**: The output variables must be exactly
   `?professorName` and `?universityName`.
7. **Hard-coded assumptions**: Always discover the actual prefix, classes, and predicates from the Turtle file. Do not assume `uni:` predicates or v01's two-hop structure — variants may use different namespaces, direct affiliations, or multi-hop chains. The reference template below is v01-specific; adapt it to your discovered ontology.
8. **Missing the intermediate node**: The affiliation path may have 1, 2, or
   more hops. Inspect the data to determine the correct chain length.
9. **Not handling variant rank representations**: If ranks are resources rather
   than strings, match on the resource type or label, not the role string.
10. **UNION duplication in fallback patterns**: When using UNION between
    `worksAt` and `teaches`-based paths, professors with both properties appear
    in both branches. Use `FILTER NOT EXISTS` in the fallback branch or prefer
    `OPTIONAL` + `COALESCE` to guarantee one path per person.
11. **Inverse containment relations**: Some variants use predicates in the
    opposite direction (e.g., `uni:hasDepartment` from university to department
    instead of `uni:partOfUniversity` from department to university). Always
    inspect the actual predicate directions in the data.

## Decision Flowchart

```
Read Turtle file
    │
    ├── Step 1: Discover ontology structure
    │   ├── What prefix/namespace? (uni:, ex:, org:, etc.)
    │   ├── What classes exist? (Person, University, Department, etc.)
    │   ├── What predicates link people to roles/ranks?
    │   ├── What predicates link people to organizations?
    │   └── What property gives names?
    │
    ├── Step 2: Role discovery and verification (CRITICAL)
    │   ├── Extract ALL unique role/rank values from the data
    │   ├── For each role, determine if it qualifies per task instructions
    │   ├── Choose matching strategy:
    │   │   ├── Simple "Professor" word → REGEX "(^|\\s)Professor(\\s|$)"
    │   │   ├── Abbreviations ("Prof.") → REGEX "(^|\\s)(Professor|Prof\\.)(\\s|$)"
    │   │   ├── Task names exact ranks → VALUES/IN enumeration
    │   │   ├── Ranks are resources → match on type or label
    │   │   └── Mixed → UNION or hybrid approach
    │   └── Verify filter: check BOTH matched and unmatched roles
    │       ├── Positive check: which roles pass the filter?
    │       └── Negative check: which roles don't pass? Are any false negatives?
    │
    ├── Step 3: Trace affiliation path
    │   ├── Direct to university → single hop + ?uni a uni:University
    │   ├── To department/school → follow partOfUniversity + ?uni a uni:University
    │   ├── To lab/team → follow multi-hop partOf chain + ?uni a uni:University
    │   ├── Inverse relations (hasDepartment) → reverse triple pattern
    │   └── Missing for some → OPTIONAL/COALESCE fallback via teaches/isTaughtIn
    │
    └── Step 4: Assemble and validate
        ├── Build query from discovered elements (Steps 1-3)
        ├── SELECT DISTINCT ?professorName ?universityName
        ├── Type constraints: ?uni a <UniversityClass>
        ├── Whitespace-boundary regex or enumeration
        ├── Test against graph, verify results
        ├── Cross-check count against Step 2's expected count
        └── Save to /app/solution.sparql
```
