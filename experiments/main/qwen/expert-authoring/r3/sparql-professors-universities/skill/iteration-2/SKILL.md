---
name: sparql-professors-universities
description: >
  Write a SPARQL query that retrieves professor names and their affiliated
  university names from a Turtle knowledge graph. The graph contains persons
  with academic roles (professors, lecturers, students, staff), organizational
  units (departments, universities), and relationships between them. The query
  must correctly identify qualifying professors, trace the affiliation path to
  the university, and return exactly one row per professor-university pair.
---

# SPARQL Professors–Universities Query

## Task

Given a Turtle file at `/app/university_graph.ttl`, write a SPARQL query and
save it to `/app/solution.sparql`. The query must return two variables:

- `?professorName` — name of each qualifying professor
- `?universityName` — name of the university they work in

**Exactly one row per professor-university pair. No duplicates. No missing
professors. No non-professors.**

---

## Step 1 — Run Full Graph Discovery (MANDATORY, do first)

Copy and run this **entire** Python block in one `task_shell` call. It
discovers the ontology, role values, and the affiliation path from Person to
University. Do not skip this step or try to read the file manually.

```python
python3 << 'DISCOVERY'
import rdflib
from rdflib import RDF

g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# --- Prefixes ---
print("=== PREFIXES ===")
with open("/app/university_graph.ttl") as f:
    for line in f:
        if line.strip().startswith("@prefix"):
            print("  " + line.strip())

# --- All predicates with counts ---
print("\n=== PREDICATES ===")
from collections import Counter
pred_counts = Counter(str(p) for _, p, _ in g)
for p, c in sorted(pred_counts.items()):
    print(f"  {p}  ({c})")

# --- All classes ---
print("\n=== CLASSES ===")
class_counts = Counter(str(o) for _, _, o in g.triples((None, RDF.type, None)))
for c, n in sorted(class_counts.items()):
    print(f"  {c}  ({n} instances)")

# --- Role/rank values (find the predicate dynamically) ---
print("\n=== ROLE/RANK VALUES ===")
def local_name(uri):
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]

role_pred = None
for p in pred_counts:
    if any(k in local_name(p).lower() for k in ("role", "rank", "position", "title")):
        role_pred = rdflib.URIRef(p)
        print(f"  Role predicate: {p}")
        break
if role_pred:
    role_vals = Counter(str(o) for _, _, o in g.triples((None, role_pred, None)))
    for v, c in sorted(role_vals.items()):
        marker = " <-- PROFESSOR" if "professor" in v.lower() else ""
        print(f"    '{v}'  ({c}){marker}")
else:
    print("  No role/rank predicate found! Check predicates above.")

# --- Affiliation path discovery ---
print("\n=== AFFILIATION PATH (Person -> University) ===")

# Find University CLASS (the rdf:type value, not a predicate)
# Uses local_name() defined above to avoid namespace false matches
uni_type = None
for _, _, o in g.triples((None, RDF.type, None)):
    ln = local_name(o)
    if ln.lower() == 'university':
        uni_type = o
        break

if uni_type:
    print(f"  University class: {uni_type}")
    unis = set(s for s, _, _ in g.triples((None, RDF.type, uni_type)))
    print(f"  University instances: {len(unis)}")
else:
    unis = set()
    print("  No University class found")

# Pick a professor and trace their outgoing edges
if role_pred:
    for person, _, role_val in g.triples((None, role_pred, None)):
        if "professor" in str(role_val).lower():
            print(f"\n  Sample professor: {person}")
            print(f"  Outgoing edges:")
            for _, p, o in g.triples((person, None, None)):
                # Skip rdf:type, hasName, role (noise)
                if p == RDF.type: continue
                if "name" in local_name(p).lower(): continue
                if p == role_pred: continue
                is_uni = "(-> University!)" if o in unis else ""
                print(f"    {p} -> {o} {is_uni}")
                # Follow one more hop from the target
                for _, p2, o2 in g.triples((o, None, None)):
                    if p2 == RDF.type: continue
                    is_uni2 = "(-> University!)" if o2 in unis else ""
                    print(f"      {p2} -> {o2} {is_uni2}")
            break

# --- Name predicate discovery ---
print("\n=== NAME PREDICATE ===")
for p in pred_counts:
    ln = local_name(p)
    if "name" in ln.lower():
        print(f"  {p}")

print("\n=== DONE ===")
DISCOVERY
```

This output tells you:
- The **namespace prefix** to use in `PREFIX` declarations
- The **role predicate** and which values contain "professor"
- The **exact path** from a Person to a University (1-hop? 2-hop? longer?)
- The **name predicate** for both persons and universities

---

## Step 2 — Build the Query from Discovery Results

### 2a. Professor identification filter

Use the role predicate and values discovered above. The universal filter:

```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
```

This catches "Professor of X", "Assistant Professor of X", "Associate
Professor", "Full Professor" — while excluding "Lecturer", "Student", etc.

**Critical**: Use `CONTAINS`, not `STRSTARTS` or exact match. "Assistant
Professor" starts with "Assistant", not "Professor".

### 2b. Affiliation path

Use the path discovered in Step 1. Choose the matching template:

**Two-hop (Person → Department → University)**:
```sparql
?professor <WORKS_AT_PRED> ?dept .
?dept <PART_OF_PRED> ?university .
```

**Direct (Person → University)**:
```sparql
?professor <AFFILIATION_PRED> ?university .
```

**Three-hop or longer**: Chain intermediate nodes accordingly.

### 2c. Name bindings

```sparql
?professor <NAME_PRED> ?professorName .
?university <NAME_PRED> ?universityName .
```

### 2d. Assemble the full query

```sparql
PREFIX ns: <DISCOVERED_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor ns:hasName ?professorName ;
             ns:role ?role ;
             ns:worksAt ?dept .
  ?dept ns:partOfUniversity ?university .
  ?university ns:hasName ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
```

Replace `ns:`, `role`, `worksAt`, `partOfUniversity`, `hasName` with the
actual predicates from Step 1. **Always use `SELECT DISTINCT`** to prevent
duplicate rows from multi-valued properties (e.g., a professor teaching
multiple courses).

### 2e. Variant: rank-as-resource

If Step 1 shows no string roles but instead a predicate pointing to a
resource (e.g., `uni:hasAcademicRank` → resource with `uni:rankLabel`):

```sparql
?professor ns:hasAcademicRank ?rank .
?rank ns:rankLabel ?role .
FILTER(CONTAINS(LCASE(?role), "professor"))
```

---

## Step 3 — Write and Verify (MANDATORY)

Write the query to `/app/solution.sparql`, then run this verification block:

```python
python3 << 'VERIFY'
import rdflib
from rdflib import RDF
from collections import Counter

g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# Load and run the solution
with open("/app/solution.sparql") as f:
    query = f.read()

print("=== QUERY ===")
for i, line in enumerate(query.strip().split("\n"), 1):
    print(f"  {i}: {line}")

try:
    results = g.query(query)
except Exception as e:
    print(f"\nERROR: Query failed: {e}")
    exit(1)

print(f"\n=== RESULTS ({len(results)} rows) ===")
var_names = [str(v) for v in results.vars]
print(f"Variables: {var_names}")

# Check variable names
expected = {"professorName", "universityName"}
actual = set(var_names)
if actual != expected:
    print(f"WARNING: Expected {expected}, got {actual}")

seen = set()
dups = 0
for row in results:
    key = (str(row[0]), str(row[1]))
    dup_marker = ""
    if key in seen:
        dups += 1
        dup_marker = " [DUPLICATE]"
    seen.add(key)
    print(f"  {row[0]}  ->  {row[1]}{dup_marker}")

print(f"\n=== CHECKS ===")
print(f"  Variables correct: {actual == expected}")
print(f"  Duplicates: {dups}")

# Cross-check: find all professors independently
def local_name(uri):
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]

role_pred = None
missing, extra = set(), set()
for p in set(str(p) for _, p, _ in g):
    if "role" in local_name(p).lower() or "rank" in local_name(p).lower():
        role_pred = rdflib.URIRef(p)
        break

if role_pred:
    prof_names = set()
    for _, _, v in g.triples((None, role_pred, None)):
        if "professor" in str(v).lower():
            for s2, _, _ in g.triples((None, role_pred, v)):
                for _, p2, name in g.triples((s2, None, None)):
                    if "name" in local_name(p2).lower():
                        prof_names.add(str(name))
    result_names = set(str(row[0]) for row in results)
    missing = prof_names - result_names
    extra = result_names - prof_names
    print(f"  Expected professors: {len(prof_names)}")
    print(f"  Returned professors: {len(result_names)}")
    if missing:
        print(f"  MISSING: {missing}")
    if extra:
        print(f"  EXTRA (non-professors?): {extra}")
    if not missing and not extra:
        print(f"  All professors matched, no extras. PASS.")

all_pass = (actual == expected) and (dups == 0) and (not missing) and (not extra)
print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL - fix before submitting'}")
VERIFY
```

If any check fails, fix the query and re-verify before finishing.

---

## Quick-Reference Decision Table

| Situation | Action |
|-----------|--------|
| Role is a string (e.g., `"Professor of X"`) | `FILTER(CONTAINS(LCASE(?role), "professor"))` |
| Role is a resource with a label | Bind `?rank uni:rankLabel ?role` then same filter |
| Path is Person→Dept→University | Two triple patterns via intermediate `?dept` |
| Path is Person→University (direct) | One triple pattern |
| Multiple paths possible | Use `UNION` of paths, still `SELECT DISTINCT` |
| Duplicate rows | Add `DISTINCT` to SELECT |
| Unsure about predicates | Run Step 1 discovery block |

## Common Mistakes

| Mistake | Why it fails | Fix |
|---------|-------------|-----|
| `?role = "Professor"` | Misses "Assistant Professor", "Professor of X" | Use `CONTAINS(LCASE(...))` |
| `STRSTARTS(?role, "Professor")` | "Assistant Professor" starts with "A" | Use `CONTAINS` |
| Omitting `DISTINCT` | Duplicates from multi-valued properties | Always `SELECT DISTINCT` |
| Hardcoding `uni:` prefix | Namespace may differ in variants | Extract from `@prefix` lines |
| Hardcoding two-hop path | Variant may use direct or longer path | Run Step 1 discovery |
| Projecting extra variables (e.g., `?role`) | Tests expect exactly 2 variables | Only `?professorName ?universityName` |
| Not verifying results | Silent failures on variant graphs | Always run Step 3 verify block |
