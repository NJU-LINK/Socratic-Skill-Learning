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

Given `/app/university_graph.ttl`, write a SPARQL query to `/app/solution.sparql`
that returns `?professorName` and `?universityName` — exactly one row per
professor-university pair. No duplicates. No missing professors. No non-professors.

---

## Step 1 — Discover the Graph (MANDATORY)

Run this **entire** block in one `task_shell` call. It discovers the ontology,
traces **all** professors' paths to their university, and checks for unreachable
professors. **Do not skip or shorten it.**

```python
python3 << 'DISCOVER'
import rdflib
from rdflib import RDF
from collections import Counter

g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

def ln(uri):
    """Local name of a URI, ignoring namespace."""
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]

# Prefixes
print("=== PREFIXES ===")
with open("/app/university_graph.ttl") as f:
    for line in f:
        if line.strip().startswith("@prefix"):
            print("  " + line.strip())

# Predicates
print("\n=== PREDICATES ===")
pc = Counter(str(p) for _, p, _ in g)
for p, c in sorted(pc.items()):
    print(f"  {p}  ({c})")

# Classes
print("\n=== CLASSES ===")
cc = Counter(str(o) for _, _, o in g.triples((None, RDF.type, None)))
for c, n in sorted(cc.items()):
    print(f"  {c}  ({n})")

# Role predicate and values
print("\n=== ROLES ===")
role_pred = None
for p in pc:
    if any(k in ln(p).lower() for k in ("role", "rank", "position", "title")):
        role_pred = rdflib.URIRef(p)
        print(f"  Predicate: {p}")
        break
prof_role_vals = set()
if role_pred:
    for v, c in sorted(Counter(str(o) for _, _, o in g.triples((None, role_pred, None))).items()):
        tag = ""
        if "professor" in v.lower():
            tag = " <-- PROFESSOR"
            prof_role_vals.add(v)
        print(f"    '{v}' ({c}){tag}")

# University class (by local name)
uni_class = None
for _, _, o in g.triples((None, RDF.type, None)):
    if ln(o).lower() == 'university':
        uni_class = o
        break
unis = set(s for s, _, _ in g.triples((None, RDF.type, uni_class))) if uni_class else set()
print(f"\n=== UNIVERSITY CLASS: {uni_class} ({len(unis)} instances) ===")

# Name predicate
name_pred = None
for p in pc:
    if ln(p).lower() == 'hasname' or ln(p).lower() == 'name':
        name_pred = rdflib.URIRef(p)
        break
print(f"\n=== NAME PREDICATE: {name_pred} ===")

# Trace ALL professors' paths
print(f"\n=== ALL PROFESSOR PATHS ===")
affiliation_pred = None  # the pred that reaches university (directly or via dept)
professors = []
unreachable = []

if role_pred:
    for person, _, rv in g.triples((None, role_pred, None)):
        if "professor" not in str(rv).lower():
            continue
        # Get this person's name
        pname = "?"
        if name_pred:
            for _, _, n in g.triples((person, name_pred, None)):
                pname = str(n)

        # Find outgoing edges (excluding type, name, role)
        reached_uni = False
        # BFS: explore by depth to find shortest path
        # Skip noise predicates (type, name, role)
        def is_noise(pred):
            if pred == RDF.type or pred == role_pred:
                return True
            if name_pred and pred == name_pred:
                return True
            return False

        # Depth 1: direct reach
        for _, ep, eo in g.triples((person, None, None)):
            if is_noise(ep): continue
            if eo in unis:
                print(f"  {pname}: {ln(ep)} -> University (1-hop, DIRECT)")
                affiliation_pred = ep
                reached_uni = True
                professors.append((pname, str(person)))
                break
        if reached_uni:
            continue

        # Depth 2: person -> X -> University
        for _, ep, eo in g.triples((person, None, None)):
            if is_noise(ep): continue
            for _, ep2, eo2 in g.triples((eo, None, None)):
                if ep2 == RDF.type: continue
                if eo2 in unis:
                    print(f"  {pname}: {ln(ep)} -> {ln(eo)} -> {ln(ep2)} -> University (2-hop)")
                    if affiliation_pred is None:
                        affiliation_pred = ep
                    reached_uni = True
                    professors.append((pname, str(person)))
                    break
            if reached_uni:
                break
        if reached_uni:
            continue

        # Depth 3: person -> X -> Y -> University
        for _, ep, eo in g.triples((person, None, None)):
            if is_noise(ep): continue
            for _, ep2, eo2 in g.triples((eo, None, None)):
                if ep2 == RDF.type: continue
                for _, ep3, eo3 in g.triples((eo2, None, None)):
                    if ep3 == RDF.type: continue
                    if eo3 in unis:
                        print(f"  {pname}: {ln(ep)} -> {ln(eo)} -> {ln(ep2)} -> {ln(eo2)} -> {ln(ep3)} -> University (3-hop)")
                        if affiliation_pred is None:
                            affiliation_pred = ep
                        reached_uni = True
                        professors.append((pname, str(person)))
                        break
                if reached_uni:
                    break
            if reached_uni:
                break

        if not reached_uni:
            unreachable.append(pname)
            print(f"  {pname}: NO PATH TO UNIVERSITY FOUND")

print(f"\n=== SUMMARY ===")
print(f"  Professors found: {len(professors)}")
print(f"  Unreachable: {len(unreachable)}")
if unreachable:
    print(f"  WARNING: These professors have no path to a university: {unreachable}")
    print(f"  Check if they use a different affiliation predicate or are missing data.")
if affiliation_pred:
    print(f"  Primary affiliation predicate: {affiliation_pred}")

# Check for path heterogeneity
path_types = Counter()
if role_pred and affiliation_pred:
    for person, _, rv in g.triples((None, role_pred, None)):
        if "professor" not in str(rv).lower():
            continue
        has_direct = any(o in unis for _, p, o in g.triples((person, affiliation_pred, None)))
        has_indirect = False
        for _, _, dept in g.triples((person, affiliation_pred, None)):
            if dept not in unis:
                for _, _, o2 in g.triples((dept, None, None)):
                    if o2 in unis:
                        has_indirect = True
                        break
        if has_direct:
            path_types["direct"] += 1
        elif has_indirect:
            path_types["indirect-via-dept"] += 1
        else:
            path_types["other/unknown"] += 1
    if len(path_types) > 1:
        print(f"  WARNING: Multiple path types detected: {dict(path_types)}")
        print(f"  You may need UNION or property paths in the query.")
    else:
        print(f"  Path type: {dict(path_types)}")

print("\n=== DONE ===")
DISCOVER
```

Read the output and note:
- **PREFIXES**: namespace for SPARQL `PREFIX` declarations
- **ROLES**: which role predicate and values to filter with `CONTAINS(LCASE(...), "professor")`
- **UNIVERSITY CLASS**: confirms universities exist and how many
- **NAME PREDICATE**: predicate for `?professorName` and `?universityName`
- **ALL PROFESSOR PATHS**: the exact predicate chain each professor uses to reach their university
- **SUMMARY**: number of professors, any unreachable ones, path homogeneity check

---

## Step 2 — Build the Query

Use the discovery output to choose the correct template.

### Professor filter (universal)

```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
```

Use `CONTAINS` (not `STRSTARTS` or `=`) because "Assistant Professor" starts with "A".

### Template: two-hop via department (most common)

Use when SUMMARY shows `indirect-via-dept` path type:

```sparql
PREFIX <ns>: <DISCOVERED_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor <ns:hasName> ?professorName ;
             <ns:role> ?role ;
             <ns:worksAt> ?dept .
  ?dept <ns:partOfUniversity> ?university .
  ?university <ns:hasName> ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
```

Replace `<ns:hasName>`, `<ns:role>`, `<ns:worksAt>`, `<ns:partOfUniversity>`
with actual predicates from discovery.

### Template: direct affiliation

Use when SUMMARY shows `direct` path type:

```sparql
PREFIX <ns>: <DISCOVERED_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor <ns:hasName> ?professorName ;
             <ns:role> ?role ;
             <AFFILIATION_PRED> ?university .
  ?university <ns:hasName> ?universityName .
  FILTER(CONTAINS(LCASE(?role), "professor"))
}
```

### Template: heterogeneous paths

If SUMMARY shows multiple path types, use `UNION`:

```sparql
SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor <ns:hasName> ?professorName ;
             <ns:role> ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  {
    ?professor <ns:worksAt> ?dept .
    ?dept <ns:partOfUniversity> ?university .
  } UNION {
    ?professor <ns:affiliatedWith> ?university .
  }
  ?university <ns:hasName> ?universityName .
}
```

### Template: rank-as-resource variant

If ROLES shows no string roles but a rank predicate pointing to resources:

```sparql
?professor <ns:hasAcademicRank> ?rank .
?rank <ns:rankLabel> ?role .
FILTER(CONTAINS(LCASE(?role), "professor"))
```

**Always include `SELECT DISTINCT`** — prevents duplicates from multi-valued properties.

---

## Step 3 — Write and Verify (MANDATORY)

Write your query to `/app/solution.sparql`, then run:

```python
python3 << 'VERIFY'
import rdflib
from rdflib import RDF

g = rdflib.Graph()
g.parse("/app/university_graph.ttl", format="turtle")

with open("/app/solution.sparql") as f:
    query = f.read()

print("QUERY:")
for i, line in enumerate(query.strip().split("\n"), 1):
    print(f"  {i}: {line}")

try:
    results = g.query(query)
except Exception as e:
    print(f"\nERROR: {e}")
    exit(1)

def ln(uri):
    s = str(uri)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]

vars = set(str(v) for v in results.vars)
expected = {"professorName", "universityName"}
print(f"\n{len(results)} rows, variables: {vars}")

seen, dups = set(), 0
for row in results:
    k = (str(row[0]), str(row[1]))
    if k in seen: dups += 1
    seen.add(k)
    print(f"  {row[0]}  ->  {row[1]}")

# Cross-check
role_pred = None
for p in set(str(p) for _, p, _ in g):
    if any(k in ln(p).lower() for k in ("role", "rank")):
        role_pred = rdflib.URIRef(p)
        break

missing, extra = set(), set()
if role_pred:
    prof_names = set()
    name_pred = None
    for p in set(str(p) for _, p, _ in g):
        if ln(p).lower() in ("hasname", "name"):
            name_pred = rdflib.URIRef(p)
            break
    if name_pred:
        for _, _, v in g.triples((None, role_pred, None)):
            if "professor" in str(v).lower():
                for s2, _, _ in g.triples((None, role_pred, v)):
                    for _, _, n in g.triples((s2, name_pred, None)):
                        prof_names.add(str(n))
    result_names = set(str(r[0]) for r in results)
    missing = prof_names - result_names
    extra = result_names - prof_names

ok = (vars == expected) and (dups == 0) and (not missing) and (not extra)
print(f"\nChecks: vars={'OK' if vars==expected else 'FAIL'} dups={dups} missing={len(missing)} extra={len(extra)}")
if missing: print(f"  MISSING: {missing}")
if extra: print(f"  EXTRA: {extra}")
print(f"RESULT: {'PASS' if ok else 'FAIL - FIX BEFORE SUBMITTING'}")
VERIFY
```

If RESULT is FAIL, fix the query and re-run this step.

---

## Quick Reference

| Problem | Solution |
|---------|----------|
| Role is a string like `"Professor of X"` | `FILTER(CONTAINS(LCASE(?role), "professor"))` |
| Role is a resource with label | Bind rank resource → `rankLabel` then filter |
| Person→Dept→University | Two triple patterns via `?dept` |
| Person→University (direct) | One triple pattern |
| Mixed path types | `UNION` of paths |
| Duplicate rows | `SELECT DISTINCT` |
| Unsure about predicates | Run Step 1 discovery |
| Some professors unreachable | Check discovery SUMMARY for warnings |

## Common Mistakes to Avoid

| Mistake | Why | Fix |
|---------|-----|-----|
| `?role = "Professor"` | Misses "Assistant Professor" etc. | `CONTAINS(LCASE(...))` |
| `STRSTARTS(?role, "Professor")` | "Assistant Professor" starts with "A" | `CONTAINS` |
| No `DISTINCT` | Duplicates from multi-valued props | Always `SELECT DISTINCT` |
| Hardcoding `uni:` prefix | May differ in variants | Extract from `@prefix` lines |
| Hardcoding two-hop path | May be direct or longer | Run Step 1 discovery |
| Extra projected variables | Tests expect exactly 2 | Only `?professorName ?universityName` |
| Skipping verification | Silent failures | Always run Step 3 |
