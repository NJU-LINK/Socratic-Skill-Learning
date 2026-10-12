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
1. **Namespace prefix** (e.g., `uni:` → `http://university.org/ontology#`)
2. **Person class** (e.g., `uni:Person`)
3. **Name predicate** (e.g., `uni:hasName`)
4. **University class** (e.g., `uni:University`)
5. **University name predicate** (e.g., `uni:hasName`)

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

**Step 1: Forward trace from Person** — enumerate all outgoing predicates from Person entities and discover which lead toward organizations:
```bash
python3 -c "
from rdflib import Graph, RDF, URIRef
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

# Discover the Person class URI from the data
PERSON = None
for s,p,o in g.triples((None, RDF.type, None)):
    if 'Person' in str(o):
        PERSON = o; break

persons = set(s for s,p,o in g.triples((None, RDF.type, PERSON)))

# All outgoing predicates from Person entities
person_preds = set()
for person in persons:
    for s, p, o in g.triples((person, None, None)):
        person_preds.add(str(p))

print('=== Person outgoing predicates ===')
for p in sorted(person_preds):
    print(f'  {p}')

# For each predicate, what types/resources does it lead to?
for pred_str in sorted(person_preds):
    pred = URIRef(pred_str)
    targets = set()
    for person in persons:
        for s, p, o in g.triples((person, pred, None)):
            target_types = [str(t) for s2, p2, t in g.triples((o, RDF.type, None))]
            if target_types:
                targets.update(target_types)
            else:
                targets.add(f'literal:{type(o).__name__}')
    print(f'  {pred_str} -> {targets}')
"
```

**Step 2: Backward trace from University** — enumerate incoming edges to University entities to discover the containment structure:
```bash
python3 -c "
from rdflib import Graph, RDF, URIRef
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')
UNI = URIRef('http://university.org/ontology#University')
unis = set(s for s,p,o in g.triples((None, RDF.type, UNI)))

print('=== Incoming edges to Universities ===')
for u in unis:
    incoming = [(s,p) for s,p,o in g.triples((None, None, u))]
    print(f'{u}:')
    for s,p in incoming:
        # Also show what types point to it
        types = [str(t) for s2,p2,t in g.triples((s, RDF.type, None))]
        print(f'  <- {p} <- {s}  (types: {types})')
"
```

**Step 3: Connect forward and backward** — join the two traces at their meeting point. The forward trace reveals the Person→?org predicate; the backward trace reveals the ?org→University predicate. Together they form the full chain.

**Why bidirectional tracing is essential:**
- If a variant uses `uni:employedBy` instead of `uni:worksAt`, only forward tracing reveals this predicate change at the Person end.
- If a variant uses inverse containment (`?uni uni:hasDepartment ?dept` instead of `?dept uni:partOfUniversity ?uni`), only backward tracing reveals this structural flip.
- If both change simultaneously, you need both traces to reconstruct the correct chain.

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

### Phase 5: Verification

Always test the query against the data before saving:

```bash
python3 -c "
from rdflib import Graph
g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')
with open('/app/solution.sparql') as f:
    query = f.read()
results = g.query(query)
print(f'Variables: {[str(v) for v in results.vars]}')
print(f'Row count: {len(results)}')
for row in results:
    print(f'  {row[0]} | {row[1]}')
"
```

Check:
- Correct number of variables (exactly 2: `?professorName`, `?universityName`)
- No non-professors in results (no "Lecturer", "Student", "Staff", etc.)
- All expected professors are present
- No duplicate rows (unless the task explicitly allows them)
- University names are human-readable strings, not URIs

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

1. **Hardcoding predicates from v01**: Always re-discover the ontology from the actual TTL file
2. **Missing professor types**: "Assistant Professor" and "Associate Professor" must be included unless explicitly excluded
3. **Including non-professors**: "Lecturer", "Senior Lecturer", "Researcher", "Student" are NOT professors
4. **Wrong name variable**: Use the predicate that yields human-readable names (usually `uni:hasName`), not URIs
5. **Missing DISTINCT**: When a professor has multiple departments or courses at the same university, the join may produce duplicates
6. **Forgetting the prefix**: The namespace prefix must match the actual TTL file; it may vary between instances
