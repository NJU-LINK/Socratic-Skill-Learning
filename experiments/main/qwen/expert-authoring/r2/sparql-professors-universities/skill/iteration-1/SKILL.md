---
name: sparql-professors-universities
description: >
  Write SPARQL queries to extract professor names and their affiliated
  university names from a Turtle knowledge graph describing universities,
  departments, employees, students, and courses. The skill covers schema
  discovery, professor-role identification, affiliation-chain tracing,
  and result validation against varying graph structures.
---

# SPARQL Professors-Universities Query

## Task Summary

Given a Turtle file at `/app/university_graph.ttl`, write a SPARQL query that
returns two variables — `?professorName` and `?universityName` — one row per
qualifying professor. Save the query to `/app/solution.sparql`.

## Execution Strategy

Follow these phases in order. Each phase produces concrete artifacts (notes,
query fragments, result counts) that feed the next.

### Phase 1 — Schema Discovery

1. **Load and inspect the graph** with Python + rdflib:
   ```python
   from rdflib import Graph, Namespace
   g = Graph()
   g.parse("/app/university_graph.ttl", format="turtle")
   UNI = Namespace("http://university.org/ontology#")
   ```
2. **Enumerate all predicates, types, and role values**:
   - `set(str(p) for _, p, _ in g)` — all predicates
   - `set(str(o) for _, _, o in g.triples((None, RDF.type, None)))` — all class types
   - `set(str(o) for _, _, o in g.triples((None, UNI.role, None)))` — all role strings (if `uni:role` exists)
   - Also check for `uni:hasAcademicRank` / `uni:rankLabel` patterns if `uni:role` is absent.
3. **Identify the namespace** used in the file (commonly `uni:` but confirm).
4. **Record** the class hierarchy: which `rdf:type` values appear (e.g., `Person`, `University`, `Department`, `Course`).

### Phase 2 — Identify Professor Qualification Rule

The graph distinguishes qualifying professors from non-target roles (lecturers,
students, staff). Use the schema discovery output to decide which rule applies:

| Signal in graph | Rule |
|---|---|
| `uni:role` literal strings present | Match strings containing the substring `"professor"` (case-insensitive). This captures "Professor of X", "Assistant Professor of X", "Associate Professor of X", etc. |
| `uni:hasAcademicRank` + `uni:rankLabel` | Match rank labels containing `"professor"` (case-insensitive). |
| Explicit class `uni:Professor` | Use `?person a uni:Professor`. |
| Multiple rank indicators | Prefer the most specific; fall back to role-string matching. |

**Important**: Always use case-insensitive matching — `FILTER(CONTAINS(LCASE(?role), "professor"))` — to handle spelling variations.

**Exclusions**: Students, Lecturers, and generic Staff will not match the
"professor" substring. Verify by listing all role values and confirming which
should be included vs. excluded.

### Phase 3 — Trace the Affiliation Chain

Determine how a Person connects to a University. Inspect sample triples:

```python
for s, p, o in g.triples((None, UNI.worksAt, None)):
    print(s, "->", o)
```

Common chain patterns (use whichever the graph actually contains):

| Chain pattern | SPARQL path |
|---|---|
| Person → Department → University | `?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni .` |
| Person → University (direct) | `?person uni:worksAt ?uni . ?uni a uni:University .` |
| Person → Department → University (via inverse) | `?uni uni:hasDepartment ?dept . ?person uni:worksAt ?dept .` |
| Person → Course → Department → University | `?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni .` |
| Person → Appointment → University | `?person uni:hasAppointment ?appt . ?appt uni:atUniversity ?uni .` |

**Decision rule**: Check which predicates exist outgoing from Person instances
and which lead to a `uni:University` typed node. Use the shortest reliable path.

If both a primary path (e.g., `worksAt` → `partOfUniversity`) and a fallback
(e.g., `teaches` → `isTaughtIn` → `partOfUniversity`) exist, prefer the
primary. Use `UNION` only if the task explicitly requires it.

### Phase 4 — Write the Query

Assemble the query from the discovered components:

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  # --- Professor identification ---
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))

  # --- Affiliation chain (adapt to actual graph) ---
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
```

**Key design choices**:
- `SELECT DISTINCT` — prevents duplicate rows when a professor has multiple
  courses, appointments, or other multi-valued properties.
- Use `uni:hasName` for both professor and university names (the typical
  name predicate). Confirm the actual predicate from Phase 1.
- Bind `?role` but do **not** project it — only `?professorName` and
  `?universityName` should appear in results.

### Phase 5 — Validate

Run the query and inspect results:

```python
from rdflib import Graph
g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
with open("/app/solution.sparql") as f:
    query = f.read()
results = g.query(query)
print(f"Result count: {len(results)}")
print(f"Variables: {[str(v) for v in results.vars]}")
for row in results:
    print(row)
```

**Validation checklist**:
- [ ] Exactly two variables: `?professorName`, `?universityName`
- [ ] Result count equals the number of qualifying professors in the graph
- [ ] Every row has a non-empty professor name and university name
- [ ] No lecturers, students, or staff appear
- [ ] No duplicate rows (same professor-university pair appearing twice)
- [ ] Each professor appears exactly once (assuming one university per professor)

**Cross-check**: Count persons with qualifying roles independently:
```python
count = sum(1 for _, _, o in g.triples((None, UNI.role, None))
            if "professor" in str(o).lower())
print(f"Expected professor count: {count}")
```
Verify this matches the query result count.

## Common Pitfalls

1. **Matching only "Professor" exactly** — misses "Assistant Professor" and
   "Associate Professor". Always use `CONTAINS` + `LCASE`.
2. **Forgetting DISTINCT** — professors teaching multiple courses produce
   duplicate rows without it.
3. **Wrong affiliation chain** — always verify by inspecting actual triples
   rather than guessing the path.
4. **Projecting extra variables** — the task asks for exactly
   `?professorName` and `?universityName`.
5. **Hardcoding namespace** — read the actual `@prefix` from the file; it may
   differ from `uni:`.

## Adaptation Notes

When the graph structure varies from the anchor realization:
- **Different role representation**: If roles use `uni:hasAcademicRank`
  resources instead of string literals, replace the FILTER with a pattern
  match on rank labels: `?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?label . FILTER(CONTAINS(LCASE(?label), "professor"))`.
- **Direct university affiliation**: If `uni:worksAt` points directly to a
  `uni:University`, remove the intermediate `?dept` hop.
- **Heterogeneous chains**: If some professors link through departments and
  others directly, use `UNION` to cover both paths.
- **Increased noise**: With larger graphs, the DISTINCT and the
  case-insensitive FILTER remain correct; just verify result count scales
  appropriately.
