---
name: sparql-professors-universities
description: >
  Write SPARQL queries to extract professor names and their affiliated
  university names from a Turtle knowledge graph describing universities,
  departments, employees, students, and courses. The skill enforces
  programmatic schema discovery before query authoring so the solution
  adapts to variant graphs that may differ in role representation,
  affiliation structure, and noise level.
---

# SPARQL Professors-Universities Query

## Task Summary

Given a Turtle file at `/app/university_graph.ttl`, write a SPARQL query that
returns exactly two variables — `?professorName` and `?universityName` — one
row per qualifying professor. Save to `/app/solution.sparql`.

## Execution Plan

Run each step in order. Do not skip Step 1 — later steps depend on its output.

---

### Step 1 — Mandatory Schema Discovery (run this script)

Execute the following Python script **in full** before writing any SPARQL.
It extracts every piece of structural information needed to author the query.

```bash
python3 << 'PYEOF'
from rdflib import Graph, Namespace, RDF, URIRef

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# --- 1. Namespace & prefixes ---
print("=== PREFIXES ===")
for prefix, ns in g.namespaces():
    if prefix:
        print(f"  {prefix}: {ns}")

# --- 2. All predicates ---
preds = sorted(set(str(p) for _, p, _ in g))
print("\n=== ALL PREDICATES ===")
for p in preds:
    print(f"  {p}")

# --- 3. All rdf:type values ---
types = sorted(set(str(o) for _, _, o in g.triples((None, RDF.type, None))))
print("\n=== ALL TYPES ===")
for t in types:
    print(f"  {t}")

# --- 4. Outgoing predicates from Person instances ---
persons = set(s for s, _, o in g.triples((None, RDF.type, None))
              if "Person" in str(o))
person_preds = sorted(set(str(p) for s in persons for _, p, _ in g.triples((s, None, None))))
print("\n=== PERSON OUTGOING PREDICATES ===")
for p in person_preds:
    print(f"  {p}")

# --- 5. All values of role-like predicates ---
# Check uni:role, uni:hasAcademicRank, uni:rankLabel, or any predicate
# whose local name contains "role" or "rank"
role_preds = [p for p in preds if "role" in p.lower() or "rank" in p.lower()]
print("\n=== ROLE/RANK PREDICATES & VALUES ===")
for rp in role_preds:
    vals = sorted(set(str(o) for _, _, o in g.triples((None, URIRef(rp), None))))
    print(f"  {rp}:")
    for v in vals:
        print(f"    - {v}")

# If no role/rank predicate found, fall back to all literal properties of persons
if not role_preds:
    print("  (no role/rank predicate found — showing all literal properties of persons)")
    for s in sorted(persons):
        for p, o in g.triples((s, None, None)):
            if not isinstance(o, URIRef):
                print(f"    {s} {p} = {o}")

# --- 6. Trace Person → organization chain ---
print("\n=== PERSON ORGANIZATION LINKS (sample) ===")
org_types_kw = ["Department", "University", "Faculty", "School", "Institute", "Organization"]
for s in sorted(persons):
    for _s2, p, o in g.triples((s, None, None)):
        if isinstance(o, URIRef):
            o_types = [str(t) for _s3, _p3, t in g.triples((o, RDF.type, None))]
            if any(kw in t for t in o_types for kw in org_types_kw):
                o_name = None
                ns_base = str(p).rsplit("/", 1)[0] + "/"
                for _s4, _p4, n in g.triples((o, URIRef(ns_base + "hasName"), None)):
                    o_name = n
                print(f"  {str(s).split('/')[-1]} --{str(p).split('/')[-1]}--> {str(o).split('/')[-1]}"
                      f"  (types: {o_types}, name: {o_name})")

# --- 7. Check for University-typed nodes and how they get names ---
print("\n=== UNIVERSITY NODES ===")
uni_nodes = set(s for s, _p5, o in g.triples((None, RDF.type, None))
                if "University" in str(o))
for u in sorted(uni_nodes):
    name_preds = [str(p) for _s6, p, _o2 in g.triples((u, None, None))
                  if "name" in str(p).lower() or "label" in str(p).lower()]
    sample_name = None
    for np in name_preds:
        triples = list(g.triples((u, URIRef(np), None)))
        sample_name = triples[0][2] if triples else None
    print(f"  {str(u).split('/')[-1]}  name_pred={name_preds}  sample={sample_name}")

PYEOF
```

**Study the output carefully.** Every subsequent decision depends on what you see.

---

### Step 2 — Decide the Professor Filter

Use the **ROLE/RANK PREDICATES & VALUES** output to select the correct filter:

```
IF a predicate with "role" or "rank" in its name exists:
    LET ?rolePred = that predicate URI
    LET role_values = its distinct literal values
    
    CLASSIFY each value:
      - contains "professor" (case-insensitive) → INCLUDE
      - does not contain "professor" → EXCLUDE
    
    IF all include/exclude decisions look correct:
      → FILTER: FILTER(CONTAINS(LCASE(?roleVar), "professor"))
    
    IF some values are ambiguous (e.g., "Prof.", "Professeur"):
      → Use broader matching:
        FILTER(CONTAINS(LCASE(?roleVar), "professor") ||
               CONTAINS(LCASE(?roleVar), "prof"))
    
    IF the predicate points to URIRef resources (not literals):
      → Check for a label sub-property:
        ?person ?rolePred ?rank .
        ?rank ?labelPred ?roleVar .
        FILTER(CONTAINS(LCASE(?roleVar), "professor"))
        (find ?labelPred from the PERSON ORGANIZATION LINKS or ALL PREDICATES output)

ELSE (no role/rank predicate):
    → Check if there is a class like uni:Professor:
        ?person a <ProfessorClassURI> .
    → If no such class exists, check all literal properties of Person
       for one whose values look like academic titles.
```

**Record**: `?rolePred` = ___, filter expression = ___.

---

### Step 3 — Decide the Affiliation Chain

Use the **PERSON ORGANIZATION LINKS** and **ALL PREDICATES** output.

```
LET personOutPreds = outgoing predicates from Person instances
LET target = a University-typed node

FOR each predicate P in personOutPreds:
    Follow P from a sample Person:
      - Does it reach a University-typed node directly?
        → Chain: ?person P ?university .
      - Does it reach an intermediate node (Department)?
        → From that intermediate, which predicate reaches University?
          Check: partOfUniversity, hasUniversity, belongsTo, etc.
        → Chain: ?person P ?intermediate . ?intermediate Q ?university .
      - Does it reach a Course?
        → From Course, check isTaughtIn → Department → partOfUniversity → University
        → Chain: ?person P ?course . ?course isTaughtIn ?dept . ?dept partOfUniversity ?university .

IF multiple chains exist:
    PREFER the one using worksAt (or its synonym) as the first hop.
    FALL BACK to teaches → isTaughtIn → partOfUniversity only if worksAt is absent.
    Use UNION only if some professors use one chain and others use another.

IF no chain reaches a University-typed node:
    Check ALL PREDICATES for any property whose objects are University-typed.
    Work backwards from University to Person.
```

**Record**: chain pattern = ___.

---

### Step 4 — Decide the Name Predicates

From the **PERSON OUTGOING PREDICATES** and **UNIVERSITY NODES** output:

```
Person name predicate: the predicate containing "name" in its local name
                       that has literal values on Person instances.
University name predicate: the predicate containing "name" in its local name
                           that has literal values on University instances.
```

These are usually the same predicate (e.g., `uni:hasName`) but verify both.

**Record**: person name pred = ___, university name pred = ___.

---

### Step 5 — Write the Query

Assemble using the recorded decisions:

```sparql
PREFIX <prefix>: <namespace-uri>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # Professor identification (from Step 2)
  ?person a <PersonClass> ;
          <personNamePred> ?professorName ;
          <rolePred> ?role .
  <filterExpression>

  # Affiliation chain (from Step 3)
  ?person <hop1Pred> <hop1Target> .
  # ... additional hops as needed ...
  ?university <universityNamePred> ?universityName .
}
```

Replace every `<...>` placeholder with the actual value discovered.
The `DISTINCT` keyword is mandatory to prevent duplicate rows from
multi-valued properties (teaches multiple courses, multiple departments, etc.).

---

### Step 6 — Validate

Run this script to verify the query:

```bash
python3 << 'PYEOF'
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

with open("/app/solution.sparql") as f:
    query = f.read()

results = g.query(query)

print(f"Variables: {[str(v) for v in results.vars]}")
print(f"Result count: {len(results)}")
for row in results:
    print(f"  {row[0]} -> {row[1]}")

# --- Structural checks ---
assert len(results.vars) == 2, f"Expected 2 variables, got {len(results.vars)}"
assert str(results.vars[0]) == "professorName", f"First var should be professorName, got {results.vars[0]}"
assert str(results.vars[1]) == "universityName", f"Second var should be universityName, got {results.vars[1]}"

rows = list(results)
assert len(rows) == len(set((str(r[0]), str(r[1])) for r in rows)), "Duplicate rows detected!"
for r in rows:
    assert r[0] is not None and str(r[0]).strip(), f"Empty professor name in row: {r}"
    assert r[1] is not None and str(r[1]).strip(), f"Empty university name in row: {r}"

print("\n✅ All structural checks passed")
print(f"   - 2 variables: professorName, universityName")
print(f"   - {len(rows)} rows, no duplicates, no empty values")
PYEOF
```

If any assertion fails, return to the relevant step and fix the query.

---

## Quick-Reference Decision Table

| Observation in discovery output | Action |
|---|---|
| `uni:role` has string values | `FILTER(CONTAINS(LCASE(?role), "professor"))` |
| `uni:hasAcademicRank` → URIRef resources | Add hop: `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?role .` then same FILTER |
| `a uni:Professor` class exists | Use `?person a uni:Professor` instead of FILTER |
| `worksAt` → Department, `partOfUniversity` → University | Two-hop chain through department |
| `worksAt` → University directly | One-hop: `?person uni:worksAt ?university` |
| No `worksAt`; `teaches` → Course → `isTaughtIn` → Dept → `partOfUniversity` | Three-hop through course and department |
| Both `worksAt` chain and `teaches` chain present for different persons | Use `UNION` of both paths |
| `uni:hasName` on both Person and University | Use `uni:hasName` for both `?professorName` and `?universityName` |
| Different name predicates for Person vs University | Use the correct predicate for each |
| Professor teaches multiple courses | `SELECT DISTINCT` handles deduplication |
| Multiple departments per university | `SELECT DISTINCT` handles deduplication |

## Common Pitfalls

1. **Skipping schema discovery** — reading the raw TTL file is not a
   substitute for programmatic inspection. Variants change predicates,
   chain structure, and role representations. Always run Step 1.
2. **Matching "Professor" exactly** — misses "Assistant Professor",
   "Associate Professor", "Prof.", etc. Always use case-insensitive
   substring matching.
3. **Forgetting DISTINCT** — any multi-valued property (teaches,
   worksAt multiple depts) produces duplicate rows.
4. **Hardcoding namespace** — always read the prefix from the file.
   The namespace URI and prefix may differ across variants.
5. **Projecting extra variables** — the output must contain exactly
   `?professorName` and `?universityName`, nothing else.
