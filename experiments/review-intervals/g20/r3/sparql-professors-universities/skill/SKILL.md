---
name: sparql-professors-universities
description: >
  Develop a SPARQL query that retrieves professor names and their affiliated
  university names from a Turtle knowledge graph. The skill provides a
  discovery-driven decision procedure: first explore the graph to answer two
  branching questions (how professors are identified, how persons link to
  universities), then construct the query from the answers. Covers string-valued
  roles, resource-based academic ranks, type-based classification, direct and
  multi-hop affiliation paths, fallback paths, noise handling, and
  deduplication.
---

# SPARQL Professors–Universities Query Skill

## Task Invariant

Every member of this family asks you to:

1. Read a Turtle file (typically `/app/university_graph.ttl`) containing both
   ontology axioms and instance data about a university knowledge graph.
2. Write a SPARQL SELECT query that returns **two variables**:
   `?professorName` and `?universityName`.
3. Each result row = one qualifying professor + the university they work at.
4. Save the query to `/app/solution.sparql`.

## Core Principle: Discovery Before Construction

**Do not write any SPARQL until you have completed Steps 1–2 and filled in the
Decision Report below.** The query structure depends entirely on what the graph
contains. Copying a template without exploration will fail on any variant.

The workflow is strictly ordered:

```
Step 1: Explore → run the exploration script
Step 2: Decide  → fill in the Decision Report
Step 3: Build   → assemble query from the report
Step 4: Verify  → test against the graph
```

---

## Step 1 — Explore the Graph

Run the following exploration script against the Turtle file. **Do not skip
any section. Do not substitute a simplified version.** The script produces
the structured answers needed for Step 2.

```python
from rdflib import Graph, URIRef, Literal, RDF

def local_name(uri_str):
    if '#' in uri_str:
        return uri_str.split('#')[-1]
    elif '/' in uri_str:
        return uri_str.rstrip('/').split('/')[-1]
    return uri_str

g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")

# ── 1a. Predicate and class inventory ──
all_predicates = sorted(set(local_name(str(p)) for s, p, o in g))
all_types = sorted(set(local_name(str(o)) for s, p, o in g if str(p) == str(RDF.type)))
print("Predicates:", all_predicates)
print("Types:", all_types)

# ── 1b. Role/rank predicate discovery ──
role_predicates = [p for p in all_predicates if any(kw in p.lower() for kw in ["role", "rank"])]
print("\n=== PROFESSOR IDENTIFICATION ===")
print("Role/rank predicates:", role_predicates)

if role_predicates:
    for rp_local in role_predicates:
        rp_uri = None
        for s, p, o in g:
            if local_name(str(p)) == rp_local:
                rp_uri = p
                break
        if rp_uri:
            objects = set()
            for s, p, o in g.triples((None, rp_uri, None)):
                obj_type = "Literal" if isinstance(o, Literal) else "Resource"
                objects.add((str(o), obj_type))
            print(f"  {rp_local}:")
            for obj, typ in sorted(objects)[:15]:
                print(f"    → {typ}: {obj}")
            
            # ── VALIDATION: Check professor identification pattern ──
            if any("Literal" in str(o) for o in objects):
                prof_values = [str(o).split("'")[1] for o in objects if "Professor" in str(o) and "Literal" in str(o)]
                non_prof_values = [str(o).split("'")[1] for o in objects if "Professor" not in str(o) and "Literal" in str(o)]
                print(f"\n  Values containing 'Professor': {prof_values}")
                print(f"  Values NOT containing 'Professor': {non_prof_values}")
                print(f"  → Check task instructions: should all 'Professor' values be included?")
                print(f"  → Are there near-miss values (e.g., 'Emeritus', 'Visiting') that need exclusion?")
else:
    print("\n  No role/rank predicates found.")
    print("  → Check if professors are identified by rdf:type (e.g., uni:Professor)")
    prof_types = [t for t in all_types if "professor" in t.lower()]
    if prof_types:
        print(f"  → Found professor type(s): {prof_types}")
        print(f"  → Use Pattern C (Type-based): ?person a uni:Professor .")
    else:
        print(f"  → No professor type found. Check task instructions for identification mechanism.")

# ── 1c. Person instances and affiliation structure ──
person_instances = set()
for s, p, o in g.triples((None, RDF.type, None)):
    if "person" in local_name(str(o)).lower():
        person_instances.add(s)

print(f"\n=== AFFILIATION STRUCTURE ===")
print(f"Person instances: {len(person_instances)}")

# Sample a person to discover affiliation predicates
if person_instances:
    sample = list(person_instances)[0]
    print(f"Sample person: {local_name(str(sample))}")

    obj_props = {}
    for s, p, o in g.triples((sample, None, None)):
        if not isinstance(o, Literal) and str(p) != str(RDF.type):
            target_types = [local_name(str(t)) for st, sp, t in g.triples((o, RDF.type, None))]
            obj_props[local_name(str(p))] = (str(o), target_types)

    print("Object properties:")
    for pred, (target, types) in sorted(obj_props.items()):
        print(f"  {pred} → {local_name(target)} (types: {types})")

    # Identify primary affiliation predicate (prioritize org-pointing)
    org_types = {"department", "university", "organization", "institution", "school", "faculty"}
    candidates = []
    for pred, (target, types) in obj_props.items():
        is_org = any(any(ot in t.lower() for ot in org_types) for t in types)
        is_uni = any("university" == t.lower() for t in types)
        candidates.append((pred, is_uni, is_org))
    candidates.sort(key=lambda x: (not x[1], not x[2], x[0]))

    if candidates:
        primary_pred = candidates[0][0]
        direct_to_uni = candidates[0][1]
        print(f"\nPrimary affiliation predicate: {primary_pred}")
        print(f"Direct to University? {direct_to_uni}")

        # ── MANDATORY: Population-wide coverage check ──
        pred_uri = None
        for s, p, o in g:
            if local_name(str(p)) == primary_pred:
                pred_uri = p
                break

        if pred_uri:
            persons_with = set()
            for s, p, o in g.triples((None, pred_uri, None)):
                if s in person_instances:
                    persons_with.add(s)

            persons_without = person_instances - persons_with
            coverage = len(persons_with) / len(person_instances) if person_instances else 1.0

            print(f"\n--- MANDATORY COVERAGE CHECK ---")
            print(f"Predicate: {primary_pred}")
            print(f"Coverage: {coverage:.0%} ({len(persons_with)}/{len(person_instances)} persons)")

            if persons_without:
                print(f"⚠ {len(persons_without)} persons LACK {primary_pred}:")
                for missing in sorted(persons_without, key=str)[:5]:
                    # Check if this person is a professor
                    is_prof = False
                    role_val = None
                    name_val = None
                    for s, p, o in g.triples((missing, None, None)):
                        ln = local_name(str(p))
                        if ln in role_predicates and isinstance(o, Literal):
                            role_val = str(o)
                            if "professor" in str(o).lower():
                                is_prof = True
                        if ln == "hasname" or ln == "name" or ln == "label":
                            name_val = str(o)
                    prof_status = "PROFESSOR" if is_prof else "non-professor"
                    print(f"  - {name_val or local_name(str(missing))} ({prof_status}, role={role_val})")
                    # Show alternative predicates
                    alt = {}
                    for s, p, o in g.triples((missing, None, None)):
                        if not isinstance(o, Literal) and str(p) != str(RDF.type):
                            tt = [local_name(str(t)) for st, sp, t in g.triples((o, RDF.type, None))]
                            alt[local_name(str(p))] = tt
                    if alt:
                        print(f"    Alternative predicates: {alt}")
            else:
                print("✓ All persons have this predicate")

        # ── Two-hop path discovery ──
        if not direct_to_uni:
            for pred, (target, types) in obj_props.items():
                if any("department" in t.lower() or "organization" in t.lower() for t in types):
                    intermediate_uri = URIRef(target)
                    print(f"\nTwo-hop path via {pred}:")
                    for ds, dp, do in g.triples((intermediate_uri, None, None)):
                        if not isinstance(do, Literal):
                            tt = [local_name(str(t)) for dst, dstp, t in g.triples((do, RDF.type, None))]
                            if tt:
                                print(f"  {local_name(str(dp))} → {local_name(str(do))} (types: {tt})")

# ── 1d. University name predicate ──
uni_instances = set()
for s, p, o in g.triples((None, RDF.type, None)):
    if "university" in local_name(str(o)).lower() or "institution" in local_name(str(o)).lower():
        uni_instances.add(s)

print(f"\n=== UNIVERSITY NAME ===")
if uni_instances:
    sample_uni = list(uni_instances)[0]
    print(f"Sample university: {local_name(str(sample_uni))}")
    for s, p, o in g.triples((sample_uni, None, None)):
        if isinstance(o, Literal):
            print(f"  {local_name(str(p))} → {o}")
```

---

## Step 2 — Decision Report (MANDATORY)

After running the exploration script, you **must** fill in this report.
**Do not proceed to Step 3 until every field is completed.**

```
═══════════════════════════════════════════════════
DECISION REPORT
═══════════════════════════════════════════════════

1. ONTOLOGY NAMESPACE: _______________
   (from @prefix in the Turtle file)

2. PROFESSOR IDENTIFICATION:
   Predicate: _______________
   Object type: [ ] String literal  [ ] URI resource  [ ] rdf:type class
   Filter: [ ] CONTAINS "Professor"  [ ] Exact values  [ ] Type-based  [ ] Other: ___
   Exclusion needed? [ ] No  [ ] Yes → exclude: _______________
   Task instruction check: [ ] All "Professor" values included
                            [ ] Some excluded per instructions: _______________

3. PERSON CLASS: _______________
   Person name predicate: _______________

4. AFFILIATION PATH:
   Primary predicate: _______________
   Direct to University? [ ] Yes  [ ] No (needs intermediate hops)

5. COVERAGE CHECK (MANDATORY):
   Primary predicate coverage: ___% (___/___ persons)
   Missing persons are: [ ] All non-professors  [ ] Include professors
   → Decision: [ ] Single path sufficient  [ ] UNION with fallback needed

6. AFFILIATION CHAIN (if not direct):
   Hop 1: ?person _______ ?intermediate .
   Hop 2: ?intermediate _______ ?uni .
   (Add more hops if needed)

7. UNIVERSITY NAME PREDICATE: _______________

8. FALLBACK PATH (if coverage < 100% for professors):
   ?person _______ ?course .
   ?course _______ ?intermediate .
   ?intermediate _______ ?uni .

═══════════════════════════════════════════════════
```

### Decision Rules

**Decision 1 — Professor Identification Pattern:**

| Condition | Pattern | SPARQL fragment |
|-----------|---------|-----------------|
| Role predicate with string literals containing "Professor" | **A: String filter** | `?person PRED ?role . FILTER(CONTAINS(?role, "Professor"))` |
| Rank predicate with URI resources + label property | **B: Resource + label** | `?person PRED ?rank . ?rank LABEL_PRED ?label . FILTER(CONTAINS(?label, "Professor"))` |
| Rank predicate with enumerable URI resources | **B2: Enumeration** | `?person PRED ?rank . VALUES ?rank { URI1 URI2 ... }` |
| rdf:type includes a Professor class | **C: Type-based** | `?person a uni:Professor .` |

**Decision 2 — Affiliation Path Pattern:**

| Condition | Pattern |
|-----------|---------|
| Coverage = 100% for professors, two-hop via department | **A: Two-hop** |
| Direct Person → University link | **B: Direct** |
| Via appointment resource | **C: Appointment** |
| Coverage < 100% for professors | **D: UNION** (primary + fallback) |
| Longer chain | **E: Extended** |

**Critical rule for Decision 2:** If the coverage check shows that some persons
lack the primary affiliation predicate, you must check whether any of those
persons are professors (have the professor signal from Decision 1). If yes,
you **must** use Path D (UNION). If all missing persons are non-professors,
a single path is sufficient because the professor filter will exclude them.

---

## Step 3 — Build the Query

Only after the Decision Report is complete, assemble the query:

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a PERSON_CLASS ;
          PERSON_NAME_PRED ?professorName .

  # PROFESSOR_ID_PATTERN (from Decision Report field 2)

  # AFFILIATION_PATH (from Decision Report fields 4-8)

  ?uni UNI_NAME_PRED ?universityName .
}
```

Substitute all placeholders from the Decision Report. Use `SELECT DISTINCT`
unless you are certain no duplicates are possible.

---

## Step 4 — Verify

```python
from rdflib import Graph
g = Graph()
g.parse("/app/university_graph.ttl", format="turtle")
query = open("/app/solution.sparql").read()
results = g.query(query)

print(f"Results: {len(results)} rows")
print(f"Variables: {[str(v) for v in results.vars]}")
for row in results:
    print(f"  {row[0]} → {row[1]}")
```

### Verification checklist

- [ ] Query parses without syntax errors
- [ ] Variables are exactly `?professorName` and `?universityName`
- [ ] All qualifying professors appear in results
- [ ] No non-professors (lecturers, students, staff) appear in results
- [ ] No duplicate rows
- [ ] University names match the name predicate values
- [ ] Query saved to `/app/solution.sparql`

---

## Common Pitfalls

1. **Skipping the exploration script**: The #1 failure mode. Always run the
   full script from Step 1.
2. **Skipping the coverage check**: If you don't check whether all professors
   have the primary affiliation predicate, you may silently miss professors
   in variants with heterogeneous paths.
3. **Over-narrow professor matching**: `?role = "Professor"` misses
   "Assistant Professor". Use CONTAINS.
4. **Under-broad professor matching**: CONTAINS("Professor") might match
   "Professor Emeritus" when that should be excluded. Check task instructions.
5. **Hard-coding paths**: The chain from Person to University varies.
6. **Forgetting DISTINCT**: Multi-valued properties cause duplicates.
7. **Wrong variable names**: Must be exactly `?professorName` and `?universityName`.
