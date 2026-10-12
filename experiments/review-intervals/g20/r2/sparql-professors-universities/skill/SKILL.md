---
name: sparql-professors-universities
description: >
  Construct SPARQL queries to retrieve professor names and their affiliated
  university names from a Turtle knowledge graph. Handles multiple ontology
  patterns for professor identification (string roles vs. ranked resources),
  varied affiliation structures (direct links, department chains, appointment
  intermediaries, fallback paths), and graph noise (non-professor roles,
  duplicate bindings). The method emphasizes data-driven ontology discovery
  before query construction.
---

# SPARQL Professors-Universities Query Skill

## Overview

This skill produces a SPARQL query that returns `?professorName` and `?universityName` for every qualifying professor in a Turtle knowledge graph. The task family varies along three axes: how professors are identified, how affiliation to universities is structured, and how much noise/duplication surrounds the answer.

## Core Methodology: Analyze-then-Query

**Never assume the ontology.** Always inspect the Turtle file first to discover:
1. What predicates identify professors
2. What path connects a person to their university
3. What predicates carry names

### Diagnostic Decision Tree

After inspecting the Turtle file, use this decision procedure to determine which patterns apply:

**Decision 1: How is academic rank represented?**
- **If** Person instances have a predicate with string literal objects like "Professor of X" or "Assistant Professor of X" → **Pattern A** (string-valued role)
- **If** Person instances have a predicate pointing to URI resources (e.g., `uni:FullProfessor`), and those resources have label predicates → **Pattern B** (resource-valued rank)
- **Diagnostic test**: Check the object types of predicates on Person instances. If `isinstance(o, Literal)` → Pattern A. If `isinstance(o, URIRef)` → Pattern B.

**Decision 2: What is the affiliation path structure?**
- **If** Person has a predicate directly pointing to a University-typed resource → **Path B** (direct affiliation)
- **If** Person has a predicate pointing to a Department-typed resource, which has a predicate pointing to University → **Path A** (two-hop via department)
- **If** Person has a predicate pointing to an Appointment resource, which points to Organization, which points to University → **Path C** (three-hop via appointment)
- **Diagnostic test**: Follow the object chain from Person. Count hops to reach a University-typed resource.

**Decision 3: Is a fallback path needed?**
- **If** the task description says "assume each professor works at exactly one university" or all professors have the primary affiliation predicate → **No fallback needed** (use primary path only)
- **If** some professors lack the primary affiliation predicate but have teaching relationships → **Add fallback** (UNION with `FILTER NOT EXISTS`)
- **Diagnostic test**: Check if all qualifying professors have the primary affiliation predicate. If any are missing it, check if they have alternative paths (e.g., `uni:teaches` → `uni:Course` → `uni:isTaughtIn` → Department).

**Decision 4: What predicates carry names?**
- **For persons**: Look for `uni:hasName`, `uni:name`, `foaf:name`, or `rdfs:label` on Person instances
- **For universities**: Look for `uni:hasName`, `uni:name`, or `rdfs:label` on University instances
- **Diagnostic test**: Enumerate all predicates on Person and University instances that have string literal objects.

### Step 1: Discover the Ontology Structure

**Run this complete discovery script** to extract all ontology information in one pass:

```python
from rdflib import Graph, RDF, Namespace, URIRef, Literal
import re

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# Extract namespace prefix from TTL file
with open("/app/university_graph.ttl") as f:
    content = f.read()
    match = re.search(r'@prefix\s+(\w+):\s+<([^>]+)>', content)
    if match:
        prefix_name, namespace_uri = match.groups()
        NS = Namespace(namespace_uri)
        print(f"Namespace: {prefix_name}: <{namespace_uri}>")

# Discover all types and their predicates
print("\n=== Types and Predicates ===")
type_info = {}
for type_uri in set(g.objects(None, RDF.type)):
    instances = list(g.subjects(RDF.type, type_uri))
    if not instances:
        continue
    all_preds = set()
    sample_literals = {}
    sample_resources = {}
    for s in instances[:3]:  # Sample first 3 instances
        for p, o in g.predicate_objects(s):
            all_preds.add(p)
            if isinstance(o, Literal):
                sample_literals.setdefault(p, []).append(str(o))
            elif isinstance(o, URIRef):
                sample_resources.setdefault(p, []).append(str(o))
    type_info[type_uri] = {
        'count': len(instances),
        'predicates': all_preds,
        'literal_samples': sample_literals,
        'resource_samples': sample_resources
    }
    print(f"\n{type_uri}: {len(instances)} instances")
    print(f"  Predicates: {sorted([str(p).split('#')[-1] for p in all_preds])}")
    for pred, vals in list(sample_literals.items())[:2]:
        print(f"  {str(pred).split('#')[-1]} (literal): {vals[:2]}")
    for pred, vals in list(sample_resources.items())[:2]:
        print(f"  {str(pred).split('#')[-1]} (resource): {vals[:2]}")

# Identify Person-like types (check local name only, not full URI)
print("\n=== Person-like Types ===")
def local_name(uri):
    s = str(uri)
    return s.split('#')[-1] if '#' in s else s.split('/')[-1]

person_types = [t for t in type_info.keys() 
                if 'person' in local_name(t).lower() or 'faculty' in local_name(t).lower() or 'professor' in local_name(t).lower()]
for pt in person_types:
    print(f"{pt}: {type_info[pt]['count']} instances")

# Identify University-like types (check local name only, not full URI)
print("\n=== University-like Types ===")
uni_types = [t for t in type_info.keys() 
             if 'university' in local_name(t).lower() or 'organization' in local_name(t).lower()]
for ut in uni_types:
    print(f"{ut}: {type_info[ut]['count']} instances")

# For Person types, identify role/rank pattern
print("\n=== Role/Rank Pattern Detection ===")
for pt in person_types:
    info = type_info[pt]
    for pred in info['predicates']:
        pred_name = str(pred).split('#')[-1].lower()
        if 'role' in pred_name or 'rank' in pred_name or 'position' in pred_name or 'title' in pred_name:
            if pred in info['literal_samples']:
                print(f"{pt} -> {pred} (Pattern A: string-valued)")
                print(f"  Samples: {info['literal_samples'][pred][:3]}")
            elif pred in info['resource_samples']:
                print(f"{pt} -> {pred} (Pattern B: resource-valued)")
                print(f"  Samples: {info['resource_samples'][pred][:3]}")

# Trace affiliation paths from Person to University
print("\n=== Affiliation Path Discovery ===")
for pt in person_types:
    info = type_info[pt]
    for pred in info['predicates']:
        if pred in info['resource_samples']:
            # Check if this predicate points to a University type
            for res_uri in info['resource_samples'][pred][:1]:
                res_uri_obj = URIRef(res_uri)
                res_type = list(g.objects(res_uri_obj, RDF.type))
                if res_type:
                    res_type_name = str(res_type[0]).split('#')[-1]
                    if 'university' in res_type_name.lower():
                        print(f"{pt} -> {str(pred).split('#')[-1]} -> {res_type_name} (Direct affiliation)")
                    elif 'department' in res_type_name.lower() or 'organization' in res_type_name.lower():
                        # Check if this intermediate type points to University
                        for p2 in g.predicates(res_uri_obj, None):
                            for o2 in g.objects(res_uri_obj, p2):
                                if isinstance(o2, URIRef):
                                    o2_type = list(g.objects(o2, RDF.type))
                                    if o2_type and 'university' in str(o2_type[0]).lower():
                                        print(f"{pt} -> {str(pred).split('#')[-1]} -> {res_type_name} -> {str(p2).split('#')[-1]} -> University (Two-hop)")

# Identify name predicates
print("\n=== Name Predicates ===")
for pt in person_types:
    info = type_info[pt]
    for pred in info['predicates']:
        pred_name = str(pred).split('#')[-1].lower()
        if 'name' in pred_name or 'label' in pred_name:
            if pred in info['literal_samples']:
                print(f"{pt} -> {str(pred).split('#')[-1]} (person name)")
                print(f"  Sample: {info['literal_samples'][pred][0]}")

for ut in uni_types:
    info = type_info[ut]
    for pred in info['predicates']:
        pred_name = str(pred).split('#')[-1].lower()
        if 'name' in pred_name or 'label' in pred_name:
            if pred in info['literal_samples']:
                print(f"{ut} -> {str(pred).split('#')[-1]} (university name)")
                print(f"  Sample: {info['literal_samples'][pred][0]}")
```

This script outputs a structured summary of:
- The namespace prefix and URI
- All types and their predicates
- Person-like and University-like types
- Role/rank pattern (Pattern A or B)
- Affiliation path structure (direct, two-hop, etc.)
- Name predicates for persons and universities

Use this output to make the diagnostic decisions and construct the query.

### Step 2: Identify Professor Qualification Pattern

There are two main patterns for representing academic rank:

#### Pattern A: String-valued role predicate
```turtle
:person1 uni:role "Professor of Computer Science" .
:person2 uni:role "Assistant Professor of Mathematics" .
```
**Detection**: Find predicates whose objects on Person instances are string literals containing rank-like words.

**Filter strategy**: Use `CONTAINS` or `REGEX` to match "Professor" (case-insensitive):
```sparql
FILTER(CONTAINS(LCASE(?role), "professor"))
```

**What qualifies**: Any string containing "Professor" — this covers "Professor", "Assistant Professor", "Associate Professor", "Full Professor", "Professor Emeritus", etc.

**What to exclude**: Roles like "Lecturer", "Student", "Staff", "Researcher" do NOT contain "Professor" and are naturally excluded.

**Edge cases to watch for**:
- "Prof." abbreviations — use `REGEX(LCASE(?role), "prof(essor|\\.)")` if abbreviations are expected
- Near-miss roles like "Professorship" (contains "Professor" — may need narrowing)
- Roles in non-English languages

#### Pattern B: Resource-valued academic rank
```turtle
:person1 uni:hasAcademicRank uni:FullProfessor .
uni:FullProfessor uni:rankLabel "Professor" .
```
**Detection**: Find predicates on Person instances whose objects are URI resources (not literals), and check if those resources have label predicates.

**Filter strategy**: Follow the rank resource to its label, then filter:
```sparql
?person uni:hasAcademicRank ?rankResource .
?rankResource uni:rankLabel ?rankLabel .
FILTER(CONTAINS(LCASE(?rankLabel), "professor"))
```

**Hybrid detection approach** (recommended):
```python
# Check if role predicates have literal or resource objects
for person in g.subjects(RDF.type, URIRef("...Person")):
    for p in g.predicates(person, None):
        for o in g.objects(person, p):
            if isinstance(o, Literal):
                # Pattern A: string-valued
            elif hasattr(o, 'n3'):  # URIRef
                # Could be Pattern B: resource-valued
```

### Step 3: Trace the Affiliation Path to University

The path from a person to their university can take several forms:

#### Path A: Person → Department → University (two-hop)
```sparql
?person uni:worksAt ?dept .
?dept uni:partOfUniversity ?university .
```
**Detection**: Person has a predicate pointing to a resource typed as Department; Department has a predicate pointing to a resource typed as University.

#### Path B: Person → University (direct)
```sparql
?person uni:affiliatedWith ?university .
```
**Detection**: Person has a predicate directly pointing to a University-typed resource.

#### Path C: Person → Appointment → Organization → University
```sparql
?person uni:hasAppointment ?appt .
?appt uni:atOrganization ?org .
?org uni:partOfUniversity ?university .
```

#### Path D: Fallback — primary path with teaching-course fallback
```sparql
{ ?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?uni . }
UNION
{ FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
  ?person uni:teaches ?course . ?course uni:isTaughtIn ?dept . ?dept uni:partOfUniversity ?uni . }
```
Use this when some professors lack a direct worksAt but teach courses in departments. The `FILTER NOT EXISTS` ensures the fallback only activates for professors with no worksAt triple, preventing false positives from cross-department teaching.

**Path discovery algorithm**:
1. Find the predicate(s) on Person that point to University-typed resources (direct path)
2. If none, find predicates on Person pointing to intermediate resources (Department, Organization)
3. From those intermediates, find predicates pointing to University-typed resources
4. If still no path, check if courses taught by the person lead to departments/universities
5. Use `UNION` to combine multiple valid paths

### Step 4: Discover Name Predicates

University names and person names may use different predicates:
- Common patterns: `uni:hasName`, `uni:name`, `rdfs:label`, `foaf:name`
- Always check what predicates have string literal objects on the relevant types

```python
# For universities
for uni in g.subjects(RDF.type, university_type):
    for p, o in g.predicate_objects(uni):
        if isinstance(o, Literal):
            print(f"  {p} -> {o}")
```

### Step 5: Construct the Query

Assemble the query using the decisions from the diagnostic tree.

**Default (simple) pattern** — use when the task guarantees all professors have the primary affiliation:

```sparql
PREFIX uni: <discovered-namespace>
# (include all needed prefixes)

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName .

  # Professor qualification (from Decision 1)
  # Pattern A: string role
  ?person uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))

  # Pattern B: resource rank (alternative)
  # ?person uni:hasAcademicRank ?rank .
  # ?rank uni:rankLabel ?rankLabel .
  # FILTER(CONTAINS(LCASE(?rankLabel), "professor"))

  # Affiliation path (from Decision 2)
  ?person uni:worksAt ?dept .
  ?dept uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
```

**With fallback** — add only when Decision 3 determines some professors lack the primary path:

```sparql
  # Affiliation path with fallback:
  {
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?university .
  } UNION {
    FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
    ?person uni:teaches ?course .
    ?course uni:isTaughtIn ?dept .
    ?dept uni:partOfUniversity ?university .
  }
  ?university uni:hasName ?universityName .
```

**Key invariants across all variants:**
- Always use `SELECT DISTINCT` to prevent duplicate rows
- Always use `LCASE()` in string filters for case-insensitive matching
- Always discover the actual namespace prefix from the TTL file

### Step 6: Handle Cardinality and Noise

- **Use `DISTINCT`** to prevent duplicate rows when multiple paths exist
- **Verify one row per professor-university pair** — if a professor has multiple qualifying affiliations, the task typically states "assume one university per professor"
- **Exclude non-professors**: The CONTAINS("professor") filter naturally excludes Lecturers, Students, Staff, etc.
- **Watch for noise**: Extra departments, courses, or organizations that don't lead to valid university paths

### Step 7: Validate the Query

Always test the query against the data:

```python
from rdflib import Graph

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
query = open("/app/solution.sparql").read()
results = g.query(query)

print(f"Results: {len(results)}")
for row in results:
    print(f"  {row.professorName} -> {row.universityName}")
```

**Validation checklist**:
- [ ] All expected professors appear
- [ ] No non-professors (Lecturers, Students, Staff) appear
- [ ] Each professor maps to the correct university
- [ ] No duplicate rows (unless the task requires them)
- [ ] Variables are named exactly as specified (`?professorName`, `?universityName`)

## Common Pitfalls

1. **Assuming a fixed ontology**: Always inspect the TTL file first. Predicate names and structures vary.
2. **Case sensitivity**: Use `LCASE()` in filters to handle "professor" vs "Professor".
3. **Missing DISTINCT**: When UNION or multiple paths exist, duplicates are common.
4. **Hardcoding namespace prefixes**: Extract the actual prefix from the TTL file.
5. **Over-filtering**: "Assistant Professor" contains "Professor" — don't accidentally exclude it with overly specific regex.
6. **Under-filtering**: "Professorship Administrator" might contain "Professor" but not be a qualifying role — understand the task's definition.
7. **Wrong name predicate**: University might use `uni:hasName`, `rdfs:label`, or `uni:name` — discover which one.
8. **Naive UNION fallback without NOT EXISTS**: A bare `UNION` of worksAt-path and teaches-path will produce false positives when a professor teaches courses in departments at a *different* university than where they work. Always use `FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }` in the fallback branch so it only activates for professors with no direct affiliation.

## Worked Example (Robust Reference Pattern)

Given a Turtle file with:
- `uni:Person` typed individuals with `uni:role` string values and `uni:hasName`
- `uni:worksAt` linking to `uni:Department` instances (primary affiliation path)
- `uni:teaches` linking to `uni:Course` instances, which `uni:isTaughtIn` departments (fallback path)
- `uni:partOfUniversity` linking departments to `uni:University` instances
- `uni:hasName` on universities for their display name

The robust reference query is:
```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName ;
          uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))

  # Primary path: worksAt → department → university
  # Fallback: only when worksAt is absent
  {
    ?person uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?university .
  } UNION {
    FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }
    ?person uni:teaches ?course .
    ?course uni:isTaughtIn ?dept .
    ?dept uni:partOfUniversity ?university .
  }

  ?university uni:hasName ?universityName .
}
```

**Why this pattern is the reference:**

1. **`DISTINCT`** — Mandatory when UNION or multi-valued predicates (like `uni:teaches` with multiple courses) can produce duplicate bindings. A professor who teaches two courses in the same department would match the fallback branch twice. DISTINCT collapses these to one row per professor-university pair, satisfying the spec's cardinality invariant.

2. **`LCASE(?role)` with lowercase `"professor"`** — Case-insensitive matching ensures the filter works regardless of whether the data stores "Professor", "professor", "PROFESSOR", or mixed case. This costs nothing on v01 but prevents silent failures on variants.

3. **UNION inside WHERE** — The professor identification (`?person a uni:Person`, `uni:hasName`, `uni:role`, FILTER) is shared above the UNION. Only the affiliation path varies. This is the standard SPARQL pattern for fallback paths: the shared pattern binds once, then multiple alternative paths are tried.

4. **`FILTER NOT EXISTS` for true fallback semantics** — The fallback branch must only activate when the professor has NO `uni:worksAt` triple at all. Without this guard, a naive UNION produces false positives: a professor who works at University A but teaches a course in a department at University B would incorrectly appear with both universities. The `FILTER NOT EXISTS { ?person uni:worksAt ?anyDept . }` ensures the teaching path is only used as a last resort for professors with no direct affiliation.

**Simplification when the task guarantees a single path:** If the task explicitly states all professors have `uni:worksAt` and no fallback is needed, you may omit the UNION entirely and use only the primary branch. But always include `DISTINCT` and `LCASE` — they are cheap insurance that costs nothing and prevents common failure modes.

## Adaptation Checklist for New Variants

When encountering a new variant in this family:

1. **Read the TTL file completely** — note all prefixes, types, and predicate patterns
2. **Identify professor pattern**: Is it string roles or resource ranks? What exact strings/labels indicate a professor?
3. **Trace affiliation**: What predicates connect Person → ... → University? How many hops?
4. **Find name predicates**: What predicate carries the university's display name? The person's name?
5. **Check for noise**: Are there multiple departments per university? Multiple affiliations per person?
6. **Write query with DISTINCT** and appropriate filters
7. **Test against the data** and verify all expected results appear
8. **Save to /app/solution.sparql**
