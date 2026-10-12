---
name: sparql-professors-universities
description: >
  Generate SPARQL queries to retrieve professor names and their affiliated 
  university names from RDF knowledge graphs. Uses pattern-based professor 
  identification with spec-declared near-miss exclusions.
---

# SPARQL Professors-Universities Query Skill

## Purpose

Generate a SPARQL query that retrieves all professors and the universities they work at,
using pattern-based identification that generalizes across different data variants.

## Critical Epistemic Rule

**The graded artifact is a function applied to data you cannot fully observe; encode the SEMANTIC RULE, never the observed INSTANCES.**

- Your query will be executed against a hidden test variant of the graph
- Discovery queries on visible data reveal what patterns exist, but the actual query must encode a *rule* that transfers to unseen instances
- Enumeration (VALUES, IN lists) is only for *discovery* — never the final query unless explicitly required

## Evidence Hierarchy for Robustifications

| Level | Source | Authority | Application |
|-------|--------|-----------|-------------|
| **(a) Family spec** | `spec.yaml` declarations | Family-wide, survives to hidden data | **Unconditional** — implement declared invariants |
| **(b) Task instruction** | `task.yaml` text | Variant-level | **Conditional override** — when explicitly stated |
| **(c) Visible probes** | P1–P3 on visible TTL | Instance-level, blind to hidden | **Can add, never remove** — justify machinery for visible conditions |

**Rule of thumb**: 
- Spec-declared distinctions (e.g., "distinguished from near-misses") → unconditional
- Spec-conditional behaviors (e.g., "fallback when preferred relation absent") → evidence-gated
- Probes justify adding (P2→UNION) but never justify removing (near-miss guard)

## Family Invariants

- **Output Schema**: Query must return exactly two variables: `?professorName` and `?universityName`
- **Result Cardinality**: Exactly one row per qualifying professor-university pair (enforced by SELECT DISTINCT)
- **Target Entities**: Persons whose academic rank qualifies per task definition; encoding must be a *generalizing rule* (pattern or class), never enumeration of observed strings
- **Near-Miss Exclusion**: Spec declares "professor-like near misses" are non-target and must be "distinguished from" qualifying roles — implement unconditionally
- **Data Location**: Input TTL file at `/app/university_graph.ttl`
- **Output Location**: SPARQL query saved to `/app/solution.sparql`

## Analysis Procedure

### Step 1: Schema Discovery

```python
from rdflib import Graph, Namespace, RDF

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
uni = Namespace("http://university.org/ontology#")

# Find all person properties and their values
for s, p, o in g:
    if (s, RDF.type, uni.Person) in g:
        print(f"{s.split('#')[-1]}: {p.split('#')[-1]} = {o}")
```

### Step 2: Identify Professor Identification Pattern

**Discovery query** (enumerate to learn the rule):
```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?role
WHERE { ?person a uni:Person ; uni:role ?role }
ORDER BY ?role
```

**Classification** (per spec: qualifying includes "Professor", "Assistant Professor", "Prof.", etc.; non-target includes "Lecturer", "Student", "Staff", and near-misses "Visiting Professor", "Professor Emeritus", etc.):
- Qualifying: Roles containing "professor" or "prof." (case-insensitive), excluding near-misses
- Non-target: "Lecturer", "Student", "Staff", and spec-declared near-misses

**Probe P1**: Check for resource-based rank variant:
```sparql
# If count > 0, use hasAcademicRank branch instead of role string
SELECT (COUNT(*) AS ?n) 
WHERE { ?p a uni:Person ; uni:hasAcademicRank ?r }
```

### Step 3: Identify Affiliation Path

**Discovery query**:
```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?prop ?middleProp (COUNT(*) AS ?n)
WHERE { 
  ?person a uni:Person ; ?prop ?middle .
  ?middle ?middleProp ?university .
  ?university a uni:University .
}
GROUP BY ?prop ?middleProp
```

**Probe P2**: Check if fallback path is needed:
```sparql
# If any results, UNION/COALESCE fallback is warranted
SELECT ?p ?name WHERE {
  ?p a uni:Person ; uni:hasName ?name ; uni:role ?role .
  FILTER(REGEX(STR(?role), "professor|prof\\.", "i"))
  FILTER NOT EXISTS { ?p uni:worksAt ?o }
}
```

### Step 4: Check for Multi-Valued Properties

**Probe P3**: Multi-valued names need reducers:
```sparql
# If any results, use FILTER(LANG(...)) or SAMPLE
SELECT ?s (COUNT(?n) AS ?c) 
WHERE { ?s uni:hasName ?n } 
GROUP BY ?s 
HAVING(?c > 1)
```

### Step 5: Construct the Query

**Default pattern** (implements spec-declared distinction unconditionally):
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
             uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?department .
  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  
  # Pattern-based with spec-declared near-miss exclusions (unconditional)
  FILTER(REGEX(STR(?role), "professor|prof\\.", "i") &&
         !REGEX(STR(?role), "emeritus|emerita|visiting|honorary|honoris|adjunct", "i"))
}
```

**Caveat**: If task instruction explicitly broadens ranks (e.g., "include adjuncts"), remove that term from exclusion. The guard implements spec's "non-target" framing; explicit task text overrides.

## Variation Axes & Adaptation Strategies

### Axis 1: Professor Identification Semantics

**Default pattern** (spec-declared, unconditional):
```sparql
FILTER(REGEX(STR(?role), "professor|prof\\.", "i") &&
       !REGEX(STR(?role), "emeritus|emerita|visiting|honorary|honoris|adjunct", "i"))
```

**Evidence-grown exclusions**: Extend alternation if visible data shows novel near-misses not in default list.

**Override** (only when task instruction explicitly includes): Remove excluded term from regex.

**Resource-based variant** (triggered by P1 > 0):
```sparql
?professor uni:hasAcademicRank ?rank .
?rank uni:rankLabel ?rankLabel .
FILTER(REGEX(STR(?rankLabel), "professor|prof\\.", "i"))
# OR filter by rank IRI: FILTER(?rank IN (uni:FullProfessor, uni:AssistantProfessor))
```

### Axis 2: Affiliation Structure to University

**Primary path** (always include if worksAt present):
```sparql
?professor uni:worksAt ?department .
?department uni:partOfUniversity ?university .
```

**Fallback paths** (evidence-gated via P2 — spec says "when preferred relation absent"):

```sparql
# UNION: evidence shows professors without worksAt
{
  ?professor uni:worksAt ?org .
  ?org uni:partOfUniversity ?university .
} UNION {
  ?professor uni:teaches ?course .
  ?course uni:isTaughtIn ?org .
  ?org uni:partOfUniversity ?university .
}

# COALESCE: strict preference (use if spec indicates preference)
OPTIONAL { 
  ?professor uni:worksAt ?o1 . 
  ?o1 uni:partOfUniversity ?u1 .
}
OPTIONAL { 
  ?professor uni:teaches ?c . 
  ?c uni:isTaughtIn ?o2 . 
  ?o2 uni:partOfUniversity ?u2 .
}
BIND(COALESCE(?u1, ?u2) AS ?university)

# Property paths: for compact alternatives
?professor (uni:worksAt|uni:teaches/uni:isTaughtIn)/uni:partOfUniversity ?university .
```

**Inverse containment**:
```sparql
?department ^uni:hasDepartment ?university .
```

**Extended chains**:
```sparql
?professor uni:worksAt/(uni:partOfUniversity+) ?university .
```

### Axis 3: Graph Noise and Result Cardinality

**Invariant-safe** (always apply):
```sparql
SELECT DISTINCT ?professorName ?universityName
```

**Per-IRI deduplication** (if names might collide, though spec declares name-level):
```sparql
SELECT ?professorName ?universityName
WHERE {
  {
    SELECT DISTINCT ?professor ?university
    WHERE { ... }
  }
  ?professor uni:hasName ?professorName .
  ?university uni:hasName ?universityName .
}
```

**Multi-valued name handling** (evidence-gated via P3):
```sparql
# Option 1: Filter by language
FILTER(LANG(?universityName) = "" || LANG(?universityName) = "en")

# Option 2: Aggregate
SELECT ?professor (SAMPLE(?universityName) AS ?univName)
```

## Reference Implementation (Default)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
             uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?department .
  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  
  FILTER(REGEX(STR(?role), "professor|prof\\.", "i") &&
         !REGEX(STR(?role), "emeritus|emerita|visiting|honorary|honoris|adjunct", "i"))
}
```

## Adversarial Test Fixture

Create `test_fixture.ttl` to verify pattern handles spec-declared behaviors:

```turtle
@prefix uni: <http://university.org/ontology#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# Infrastructure
uni:TestU a uni:University ; uni:hasName "Test University" .
uni:TestD a uni:Department ; uni:partOfUniversity uni:TestU .

# Qualifying (should be included)
uni:P1 a uni:Person ; uni:hasName "Full Professor"   ; uni:role "Professor of Physics"       ; uni:worksAt uni:TestD .
uni:P2 a uni:Person ; uni:hasName "Abbrev Professor" ; uni:role "Prof. of Chemistry"         ; uni:worksAt uni:TestD .
uni:P3 a uni:Person ; uni:hasName "Lower Professor"; uni:role "professor of biology"       ; uni:worksAt uni:TestD .
uni:P4 a uni:Person ; uni:hasName "Asst Professor" ; uni:role "Assistant Professor of CS"  ; uni:worksAt uni:TestD .

# Near-misses (should be excluded per spec)
uni:P5 a uni:Person ; uni:hasName "Visiting Prof"    ; uni:role "Visiting Professor of Math" ; uni:worksAt uni:TestD .
uni:P6 a uni:Person ; uni:hasName "Emeritus Prof"    ; uni:role "Professor Emeritus"         ; uni:worksAt uni:TestD .
uni:P7 a uni:Person ; uni:hasName "Honorary Prof"    ; uni:role "Honorary Professor"         ; uni:worksAt uni:TestD .
uni:P8 a uni:Person ; uni:hasName "Adjunct Prof"     ; uni:role "Adjunct Professor"          ; uni:worksAt uni:TestD .

# Non-target (should be excluded)
uni:P9 a uni:Person ; uni:hasName "Lecturer"         ; uni:role "Lecturer"                   ; uni:worksAt uni:TestD .
uni:P10 a uni:Person ; uni:hasName "Student"         ; uni:role "Student" .

# Edge case: contains "Professor" but not qualifying
uni:P11 a uni:Person ; uni:hasName "Assistant"       ; uni:role "Assistant to the Professor"; uni:worksAt uni:TestD .
```

**Expected results**: P1, P2, P3, P4 in; P5–P11 out.

**Validation**:
```bash
python3 << 'EOF'
from rdflib import Graph

g = Graph()
g.parse("test_fixture.ttl", format="turtle")

with open("/app/solution.sparql", "r") as f:
    query = f.read()

results = list(g.query(query))
found = {str(r.professorName) for r in results}

expected = {"Full Professor", "Abbrev Professor", "Lower Professor", "Asst Professor"}
excluded = {"Visiting Prof", "Emeritus Prof", "Honorary Prof", "Adjunct Prof", "Lecturer", "Assistant"}

print(f"Found: {found}")
print(f"\nExpected present: {expected.issubset(found)}")
print(f"Excluded absent: {excluded.isdisjoint(found)}")

if expected.issubset(found) and excluded.isdisjoint(found):
    print("\n✓ Pattern correctly implements spec classification")
else:
    print(f"\n✗ Failures — included: {excluded & found}, missing: {expected - found}")
EOF
```

## Testing Procedure

### Critical Rule: Test Exact Bytes of solution.sparql

```python
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# ALWAYS read the file — never retype inline
with open("/app/solution.sparql", "rb") as f:  # binary to preserve exact bytes
    query_bytes = f.read()
    query = query_bytes.decode('utf-8')

results = list(g.query(query))
```

### Validate Output Schema

```python
assert len(results) == 0 or (hasattr(results[0], 'professorName') and 
                             hasattr(results[0], 'universityName')), \
    "Missing required output variables: ?professorName and ?universityName"
```

### Validate Cardinality Invariant

```python
pairs = [(str(r.professorName), str(r.universityName)) for r in results]
unique_pairs = set(pairs)
assert len(pairs) == len(unique_pairs), \
    f"Duplicate rows: {len(pairs)} results, {len(unique_pairs)} unique pairs"
```

### Complete Validation Script

```python
from rdflib import Graph, Namespace

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
uni = Namespace("http://university.org/ontology#")

# Read exact bytes from file
with open("/app/solution.sparql", "r") as f:
    query = f.read()

results = list(g.query(query))

# Check 1: Output variables
assert len(results) == 0 or (hasattr(results[0], 'professorName') and 
                             hasattr(results[0], 'universityName')), \
    "Missing output variables"

# Check 2: Cardinality invariant
pairs = [(str(r.professorName), str(r.universityName)) for r in results]
assert len(pairs) == len(set(pairs)), \
    f"Duplicates: {len(pairs)} rows, {len(set(pairs))} unique"

print(f"✓ Valid: {len(results)} unique professor-university pairs")
for name, univ in sorted(pairs):
    print(f"  - {name} @ {univ}")

# Check 3: Verify pattern excludes near-misses
roles = set()
for r in g.query("""
  SELECT DISTINCT ?role WHERE {
    ?p a uni:Person ; uni:role ?role ; uni:hasName ?n .
    FILTER(REGEX(STR(?role), "professor|prof\\.", "i"))
  }
"""):
    role_str = str(r.role).lower()
    if any(x in role_str for x in ['emeritus', 'visiting', 'honorary', 'adjunct']):
        print(f"WARNING: Near-miss in visible data: {r.role}")
    roles.add(r.role)
print(f"\nMatched {len(roles)} distinct qualifying roles")
```

## Evaluator Mechanics (Inferred)

- Query text is read and executed with rdflib against hidden test TTL
- Results compared as `set((str(professorName), str(universityName)))` tuples
- Exact literal fidelity required — never transform output (no UCASE/STR on projection)
- STR belongs only inside FILTER expressions
- Set comparison means duplicates are invisible to this test, but keep DISTINCT for family invariant

## Common Pitfalls

1. **Encoding instances instead of rules**: Hardcoding VALUES with observed role strings fails on variants with different data. Use pattern-based FILTER.

2. **Missing DISTINCT**: Without SELECT DISTINCT, professors with multiple roles or departments produce duplicate rows.

3. **Case sensitivity**: `CONTAINS(?role, "Professor")` is case-sensitive. Use `REGEX(..., "i")`.

4. **Over-escaping in shell**: `\\b` or `\\.` in heredocs may over-escape through Python→SPARQL→regex layers. Test exact bytes of /app/solution.sparql, never retyped copies.

5. **rdflib variable name shadowing**: Avoid variable name `count` — `ResultRow.count` is a method. Use `?n` or `?c` instead, or access positionally (`row[2]`).

6. **Path incompleteness**: Ensure all chain segments are traversed (e.g., worksAt → partOfUniversity).

7. **Abbreviation mismatch**: Pattern "professor" won't match "Prof." — include both: `professor|prof\.`

8. **Speculative removal of guards**: Never remove the near-miss guard based on "no near-misses in visible data" — hidden data can contain them. The spec declares them non-target unconditionally.

9. **Multi-valued properties**: A person with multiple worksAt relations produces multiple rows without DISTINCT.

10. **Language-tagged literals**: `"University"@en` and `"University"@fr` are different values. Use FILTER(LANG(...)) or SAMPLE if P3 shows multi-valued names.

## Execution Command

```bash
python3 << 'PYEOF'
from rdflib import Graph, Namespace

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
uni = Namespace("http://university.org/ontology#")

with open("/app/solution.sparql", "r") as f:
    query = f.read()

results = list(g.query(query))
pairs = [(str(r.professorName), str(r.universityName)) for r in results]

if len(pairs) != len(set(pairs)):
    print(f"ERROR: {len(pairs)} rows but {len(set(pairs))} unique pairs")
else:
    print(f"OK: {len(results)} unique pairs")
    for name, univ in sorted(pairs):
        print(f"  {name} | {univ}")
PYEOF
```

## Quick Reference: Pattern Defaults

| Scenario | Pattern | When |
|----------|---------|------|
| **Default** (spec-compliant) | `FILTER(REGEX(STR(?role), "professor\|prof\\.", "i") && !REGEX(... "emeritus\|visiting\|..."))` | **Always start here** |
| Instruction override | Remove excluded term | Only when task explicitly includes that rank |
| Evidence-grown | Extend exclusion list | When visible data shows novel near-miss |
