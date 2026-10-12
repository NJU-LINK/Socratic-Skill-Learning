---
name: sparql-professors-universities
description: >
  Write SPARQL queries to extract professor names and their affiliated
  university names from a Turtle knowledge graph describing universities,
  departments, employees, students, and courses. The skill runs automatic
  BFS chain tracing from every Person to University-typed nodes so the
  student discovers the exact affiliation path (direct, two-hop, three-hop,
  or heterogeneous) without manual reasoning. Covers variants with
  different role representations, chain structures, and noise levels.
---

# SPARQL Professors-Universities Query

## Task Summary

Given a Turtle file at `/app/university_graph.ttl`, write a SPARQL query that
returns exactly two variables — `?professorName` and `?universityName` — one
row per qualifying professor. Save to `/app/solution.sparql`.

## Execution Plan

Run each step in order. Do not skip Step 1.

---

### Step 1 — Mandatory Schema Discovery (run this script)

Copy and execute this entire block. It discovers the graph structure
and traces the exact path from each Person to a University node.

```bash
python3 << 'PYEOF'
from rdflib import Graph, RDF, URIRef

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

def local(uri):
    s = str(uri)
    return s.split('#')[-1] if '#' in s else s.split('/')[-1]

# --- 1. Domain namespace ---
custom_ns = []
_noise = {"brick", "csvw", "dc", "dcat", "dcmitype", "dcterms",
          "dcam", "doap", "foaf", "odrl", "org", "owl", "prof",
          "prov", "qb", "rdf", "rdfs", "schema", "sh", "skos",
          "sosa", "ssn", "time", "vann", "void", "xsd", "xml"}
for prefix, ns in g.namespaces():
    if prefix and prefix not in _noise:
        custom_ns.append((prefix, str(ns)))
print("=== CUSTOM PREFIXES ===")
for prefix, ns in custom_ns:
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

# --- 4. Person outgoing predicates ---
persons = set(s for s, _, o in g.triples((None, RDF.type, None))
              if "Person" in str(o))
person_preds = sorted(set(str(p) for s in persons
                          for _, p, _ in g.triples((s, None, None))))
print("\n=== PERSON OUTGOING PREDICATES ===")
for p in person_preds:
    print(f"  {p}")

# --- 5. Role/rank predicates and all their values ---
role_preds = [p for p in preds if "role" in p.lower() or "rank" in p.lower()]
print("\n=== ROLE/RANK PREDICATES & VALUES ===")
for rp in role_preds:
    vals = sorted(set(str(o) for _, _, o in g.triples((None, URIRef(rp), None))))
    print(f"  {rp}:")
    for v in vals:
        print(f"    - {v}")
if not role_preds:
    print("  (none found — showing literal properties of persons)")
    for person_s in sorted(persons):
        for _s, p, o in g.triples((person_s, None, None)):
            if not isinstance(o, URIRef):
                print(f"    {local(person_s)} {local(p)} = {o}")

# --- 6. BFS: trace every Person → ... → University path ---
uni_nodes = set(s for s, _, o in g.triples((None, RDF.type, None))
                if "University" in str(o))

print("\n=== PERSON → UNIVERSITY CHAINS (BFS, max depth 5) ===")
chain_summary = {}  # pattern → list of person names
for person in sorted(persons):
    pname = None
    for _s, pred, obj in g.triples((person, None, None)):
        if "name" in str(pred).lower() and not isinstance(obj, URIRef):
            pname = str(obj)
            break
    visited = {person}
    frontier = [(person, [])]
    found_path = None
    for _d in range(5):
        new_frontier = []
        for node, path in frontier:
            for _s, p, o in g.triples((node, None, None)):
                if isinstance(o, URIRef) and o not in visited:
                    new_path = path + [(p, o)]
                    if o in uni_nodes:
                        found_path = new_path
                        break
                    visited.add(o)
                    new_frontier.append((o, new_path))
            if found_path:
                break
        if found_path:
            break
        frontier = new_frontier
    if found_path:
        parts = []
        for p, o in found_path:
            parts.append(local(p))
            o_types = [local(t) for _, _, t in g.triples((o, RDF.type, None))]
            otype = o_types[0] if o_types else "?"
            parts.append(otype)
        pattern = " → ".join(parts)
        chain_summary.setdefault(pattern, []).append(pname)
        print(f"  {pname}: {pattern}")
    else:
        print(f"  {pname}: NO PATH TO UNIVERSITY")
        chain_summary.setdefault("NO PATH", []).append(pname)

# Summarize distinct chain patterns
print("\n=== DISTINCT CHAIN PATTERNS ===")
for pattern, names in chain_summary.items():
    print(f"  {pattern}  ({len(names)} persons)")

# --- 7. Name predicates ---
print("\n=== NAME PREDICATES ===")
for tname in ["Person", "University", "Department"]:
    tnodes = set(s for s, _, o in g.triples((None, RDF.type, None))
                 if tname in str(o))
    for node in sorted(tnodes)[:2]:  # sample 2
        for _s, p, o in g.triples((node, None, None)):
            if "name" in str(p).lower() and not isinstance(o, URIRef):
                print(f"  {tname}: {local(p)} = {o}")
                break

PYEOF
```

**Study the output. Focus on:**
- **ROLE/RANK PREDICATES**: Which predicate? What values? Which contain "professor"?
- **DISTINCT CHAIN PATTERNS**: What is the path from qualifying professors to University?
- **NAME PREDICATES**: What predicate gives names to Person and University nodes?

---

### Step 2 — Decide the Professor Filter

Look at the **ROLE/RANK PREDICATES & VALUES** section.

| What you see | What to do |
|---|---|
| Predicate with literal string values (e.g., `"Professor of X"`, `"Assistant Professor of X"`, `"Lecturer"`, `"Student"`) | Use `FILTER(CONTAINS(LCASE(?role), "professor"))` on that predicate |
| Predicate whose values are **URIs** (not literals) | The URIs point to rank resources. Find a label/name predicate on those resources (check ALL PREDICATES for one with "label" or "name"). Add a hop: `?person <rolePred> ?rank . ?rank <labelPred> ?role .` then FILTER on `?role` |
| No role/rank predicate exists | Check ALL TYPES for a class like `Professor`. If found, use `?person a <ProfessorClass>` instead of a FILTER |

**Always use case-insensitive matching** (`LCASE` + `CONTAINS`).
Common near-misses to be aware of: "Prof.", "Professeur", "Profesor".
If these appear, broaden: `CONTAINS(LCASE(?role), "prof")`.

---

### Step 3 — Decide the Affiliation Chain

Look at the **DISTINCT CHAIN PATTERNS** section. It tells you the exact path.

Common patterns (use whichever appears for qualifying persons):

| Chain pattern | SPARQL |
|---|---|
| `worksAt → Department → partOfUniversity → University` | `?person <hop1> ?dept . ?dept <hop2> ?university .` |
| `worksAt → University` (direct) | `?person <hop1> ?university .` |
| `teaches → Course → isTaughtIn → Department → partOfUniversity → University` | `?person <hop1> ?course . ?course <hop2> ?dept . ?dept <hop3> ?university .` |
| Mixed patterns (some persons use one chain, others use another) | Use `{ ... } UNION { ... }` to cover both |

**Replace `<hopN>` with the actual predicate URIs shown in the chain output.**

If the qualifying persons (those matching the professor filter) use a
different chain than non-qualifying persons (students, staff), use only
the chain that qualifying persons use.

---

### Step 4 — Write the Query

Combine Steps 2 and 3. The template:

```sparql
PREFIX <pfx>: <namespace-from-PREFIXES-output>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # --- Professor identification (Step 2) ---
  ?person a <PersonClass> ;
          <namePred> ?professorName ;
          <rolePred> ?role .
  <filterExpression>

  # --- Affiliation chain (Step 3) ---
  ?person <hop1> ?intermediate .
  # ... additional hops ...
  ?university <uniNamePred> ?universityName .
}
```

Replace every `<...>` placeholder with actual values.
`DISTINCT` is **mandatory** — it prevents duplicates when a person has
multiple courses, teaches in multiple departments, etc.

---

### Step 5 — Validate

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

# Structural checks
assert len(results.vars) == 2, f"Expected 2 vars, got {len(results.vars)}"
assert str(results.vars[0]) == "professorName"
assert str(results.vars[1]) == "universityName"
rows = list(results)
assert len(rows) == len(set((str(r[0]), str(r[1])) for r in rows)), "Duplicates!"
for r in rows:
    assert r[0] and str(r[0]).strip(), f"Empty prof name: {r}"
    assert r[1] and str(r[1]).strip(), f"Empty uni name: {r}"

# Cross-check: independently count professor-like roles
prof_count = 0
from rdflib import URIRef
role_preds = [str(p) for p in set(p for _, p, _ in g)
              if "role" in str(p).lower() or "rank" in str(p).lower()]
for rp in role_preds:
    for _, _, o in g.triples((None, URIRef(rp), None)):
        if "professor" in str(o).lower():
            prof_count += 1
if prof_count:
    assert len(rows) == prof_count, \
        f"Query returned {len(rows)} rows but independent count is {prof_count}"

print(f"\n✅ All checks passed: {len(rows)} professors, no duplicates")
PYEOF
```

If any assertion fails, return to the relevant step and fix the query.

---

## Quick-Reference Decision Table

| Observation | Action |
|---|---|
| `uni:role` has string values with "professor" | `FILTER(CONTAINS(LCASE(?role), "professor"))` |
| `uni:hasAcademicRank` → URIRef resources | Add: `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?role .` then same FILTER on `?role` |
| `a uni:Professor` class exists, no role predicate | `?person a uni:Professor .` (no FILTER needed) |
| Chain: `worksAt → Department → partOfUniversity → University` | Two-hop: `?person P1 ?dept . ?dept P2 ?university .` |
| Chain: `worksAt → University` | One-hop: `?person P1 ?university .` |
| Chain: `teaches → Course → isTaughtIn → Dept → partOfUniversity → University` | Three-hop through course and department |
| Two different chains for different persons | `{ chain1 } UNION { chain2 }` |
| `uni:hasName` on both Person and University | Same pred for `?professorName` and `?universityName` |
| Professor teaches multiple courses / depts | `SELECT DISTINCT` handles it |
| Near-miss roles like "Prof.", "Professeur" | Broaden filter: `CONTAINS(LCASE(?role), "prof")` |

## Common Pitfalls

1. **Skipping discovery** — always run Step 1. Variants change predicates,
   chain depth, and role representations.
2. **Matching "Professor" exactly** — misses "Assistant Professor",
   "Associate Professor". Always `CONTAINS` + `LCASE`.
3. **Forgetting DISTINCT** — any multi-valued property creates duplicate rows.
4. **Hardcoding namespace** — read from the PREFIXES output.
5. **Projecting extra variables** — only `?professorName` and `?universityName`.
6. **Using student/staff chain** — the BFS shows chains for all persons;
   use only the chain that qualifying professors follow.
