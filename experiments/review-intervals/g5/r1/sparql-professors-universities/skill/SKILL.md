---
name: sparql-professors-universities
description: >
  Construct a SPARQL query that retrieves all professors and the university
  they work at, given a Turtle knowledge graph. Handles variation in how
  professors are identified (role strings vs academic-rank resources), how
  affiliation to a university is structured (direct link, department-mediated
  forward or inverse containment, appointment resources, or course-fallback),
  and how much noise/duplicate data surrounds the answer.
---

# SPARQL Professors–Universities Query

## Task Summary

Given a Turtle file (typically at `/app/university_graph.ttl`) containing an
ontology and instance data for a university knowledge graph, produce a SPARQL
query that returns two variables: `?professorName` and `?universityName`, with
one row per qualifying professor–university pair.

## Family Variation Axes

This skill covers tasks that vary along three dimensions:

1. **Professor identification semantics** — How qualifying professors are
   represented: string-valued `role` predicates, or resource-valued
   `hasAcademicRank` pointing to a node with `rankLabel`. May include spelling
   variants ("Prof.", "Asst. Prof.") and near-miss titles ("Visiting Professor",
   "Professor Emeritus", "Associate Professor") that should be included if they
   contain "Professor".

2. **Affiliation structure to university** — How a person links to a university
   name: direct `worksAt` → university, indirect via department with forward
   containment (`worksAt` → department → `partOfUniversity` → university) or
   inverse containment (university → `containsDepartment` → department), via
   appointment resources (`hasAppointment` → appointment → `atUniversity`), or
   fallback via taught courses (`teaches` → course → `isTaughtIn` → department
   → university).

3. **Graph noise and result cardinality** — Varying amounts of distracting data
   (students, lecturers, staff, multiple departments per university, duplicate
   signals). The invariant is exactly one row per qualifying professor–university
   pair.

## Procedure

### Step 0: Environment Check and Automated Inspection

Before manual inspection, check if automated tools are available:

1. **Check for rdflib**: Run `python3 -c "from rdflib import Graph; print('OK')"`
   - If successful, use the inline inspection code below
   - If not, fall back to manual grep-based inspection (Step 1)

2. **Run automated inspection** (when rdflib is available):
   Copy and run this Python code:
   ```python
   from rdflib import Graph
   
   g = Graph()
   g.parse('/app/university_graph.ttl', format='turtle')
   
   print("=== GRAPH INSPECTION ===")
   
   # 1. Find namespace
   for prefix, ns in g.namespaces():
       if prefix and 'university' in str(ns).lower():
           print(f"Namespace: {prefix}: {ns}")
   
   # 2. Find types
   types = set()
   for s, p, o in g.triples((None, None, None)):
       if str(p) == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type':
           types.add(str(o).split('#')[-1])
   print(f"Types: {sorted(types)}")
   
   # 3. Find Person predicates
   person_preds = set()
   for s, p, o in g.triples((None, None, None)):
       if str(p) == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' and 'Person' in str(o):
           for s2, p2, o2 in g.triples((s, None, None)):
               person_preds.add(str(p2).split('#')[-1])
   print(f"Person predicates: {sorted(person_preds)}")
   
   # 4. Discover affiliation paths
   print("\n=== AFFILIATION PATHS ===")
   q = """
   SELECT DISTINCT ?pred1 ?pred2 WHERE {
     ?person a <http://university.org/ontology#Person> .
     ?person ?pred1 ?intermediate .
     ?intermediate ?pred2 ?uni .
     ?uni a <http://university.org/ontology#University> .
   }
   """
   results = g.query(q)
   for row in results:
       print(f"  {str(row[0]).split('#')[-1]} → {str(row[1]).split('#')[-1]}")
   
   # 5. Find role values
   print("\n=== ROLE VALUES ===")
   q2 = """
   SELECT DISTINCT ?role WHERE {
     ?person a <http://university.org/ontology#Person> .
     ?person ?pred ?role .
     FILTER(REGEX(STR(?pred), "role|rank|position", "i"))
   }
   """
   for row in g.query(q2):
       print(f"  '{row[0]}'")
   
   print("\n=== INSPECTION COMPLETE ===")
   ```
   
   This will:
   - Identify the ontology namespace/prefix
   - List all types (Person, University, Department, etc.)
   - Show predicates for Person entities
   - Discover affiliation paths (forward two-hop)
   - Extract role/rank values to understand professor identification

3. **Parse the output** to determine:
   - Which professor-identification pattern to use (string-rank vs resource-rank)
   - Which affiliation path exists (direct, department-mediated forward/inverse, appointment-based)
   - Which name predicates to use for persons and universities

4. **Proceed to Step 1** for manual verification or if rdflib is unavailable.

### Step 1: Inspect the Graph (Manual Fallback)

Read the TTL file and identify:

1. **Prefix/namespace**: Find the ontology prefix (e.g., `uni:` →
   `http://university.org/ontology#`). All predicates will use this namespace.

2. **Professor identification mechanism**: Search for how academic rank is
   expressed. Look for:
   - A literal-valued predicate like `uni:role` with strings containing
     "Professor" — this is the **string-rank** pattern.
   - A resource-valued predicate like `uni:hasAcademicRank` pointing to a node
     that has a `uni:rankLabel` — this is the **resource-rank** pattern.
   - Both may coexist; handle with UNION.

3. **Affiliation path** (concrete inspection technique):
   The goal is to discover which predicates connect a Person to a University,
   possibly through intermediaries. Use these methods in order:

   **Method A — Grep the TTL (bidirectional):**
   1. Search for all lines containing the University type declaration
      (e.g., `a uni:University`) to collect university URIs.
   2. Search for lines referencing those URIs as **objects** to find forward
      containment predicates. Example: grep for `uni:NTUA` and note predicates
      like `uni:partOfUniversity` where `?dept uni:partOfUniversity uni:NTUA`.
   3. Search for lines where those URIs appear as **subjects** to find inverse
      containment predicates. Example: look for lines starting with `uni:NTUA`
      and note predicates like `uni:containsDepartment` where
      `uni:NTUA uni:containsDepartment ?dept`.
   4. Then search for what predicates connect Person to the intermediate nodes
      (departments/appointments). Example: grep for `uni:ComputerScience_NTUA`
      to find `uni:worksAt`.
   5. This reveals the full chain in either direction:
      - Forward: `Person → worksAt → Department → partOfUniversity → University`
      - Inverse: `Person → worksAt → Department ← containsDepartment ← University`

   **Method B — SPARQL discovery queries** (if a SPARQL engine is available):
   Run these queries to find all predicate chains connecting Person to University
   in **both directions**:
   ```sparql
   # Forward two-hop: Person → ?pred1 → intermediate → ?pred2 → University
   SELECT DISTINCT ?pred1 ?pred2 WHERE {
     ?person a uni:Person .
     ?person ?pred1 ?intermediate .
     ?intermediate ?pred2 ?target .
     ?target a uni:University .
   }
   # Inverse two-hop: Person → ?pred1 → intermediate ← ?pred2 ← University
   SELECT DISTINCT ?pred1 ?pred2 WHERE {
     ?person a uni:Person .
     ?person ?pred1 ?intermediate .
     ?target a uni:University .
     ?target ?pred2 ?intermediate .
   }
   # Direct one-hop: Person → ?pred → University
   SELECT DISTINCT ?pred WHERE {
     ?person a uni:Person .
     ?person ?pred ?target .
     ?target a uni:University .
   }
   ```

   **Method C — Appointment resource check:**
   Some graphs use an intermediate "appointment" node between person and
   university. Check for this pattern:
   ```sparql
   SELECT DISTINCT ?pred1 ?pred2 WHERE {
     ?person a uni:Person .
     ?person ?pred1 ?appointment .
     ?appointment ?pred2 ?target .
     ?target a uni:University .
     FILTER(?appointment != ?target)
   }
   ```
   If this returns results, the graph uses appointment resources.

   Classify the result as one of:
   - **Direct**: `?person ?affiliationPred ?university` where `?university a
     uni:University`.
   - **Department-mediated (forward)**: `?person ?worksAtPred ?dept . ?dept
     ?partOfPred ?university` where `?dept a uni:Department`.
   - **Department-mediated (inverse)**: `?person ?worksAtPred ?dept . ?university
     ?containsPred ?dept` where `?university a uni:University`.
   - **Appointment resource**: `?person ?hasApptPred ?appt . ?appt ?atUniPred
     ?university` where the appointment is an intermediate node.
   - **Course fallback**: `?person ?teachesPred ?course . ?course ?taughtInPred
     ?dept . ?dept ?partOfPred ?university`.

4. **Name predicates**: Identify how person names and university names are
   stored (e.g., `uni:hasName`, `rdfs:label`, `foaf:name`).

5. **Noise entities**: Note what non-professor roles exist (Students,
   Lecturers, Staff) so you can confirm your filter excludes them.

### Step 2: Construct the Query

Build the SPARQL query following these principles:

#### Professor Filter

Use a case-insensitive regex or CONTAINS check that matches "Professor" in the
rank/role label. This captures:
- "Professor of X" (full professor)
- "Assistant Professor of X"
- "Associate Professor of X"
- "Prof. X" (abbreviation)
- "Asst. Prof. of X"

**String-rank pattern:**
```sparql
?person :role ?role .
FILTER(REGEX(?role, "Professor|Prof\\.", "i"))
```

**Resource-rank pattern:**
```sparql
?person :hasAcademicRank ?rank .
?rank :rankLabel ?rankLabel .
FILTER(REGEX(?rankLabel, "Professor|Prof\\.", "i"))
```

**Combined with UNION:**
```sparql
{
  ?person :role ?roleLabel .
  FILTER(REGEX(?roleLabel, "Professor|Prof\\.", "i"))
}
UNION
{
  ?person :hasAcademicRank ?rank .
  ?rank :rankLabel ?rankLabel .
  FILTER(REGEX(?rankLabel, "Professor|Prof\\.", "i"))
}
```

#### Affiliation Path

Use the path discovered in Step 1. If multiple paths may coexist, use UNION or
OPTIONAL with COALESCE. The most common patterns:

**Department-mediated (forward containment, most common in seed):**
```sparql
?person :worksAt ?dept .
?dept :partOfUniversity ?uni .
```

**Department-mediated (inverse containment):**
```sparql
?person :worksAt ?dept .
?uni :containsDepartment ?dept .
?uni a :University .
```

**Direct:**
```sparql
?person :worksAt ?uni .
?uni a :University .
```

**Appointment resource:**
```sparql
?person :hasAppointment ?appt .
?appt :atUniversity ?uni .
?uni a :University .
```

**Course fallback (when worksAt may be absent):**
```sparql
OPTIONAL { ?person :worksAt ?dept . ?dept :partOfUniversity ?uni . }
OPTIONAL {
  ?person :teaches ?course .
  ?course :isTaughtIn ?courseDept .
  ?courseDept :partOfUniversity ?uniFromCourse .
}
BIND(COALESCE(?uni, ?uniFromCourse) AS ?university)
```

#### Name Extraction

```sparql
?person :hasName ?professorName .
?university :hasName ?universityName .
```

(Adapt predicate names to what the graph actually uses.)

#### Deduplication

Always use `SELECT DISTINCT` to guarantee exactly one row per
professor–university pair, regardless of how many courses a professor teaches
or how many departments they are affiliated with.

#### Complete Query Template

The template below uses **placeholders** for the affiliation path. You MUST
replace the affiliation section with the concrete path discovered in Step 1.

```sparql
PREFIX uni: <ONTOLOGY_NAMESPACE>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?person a uni:Person ;
          uni:hasName ?professorName .

  # --- Professor identification ---
  # Include ONLY the branch(es) that exist in this graph.
  # If the graph uses role strings:
  {
    ?person uni:role ?roleLabel .
    FILTER(REGEX(?roleLabel, "Professor|Prof\\.", "i"))
  }
  # If the graph uses academic-rank resources, add this branch (UNION):
  # {
  #   ?person uni:hasAcademicRank ?rank .
  #   ?rank uni:rankLabel ?rankLabel .
  #   FILTER(REGEX(?rankLabel, "Professor|Prof\\.", "i"))
  # }

  # --- Affiliation path ---
  # PICK EXACTLY ONE of the following based on Step 1 findings:
  #
  # OPTION A — Department-mediated (forward containment, most common):
  #   ?person uni:worksAt ?dept .
  #   ?dept uni:partOfUniversity ?university .
  #
  # OPTION B — Direct link:
  #   ?person uni:worksAt ?university .
  #   ?university a uni:University .
  #
  # OPTION C — Course fallback (when worksAt may be absent):
  #   OPTIONAL { ?person uni:worksAt ?dept . ?dept uni:partOfUniversity ?university . }
  #   OPTIONAL {
  #     ?person uni:teaches ?course .
  #     ?course uni:isTaughtIn ?courseDept .
  #     ?courseDept uni:partOfUniversity ?uniFromCourse .
  #   }
  #   BIND(COALESCE(?university, ?uniFromCourse) AS ?university)
  #
  # OPTION D — Department-mediated (inverse containment):
  #   ?person uni:worksAt ?dept .
  #   ?university uni:containsDepartment ?dept .
  #   ?university a uni:University .
  #
  # OPTION E — Appointment resource:
  #   ?person uni:hasAppointment ?appt .
  #   ?appt uni:atUniversity ?university .
  #   ?university a uni:University .

  ?university uni:hasName ?universityName .
}
```

### Step 3: Validate

**Primary method (when rdflib is available):**

Copy and run this Python code:
```python
from rdflib import Graph

g = Graph()
g.parse('/app/university_graph.ttl', format='turtle')

with open('/app/solution.sparql') as f:
    query = f.read()

results = g.query(query)
print(f"Results: {len(results)}")
print(f"Variables: {[str(v) for v in results.vars]}")
print()

rows = sorted([(str(r[0]), str(r[1])) for r in results])
for prof, uni in rows:
    print(f"  {prof:35s} | {uni}")

if len(rows) != len(set(rows)):
    print("\nWARNING: Duplicates found!")
else:
    print("\nNo duplicates.")
```

This will:
- Load the graph and execute the query
- Report the number of results and variable names
- Print all results sorted by professor name
- Check for duplicate rows

**Fallback method (manual validation):**

1. **Mental trace**: For each person in the graph, check:
   - Does their role/rank match the professor filter?
   - Does their affiliation path resolve to a university?
   - Are non-professors (Lecturers, Students, Staff) correctly excluded?

2. **Cardinality check**: Count expected results. Each qualifying professor
   should appear exactly once. If a professor has multiple signals (teaches
   multiple courses, multiple departments), DISTINCT should collapse them.

3. **Edge cases**: Verify that:
   - "Lecturer" does NOT match the professor filter.
   - "Student" does NOT match.
   - Abbreviations like "Prof." DO match.

## Decision Checklist

When facing a new variant, answer these questions in order:

| # | Question | Action |
|---|----------|--------|
| 1 | Does the graph use `role` strings or `hasAcademicRank` resources for rank? | String-rank → regex on `?role`; Resource-rank → regex on `?rankLabel`; Both → UNION |
| 2 | Which affiliation pattern did Step 1 discover? | **Direct** → `?person ?pred ?uni`; **Dept-mediated (forward)** → `?person ?pred ?dept . ?dept ?pred2 ?uni`; **Dept-mediated (inverse)** → `?person ?pred ?dept . ?uni ?containsPred ?dept`; **Appointment resource** → `?person ?pred ?appt . ?appt ?pred2 ?uni`; **Course fallback** → OPTIONAL with COALESCE |
| 3 | Might `worksAt` be absent for some professors? | Add course-fallback OPTIONAL with COALESCE |
| 4 | Are there multiple name predicates? | Use the one on Person/University nodes (check `?person ?namePred "literal"` and `?uni ?namePred "literal"`) |
| 5 | Are there duplicate signals (multiple courses/departments)? | Always use SELECT DISTINCT |

## Common Pitfalls

1. **Over-broad regex**: `FILTER(REGEX(?role, "prof", "i"))` would match
   "Professional" — use "Professor" or "Prof\\." specifically.
2. **Missing DISTINCT**: Without it, a professor teaching 2 courses in the same
   department produces 2 rows.
3. **Hardcoding predicates**: Always inspect the graph first; predicates may
   differ across variants.
4. **Case sensitivity**: Always use case-insensitive matching (`"i"` flag).
5. **Assuming single affiliation path**: Check whether the graph uses direct
   links, department mediation, or both.
