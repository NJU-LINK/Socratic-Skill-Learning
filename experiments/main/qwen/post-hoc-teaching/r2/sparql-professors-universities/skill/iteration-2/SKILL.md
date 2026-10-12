---
name: sparql-professors-universities
description: >
  Write a SPARQL query to retrieve professor names and their university names
  from a Turtle knowledge graph. Handles varying professor-identification
  schemes (string roles, structured rank resources), diverse affiliation
  structures (direct links, multi-hop department chains, inverse relations,
  fallback paths), and differing noise/cardinality levels. Produces a
  .sparql file returning ?professorName and ?universityName with exactly one
  row per qualifying professor-university pair.
---

# SPARQL Professors-Universities Query Skill

## Task Summary

Given a Turtle (`.ttl`) file at `/app/university_graph.ttl` containing an ontology and instance data describing a university knowledge graph, write a SPARQL query that:
- Retrieves all **professor** names
- For each professor, retrieves the **university** they work at
- Saves the query to `/app/solution.sparql`
- Returns exactly two variables: `?professorName` and `?universityName`
- Produces exactly one row per qualifying professor-university pair

## General Methodology

### Phase 1: Ontology Discovery

Always start by inspecting the TTL file to understand the actual ontology and data layout. **Never assume predicates or structure from prior tasks.**

```bash
# Quick structural overview
python3 -c "
from rdflib import Graph, URIRef, RDF, RDFS
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# All predicates
preds = sorted(set(str(p) for s,p,o in g))
print('=== Predicates ===')
for p in preds: print(p)

# All classes
print('\n=== Classes ===')
for s,p,o in g.triples((None, RDF.type, None)):
    print(f'  {s} a {o}')

# Sample triples for key properties
print('\n=== Sample triples (first 50) ===')
for i, (s,p,o) in enumerate(g):
    if i >= 50: break
    print(f'  {s} {p} {o}')
"
```

Key things to discover:
1. **Namespace prefix** — auto-detect from predicate URIs (e.g., `http://university.org/ontology#` → prefix `uni:`)
2. **Person class** — find the class whose instances have role/rank properties (may be `uni:Person`, `uni:Employee`, `uni:Faculty`, etc.)
3. **Name predicate for persons** — the predicate mapping persons to human-readable name strings
4. **University class** — find the class whose instances represent higher-education institutions
5. **University name predicate** — the predicate mapping universities to name strings (may differ from person name predicate!)
6. **All predicates** — enumerate every predicate in the graph; you'll need them for path construction

**Critical**: Extract the namespace URI from the data. All subsequent scripts and the final query must use this discovered namespace, not a hardcoded one.

### Phase 2: Professor Identification Strategy

Determine how professors are distinguished from non-professors. Two main patterns:

#### Pattern A: String-valued role property (v01 baseline)
- A predicate like `uni:role` maps a person to a string literal
- Professors have strings containing "Professor" (e.g., "Professor of X", "Assistant Professor of X")
- Non-professors have other strings ("Lecturer", "Student", "Staff", etc.)
- **Strategy**: `FILTER(CONTAINS(?role, "Professor"))` or regex matching

```sparql
?person uni:role ?role .
FILTER(CONTAINS(?role, "Professor"))
```

**Watch out for near-misses**: If the data contains roles like "Professor Emeritus", "Associate Professor", "Visiting Professor", "Professor-Like", etc., the task instruction will specify which qualify. Always read the task instruction carefully.

#### Pattern B: Structured academic rank resources
- A predicate like `uni:hasAcademicRank` maps a person to a rank resource
- The rank resource has a label via `uni:rankLabel` or similar
- **Strategy**: Match against rank labels, possibly with a controlled vocabulary

```sparql
?person uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(?rankLabel IN ("Professor", "Assistant Professor", "Associate Professor"))
```

Or if ranks are typed:
```sparql
?person uni:hasAcademicRank ?rank .
?rank a uni:FullProfessor .   # or uni:AssistantProfessor
```

**Key principle**: The task instruction will tell you which ranks qualify. Map the instruction's terminology to the actual ontology.

### Phase 3: Affiliation Path Discovery

Trace the path from a person to their university name. Common patterns:

#### Pattern A: Two-hop via department (v01 baseline)
```
Person --worksAt--> Department --partOfUniversity--> University
```
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?uni .
?uni uni:hasName ?universityName .
```

#### Pattern B: Direct affiliation
```
Person --affiliatedWith--> University
```
```sparql
?person uni:affiliatedWith ?uni .
?uni uni:hasName ?universityName .
```

#### Pattern C: Longer/indirect chains
```
Person --hasAppointment--> Appointment --atOrganization--> Department --partOf--> University
```
May require 3+ hops.

#### Pattern D: Fallback paths
The task may specify: "Use worksAt path; if absent, fall back to teaching-course path."
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
  FILTER NOT EXISTS { ?person uni:worksAt [] }
}
```

**Discovery technique — Bidirectional path tracing (critical):**

You must trace in **both directions** and connect the results. One-directional tracing will miss predicate changes at either end of the chain.

**IMPORTANT**: All discovery scripts below are **namespace-agnostic**. They auto-detect class URIs, predicates, and name properties from the data itself. **Never hardcode namespace URIs** — variants may use completely different namespaces (e.g., `http://example.org/acad#` instead of `http://university.org/ontology#`).

**Step 0: Auto-discover the namespace and key class URIs** — before any tracing, extract the namespace and identify which classes represent universities and persons:
```bash
python3 -c "
from rdflib import Graph, RDF, URIRef, Literal
from collections import Counter
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# Discover all classes
classes = Counter()
for s,p,o in g.triples((None, RDF.type, None)):
    classes[str(o)] += 1

print('=== All classes (with instance counts) ===')
for cls, count in classes.most_common():
    print(f'  {cls} ({count} instances)')

# Auto-detect namespace from predicates
preds = set(str(p) for s,p,o in g)
ns_uris = set()
for p in preds:
    if '#' in p:
        ns_uris.add(p.rsplit('#', 1)[0] + '#')
    elif '/' in p:
        ns_uris.add(p.rsplit('/', 1)[0] + '/')

print('\\n=== Detected namespaces ===')
for ns in sorted(ns_uris):
    print(f'  {ns}')

# Identify university-like class: has instances with string name properties
print('\\n=== University detection ===')
for cls in classes:
    cls_uri = URIRef(cls)
    instances = list(g.subjects(RDF.type, cls_uri))
    if not instances:
        continue
    # Check if instances have string-valued name-like properties
    for inst in instances[:3]:  # Sample first 3
        for p,o in g.predicate_objects(inst):
            if isinstance(o, Literal) and len(str(o)) > 3:
                print(f'  {cls} instance {inst} has literal property {p} -> \"{o}\"')
                break

# Identify person-like class: has instances with role-like properties
print('\\n=== Person detection ===')
for cls in classes:
    cls_uri = URIRef(cls)
    instances = list(g.subjects(RDF.type, cls_uri))
    if not instances:
        continue
    # Check if instances have role/rank-like properties
    for inst in instances[:3]:
        for p,o in g.predicate_objects(inst):
            if 'role' in str(p).lower() or 'rank' in str(p).lower() or 'position' in str(p).lower():
                print(f'  {cls} instance {inst} has role-like property {p} -> \"{o}\"')
                break
"
```

This script auto-detects:
- The namespace URI (e.g., `http://university.org/ontology#`)
- Which class represents universities (by finding classes with instances that have string name properties)
- Which class represents persons (by finding classes with instances that have role/rank properties)
- The actual predicates used for names, roles, and affiliations

**Step 1: Forward trace from Person** — using the auto-detected person class URI, enumerate all outgoing predicates:
```bash
python3 -c "
from rdflib import Graph, RDF, URIRef, Literal
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# Auto-detect person class (look for class with role-like properties)
PERSON = None
for s,p,o in g.triples((None, RDF.type, None)):
    cls_str = str(o).lower()
    if 'person' in cls_str or 'employee' in cls_str or 'faculty' in cls_str:
        PERSON = o
        break

if not PERSON:
    # Fallback: find class with most instances that have role/rank properties
    from collections import Counter
    cls_role_count = Counter()
    for s,p,o in g:
        if 'role' in str(p).lower() or 'rank' in str(p).lower():
            for s2,p2,o2 in g.triples((s, RDF.type, None)):
                cls_role_count[str(o2)] += 1
    if cls_role_count:
        PERSON = URIRef(cls_role_count.most_common(1)[0][0])

if not PERSON:
    print('ERROR: Could not auto-detect person class')
    exit(1)

print(f'Auto-detected person class: {PERSON}')
persons = set(g.subjects(RDF.type, PERSON))
print(f'Found {len(persons)} person instances')

# All outgoing predicates from Person entities
person_preds = set()
for person in persons:
    for s, p, o in g.triples((person, None, None)):
        person_preds.add(str(p))

print('\\n=== Person outgoing predicates ===')
for p in sorted(person_preds):
    print(f'  {p}')

# For each predicate, what types/resources does it lead to?
print('\\n=== Predicate target types ===')
for pred_str in sorted(person_preds):
    pred = URIRef(pred_str)
    targets = set()
    for person in persons:
        for s, p, o in g.triples((person, pred, None)):
            target_types = [str(t) for s2, p2, t in g.triples((o, RDF.type, None))]
            if target_types:
                targets.update(target_types)
            elif isinstance(o, Literal):
                targets.add(f'literal:{type(o).__name__}')
            else:
                targets.add('untyped_resource')
    print(f'  {pred_str} -> {sorted(targets)}')
"
```

**Step 2: Backward trace from University** — using the auto-detected university class URI, enumerate incoming edges:
```bash
python3 -c "
from rdflib import Graph, RDF, URIRef, Literal
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# Auto-detect university class (look for class with instances that have string name properties)
UNI = None
for s,p,o in g.triples((None, RDF.type, None)):
    cls_str = str(o).lower()
    if 'university' in cls_str or 'institution' in cls_str or 'organization' in cls_str:
        # Verify it has instances with string name properties
        instances = list(g.subjects(RDF.type, o))
        if instances:
            for inst in instances[:2]:
                for p2,o2 in g.predicate_objects(inst):
                    if isinstance(o2, Literal) and len(str(o2)) > 3:
                        UNI = o
                        break
                if UNI:
                    break
        if UNI:
            break

if not UNI:
    print('ERROR: Could not auto-detect university class')
    exit(1)

print(f'Auto-detected university class: {UNI}')
unis = set(g.subjects(RDF.type, UNI))
print(f'Found {len(unis)} university instances')

print('\\n=== Incoming edges to Universities ===')
for u in sorted(unis)[:5]:  # Show first 5 for brevity
    incoming = [(s,p) for s,p,o in g.triples((None, None, u))]
    print(f'{u}:')
    for s,p in incoming:
        # Also show what types point to it
        types = [str(t) for s2,p2,t in g.triples((s, RDF.type, None))]
        print(f'  <- {p} <- {s}  (types: {types})')
if len(unis) > 5:
    print(f'  ... and {len(unis) - 5} more universities')

# Also discover the name predicate for universities
print('\\n=== University name predicate detection ===')
for u in sorted(unis)[:2]:
    for p,o in g.predicate_objects(u):
        if isinstance(o, Literal) and len(str(o)) > 3:
            print(f'  {u} has name property: {p} -> \"{o}\"')
"
```

**Step 3: Connect forward and backward** — join the two traces at their meeting point. The forward trace reveals the Person→?org predicate; the backward trace reveals the ?org→University predicate. Together they form the full chain.

**Why bidirectional tracing is essential:**
- If a variant uses `uni:employedBy` instead of `uni:worksAt`, only forward tracing reveals this predicate change at the Person end.
- If a variant uses inverse containment (`?uni uni:hasDepartment ?dept` instead of `?dept uni:partOfUniversity ?uni`), only backward tracing reveals this structural flip.
- If both change simultaneously, you need both traces to reconstruct the correct chain.
- If the namespace changes (e.g., `http://example.org/acad#`), the auto-detection scripts will find the correct URIs instead of failing silently.

**Inverse containment example:**
When the containment relation is inverted, the SPARQL pattern changes structurally — the university variable moves from object to subject position:
```sparql
# Forward containment (v01 baseline):
?dept uni:partOfUniversity ?uni .

# Inverse containment (variant):
?uni uni:hasDepartment ?dept .
```
Both express the same relationship but require different triple pattern structures in the query.

### Phase 4: Query Construction

Assemble the SPARQL query with these components:

1. **PREFIX declarations** matching the discovered namespace
2. **SELECT** with exactly `?professorName` and `?universityName`
3. **WHERE** clause chaining:
   - Person type constraint
   - Person name binding
   - Professor identification filter
   - Affiliation path to university
   - University name binding
4. **DISTINCT** if there is risk of duplicate rows from multiple paths
5. **ORDER BY** for deterministic output (optional but good practice)

#### Template query structure:

```sparql
PREFIX <ns>: <discovered-namespace#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
    # Person must be of the right type
    ?person a <ns>:Person ;
            <ns>:hasName ?professorName .

    # Professor identification (adapt to discovered pattern)
    ?person <ns>:role ?role .
    FILTER(CONTAINS(?role, "Professor"))
    # OR: ?person <ns>:hasAcademicRank ?rank . ?rank <ns>:rankLabel ?rankLabel . FILTER(...)

    # Affiliation path to university (adapt to discovered structure)
    ?person <ns>:worksAt ?dept .
    ?dept <ns>:partOfUniversity ?uni .
    ?uni <ns>:hasName ?universityName .
}
ORDER BY ?professorName
```

### Phase 5: Automated Cross-Validation

**Never rely on visual inspection alone.** The spec requires *exactly one row per qualifying professor-university pair* — on variants with unknown counts, eyeballing results is unreliable. Instead, run an **independent cross-validation** that enumerates expected results using Python/rdflib (NOT the SPARQL query being tested), then compares against the SPARQL output.

This creates a closed-loop validation: if the SPARQL query and the validation both use the same logic, they'd share the same bug. Independence catches errors that eyeballing misses.

Run this script **after** saving `/app/solution.sparql`:

```bash
python3 -c "
from rdflib import Graph, RDF, URIRef, Literal
from collections import Counter

g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# --- INDEPENDENT ENUMERATION (Python/rdflib, NOT SPARQL) ---

# 1. Auto-detect person class
PERSON = None
for s,p,o in g.triples((None, RDF.type, None)):
    cls_str = str(o).lower()
    if 'person' in cls_str or 'employee' in cls_str or 'faculty' in cls_str:
        PERSON = o
        break

if not PERSON:
    # Fallback: find class with role/rank properties
    cls_role_count = Counter()
    for s,p,o in g:
        if 'role' in str(p).lower() or 'rank' in str(p).lower():
            for s2,p2,o2 in g.triples((s, RDF.type, None)):
                cls_role_count[str(o2)] += 1
    if cls_role_count:
        PERSON = URIRef(cls_role_count.most_common(1)[0][0])

# 2. Auto-detect role/rank predicate
ROLE_PRED = None
if PERSON:
    sample_persons = list(g.subjects(RDF.type, PERSON))[:3]
    for person in sample_persons:
        for p,o in g.predicate_objects(person):
            if 'role' in str(p).lower() or 'rank' in str(p).lower() or 'position' in str(p).lower():
                ROLE_PRED = p
                break
        if ROLE_PRED:
            break

# 3. Auto-detect name predicate for persons
NAME_PRED = None
if PERSON:
    sample_persons = list(g.subjects(RDF.type, PERSON))[:3]
    for person in sample_persons:
        for p,o in g.predicate_objects(person):
            if isinstance(o, Literal) and len(str(o)) > 2 and p != ROLE_PRED:
                NAME_PRED = p
                break
        if NAME_PRED:
            break

# 4. Enumerate expected professors independently
expected_professors = {}  # name -> set of roles
if PERSON and ROLE_PRED:
    for person in g.subjects(RDF.type, PERSON):
        roles = [str(o) for s,p,o in g.triples((person, ROLE_PRED, None))]
        is_prof = any('Professor' in r for r in roles)
        if is_prof:
            if NAME_PRED:
                names = [str(o) for s,p,o in g.triples((person, NAME_PRED, None))]
            else:
                names = [str(o) for s,p,o in g.triples((person, None, None))
                         if isinstance(o, Literal) and len(str(o)) > 2]
            name = names[0] if names else str(person)
            expected_professors[name] = roles

print(f'Independent enumeration: {len(expected_professors)} professors')
for name, roles in sorted(expected_professors.items()):
    print(f'  {name} (roles: {roles})')

# --- SPARQL RESULTS ---
with open('/app/solution.sparql') as f:
    query = f.read()

sparql_result = g.query(query)
results = list(sparql_result)
sparql_names = [str(row[0]) for row in results]

print(f'\\nSPARQL result count: {len(results)}')

# --- CROSS-VALIDATION ---
errors = []

# Check variable names
var_names = [str(v) for v in sparql_result.vars]
if var_names != ['professorName', 'universityName']:
    errors.append(f'Wrong variables: {var_names}')

# Check count match
if len(results) != len(expected_professors):
    errors.append(f'Count mismatch: SPARQL={len(results)}, expected={len(expected_professors)}')

# Check for NULL values
null_rows = [i for i, row in enumerate(results) if row[0] is None or row[1] is None]
if null_rows:
    errors.append(f'NULL values in rows: {null_rows}')

# Check for duplicates
if len(sparql_names) != len(set(sparql_names)):
    dupes = {k:v for k,v in Counter(sparql_names).items() if v > 1}
    errors.append(f'Duplicate professor names: {dupes}')

# Check all expected professors are present
missing = set(expected_professors.keys()) - set(sparql_names)
extra = set(sparql_names) - set(expected_professors.keys())
if missing:
    errors.append(f'Missing from SPARQL: {missing}')
if extra:
    errors.append(f'Extra in SPARQL: {extra}')

# Check university names are strings, not URIs
for row in results:
    if not isinstance(row[1], Literal):
        errors.append(f'University name is URI, not literal: {row[1]}')
        break

if errors:
    print('\\n❌ VALIDATION FAILED:')
    for e in errors:
        print(f'  - {e}')
    print('\\nReturn to the relevant phase:')
    print('  - Filter issues (missing/extra professors) → Phase 2')
    print('  - Path issues (NULL universities, wrong structure) → Phase 3')
    print('  - Construction issues (wrong variables, duplicates) → Phase 4')
else:
    print('\\n✅ VALIDATION PASSED: SPARQL results match independent enumeration')
"
```

**What this catches that visual inspection misses:**

| Failure mode | Eyeball check | Cross-validation |
|---|---|---|
| Wrong namespace → 0 results | "Hmm, empty... maybe correct?" | **Count mismatch: 0 vs N** |
| Wrong filter → includes Lecturer | Might not notice extra row | **Extra in SPARQL: {'Jane Petterson'}** |
| Duplicate from multi-dept join | Looks like a long list | **Duplicate names: {'Alex Morgan': 2}** |
| Incomplete path → NULL university | Hard to spot in a table | **NULL values in rows: [3]** |
| Wrong name predicate → URIs | Might look odd but pass | **University name is URI, not literal** |
| Near-miss role included | "Is Professor Emeritus valid?" | **Extra in SPARQL** triggers investigation |

**Feedback loop:** If validation fails, return to the relevant phase:
- Filter issues (missing/extra professors) → revisit **Phase 2** (professor identification)
- Path issues (NULL universities, wrong structure) → revisit **Phase 3** (affiliation path)
- Construction issues (wrong variables, duplicates) → revisit **Phase 4** (query construction)

## Variation Handling Guide

### When professor identification uses structured ranks
- Look for predicates linking persons to rank resources (e.g., `uni:hasAcademicRank`)
- Look for rank labels or types that distinguish professors from non-professors
- Build an inclusive filter matching all qualifying rank labels
- Beware of decoy ranks that sound professor-like but aren't (e.g., "Professor Emeritus" may or may not qualify depending on instructions)

### When affiliation uses indirect or heterogeneous paths
- Use **bidirectional tracing** (Phase 3): forward from Person to find outgoing predicates, backward from University to find containment structure, then connect at the meeting point
- Watch for predicate renames at the Person end (e.g., `employedBy` instead of `worksAt`) — only forward tracing catches these
- Watch for inverse containment (e.g., `uni:hasDepartment` instead of `uni:partOfUniversity`) — this flips variable positions in the SPARQL pattern
- If multiple paths exist, use UNION or OPTIONAL as specified
- If a fallback path is specified, implement it with appropriate priority logic

### When graph noise is high
- Use `DISTINCT` to eliminate duplicate bindings
- Be precise with type constraints (e.g., `a uni:Person` AND `a uni:Professor` if professor is a subclass)
- Filter out decoy entities that match partial patterns
- Verify cardinality: one row per qualifying professor-university pair

## Common Pitfalls

1. **Hardcoding namespace URIs**: The most critical mistake. The namespace may change between variants (e.g., `http://example.org/acad#` instead of `http://university.org/ontology#`). Always auto-detect the namespace from the TTL file. If you hardcode `http://university.org/ontology#University` in a discovery script and the variant uses a different namespace, the script returns empty results and you build a query that fails silently.
2. **Assuming person and university name predicates are the same**: v01 uses `uni:hasName` for both, but variants may use `rdfs:label` for universities, `uni:title` for persons, or different predicates entirely. Discover each independently.
3. **Hardcoding predicates from v01**: Always re-discover the ontology from the actual TTL file. Predicates like `worksAt`, `partOfUniversity`, `role` may be renamed.
4. **Missing professor types**: "Assistant Professor" and "Associate Professor" must be included unless explicitly excluded
5. **Including non-professors**: "Lecturer", "Senior Lecturer", "Researcher", "Student" are NOT professors
6. **Wrong person class name**: The person class might be `uni:Employee`, `uni:Faculty`, `uni:StaffMember` instead of `uni:Person`. Use heuristic detection (look for classes with role/rank properties).
7. **Missing DISTINCT**: When a professor has multiple departments or courses at the same university, the join may produce duplicates
8. **Forgetting the prefix**: The namespace prefix in the SPARQL query must match the discovered namespace
