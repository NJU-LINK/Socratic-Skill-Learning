---
name: sparql-professors-universities
description: >
  Write and self-verify a SPARQL query over a university RDF/Turtle knowledge
  graph that returns professor names paired with their university names.
  Covers identifying which people count as professors from role strings or
  rank resources (including near-miss titles), discovering the person-to-
  university affiliation path in varying schemas, and guaranteeing exactly one
  row per professor-university pair under noisy graphs.
---

# SPARQL: Professors and their Universities

## Deliverable contract (check first, enforce last)

The instruction defines the contract. Extract from it before writing anything:

- **Output file path** (seed: `/app/solution.sparql`) — save exactly there.
- **Projection variables** (seed: `?professorName ?universityName`) — project
  *exactly* these, in the given spelling, and nothing else. Extra variables or
  renamed variables are a common silent failure.
- **Qualifying population** — which roles/ranks count as "professor", and any
  stated assumptions (e.g. "each professor works at exactly one university").
- **Input graph path** (seed: `/app/university_graph.ttl`) — the file may have a
  different name or there may be several `.ttl` files; scan `/app`.

Family invariant regardless of variant: **one row per qualifying
professor–university pair, with exactly the requested variables, executable by
a standard SPARQL 1.1 engine** (the seed environment ships Python + rdflib,
no Jena; rdflib is the realistic grading engine, so avoid exotic syntax).

## Workflow

1. Read the instruction end to end; note path, variable names, qualifying ranks.
2. Inspect the graph before writing the query (5 minutes, pays for itself).
   Do ALL work under `/app` through the shell tool — the workspace `read`/`ls`
   file tools reject `/app` paths with WORKSPACE_BOUNDARY errors; use `cat`,
   heredocs, and `python3` in the shell instead:
   ```bash
   grep -hE '^@prefix' /app/*.ttl    # actual prefixes/namespaces - never assume `uni:`
   grep -ohE '[a-zA-Z]+:[A-Za-z_]+' /app/*.ttl | sort | uniq -c | sort -rn
   ```
   and run exploratory queries with rdflib (runner pattern in the Verification
   section below):
   - `SELECT DISTINCT ?p WHERE { ?s ?p ?o }` — the actual predicate vocabulary.
   - `SELECT DISTINCT ?role WHERE { ?person uni:role ?role }` — the actual
     role/rank values (or the rank-resource equivalent, see below).
   - Dump one sample professor completely:
     `SELECT ?p ?o WHERE { uni:SOME_PROFESSOR ?p ?o }`
3. Decide the professor filter (next section).
4. Decide the affiliation path (section after).
5. Write the query with **its own PREFIX block** — prefixes declared in the
   `.ttl` file do NOT carry over to a separate `.sparql` file.
6. Execute the query against the real graph and verify (verification section).
   Never consider the task done without a successful local run.

## Axis 1 — Identifying qualifying professors

Verify by construction — a four-step loop, never filter blind:

1. **Enumerate** every distinct role/rank value:
   `SELECT DISTINCT ?role WHERE { ?person uni:role ?role }`
2. **Classify** each value IN or OUT against the instruction's qualifying set
   (seed: full professors `"Professor of X"` and assistant professors
   `"Assistant Professor of X"` are IN; `"Lecturer"`, `"Student"` are OUT).
3. **Build** a filter reproducing exactly that classification:
   - **Explicit value list** — safest when few distinct values exist:
     `FILTER(LCASE(STR(?role)) IN ("professor of mathematics", ...))`
   - **Anchored, case-insensitive REGEX** — for pattern families. Derive the
     alternation from the ENUMERATED values, not from memory: the seed pattern
     `^(assistant )?professor( of|$)` silently misses spellings variants may
     use, e.g. `"Full Professor of X"`, `"Prof. of Y"`, `"Asst. Prof. of Z"`.
     A wider family (adapt to the instruction — add `associate` etc. only if
     the instruction includes it):
     ```sparql
     FILTER(REGEX(STR(?role), "^(full |assistant |asst[.]? )?prof(essor)?[.]?( of|$)", "i"))
     ```
     Observed facts: `CONTAINS(?r,"Professor")` wrongly matches `"Associate
     Professor"` and `"Professor Emeritus"` and misses lowercase spellings.
     rdflib gotcha (verified): write a literal dot as `[.]` — `\.` is an
     invalid SPARQL string escape and makes rdflib fail to parse the query.
   - **Plain `CONTAINS`** — acceptable ONLY if the enumeration confirms no
     near-miss titles exist.
4. **Audition the filter** against every distinct value before committing —
   one query shows the verdict per value:
   ```sparql
   SELECT DISTINCT ?role (IF(<your filter expression>, "IN", "out") AS ?verdict)
   WHERE { ?person uni:role ?role } ORDER BY ?verdict ?role
   ```
   Every verdict must match your step-2 classification. If not, fix the
   filter, not the data.

Variant shape to expect: rank may be a resource instead of a string —
`?person uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?label .` — then apply
the same decision rules to `?label`. If both representations coexist, bind one
signal with `OPTIONAL` + `COALESCE(?role, ?label)` and filter once. Always wrap
literals in `STR()` before string functions (language tags/datatypes break
naive comparisons).

## Axis 2 — Path from person to university name

Do not assume the seed topology; discover it from the predicate listing and the
sample-person dump. Seed path (verified):

```sparql
?professor uni:worksAt ?dept .          # person -> department
?dept uni:partOfUniversity ?uni .       # department -> university
?uni uni:hasName ?universityName .
?professor uni:hasName ?professorName .
```

Variant shapes and how to handle them:

- **Direct affiliation** (`?professor uni:worksAt ?uni` where `?uni a
  uni:University`) — check the *type* of the affiliation target, not the
  predicate name, to know whether you arrived.
- **Inverse containment** — university points down
  (`?uni uni:hasDepartment ?dept`): just flip the triple.
- **Longer chains** — department → faculty → university: extend the chain,
  verifying each hop against the data.
- **Heterogeneous chains** (verified risk): when different professors reach a
  university through different-length or different-direction links, a single
  fixed-length pattern silently drops everyone not matching it (observed: a
  fixed dept→uni pattern found only 1 of 4 professors in a mixed graph).
  Build a length-tolerant path from the org→org predicates you discovered:
  ```sparql
  ?professor uni:worksAt ?org .
  ?org (uni:partOfUniversity|uni:partOfFaculty|^uni:hasDepartment)* ?university .
  ?university a uni:University ; uni:hasName ?universityName .
  ```
  Rules: put EVERY discovered org→org predicate in the alternation (inverse
  ones as `^pred`); the `?university a uni:University` type anchor is
  MANDATORY — it keeps intermediate orgs out and makes zero-length (direct)
  affiliation work; keep `DISTINCT`. Verified: this one pattern returns the
  correct 7 rows on the seed graph AND all four of 2-hop/3-hop/inverse/direct
  professors in a mixed graph. Caveat: `*` follows chains of any length, so a
  pathological university→university link inflates rows — the reconciliation
  check (verification step 6) catches it. When every sampled professor shows
  the SAME topology, a plain fixed-length pattern is equally correct and
  simpler; use the property path when topologies are mixed or unsampled.
- **Appointment resources** (person → appointment → organization): same
  discovery — traverse through the intermediate node, checking the type of
  each hop's object; then apply the fixed or length-tolerant pattern above.
- **Preferred path with fallback** — instruction hints some professors lack the
  direct link (e.g. no `worksAt`, only `teaches`). CRITICAL, verified behavior:
  a **raw `UNION` double-counts** anyone reachable by both paths — in the seed
  graph Felix Wagner teaches courses in two different universities, so
  `worksAt-path UNION teaches-path` yields 8 rows instead of 7. Guard the
  fallback branch so it fires only when the preferred link is absent:
  ```sparql
  {
    ?professor uni:worksAt ?dept .
    ?dept uni:partOfUniversity ?uni .
  }
  UNION
  {
    ?professor uni:teaches ?course .
    ?course uni:isTaughtIn ?dept .
    ?dept uni:partOfUniversity ?uni .
    FILTER NOT EXISTS { ?professor uni:worksAt ?anyDept }
  }
  ```
  (An `OPTIONAL` + `COALESCE(?direct, ?derived)` formulation also works; the
  essential property is *preference*, not *union of everything*. The path
  inside each branch can itself be the length-tolerant expression above.)

Do not pattern-match through `uni:teaches` unless you need it as a fallback —
it fans out (one professor, many courses, possibly many universities).

## Axis 3 — Cardinality and noise control

- Always `SELECT DISTINCT` on exactly the requested variables. It is the cheap
  insurance against duplicate role triples, multi-department professors, and
  multi-path bindings.
- Keep auxiliary variables (`?role`, `?dept`, `?uni`…) out of the projection.
- Do not rely on the instruction's "exactly one university" assumption to skip
  dedup — fan-out enters through *other* relations (teaches, multiple names).
- Expect decoys: lecturers/students/staff, professors of unrelated-looking
  departments, multiple departments in one university. The filter, not luck,
  must exclude them.
- Multiple `hasName` values per person (aliases, language variants) produce
  multiple rows that `DISTINCT` CANNOT merge (the literals differ). Verified:
  one professor with two name literals yields two rows. If (and only if)
  inspection shows this, dedupe at the source with a subquery:
  `{ SELECT ?prof (SAMPLE(?n) AS ?professorName) WHERE { ?prof uni:hasName ?n } GROUP BY ?prof }`

## Reference query (seed topology — re-derive, don't copy blindly)

```sparql
PREFIX uni: <http://university.org/ontology#>

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?department .
  FILTER(REGEX(STR(?role), "^(assistant )?professor( of|$)", "i"))
  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
ORDER BY ?professorName
```

Verified against the seed graph: 7 rows (Alex Morgan, Thomas Berger,
Felix Wagner, Martin Keller, John Smith, Marie Dubois, Stefan Mueller;
Jane Petterson the Lecturer and all Students excluded), correct universities,
exactly two columns. `ORDER BY` is optional but makes output deterministic.
The FILTER above fits the seed's enumerated role values exactly; the moment
the enumeration shows any other spelling, rebuild the filter through the
Axis-1 loop instead of reusing this pattern.

## Verification protocol (mandatory before finishing)

Run the saved file against the real TTL and check all of the following
(`scripts/verify_solution.py` in this skill automates it; copy it to /tmp and
run `python3 verify_solution.py`, or inline the equivalent):

```python
import rdflib
g = rdflib.Graph(); g.parse("/app/university_graph.ttl", format="turtle")
res = g.query(open("/app/solution.sparql").read())   # 1. parses & runs
print([str(v) for v in res.vars])                    # 2. EXACTLY the requested vars
rows = [tuple(str(c) for c in r) for r in res]
print(len(rows), len(set(rows)))                     # 3. counts must be equal
for row in sorted(rows): print(row)                  # 4. eyeball the population
```

Checklist:

1. Query parses and executes under rdflib (grading-realistic engine).
2. Projected variables match the instruction exactly (names, count).
3. `len(rows) == len(set(rows))` — no duplicates.
4. Row count equals the number of qualifying professors you counted via the
   `DISTINCT ?role` enumeration — not more (near-misses leaked in), not fewer
   (case/spelling variants dropped).
5. Spot-check known exclusions (seed: no "Jane Petterson", no students).
6. Reconcile counts both directions:
   - Final row count must EQUAL the number of distinct qualifying people:
     `SELECT (COUNT(DISTINCT ?p) AS ?c) WHERE { ?p uni:role ?r . FILTER(<your filter>) }`.
     Fewer rows than qualifying people = some professor has no affiliation
     under your path pattern → re-inspect the topology (Axis 2) before
     finishing; do NOT ship a silently incomplete result.
   - Nobody appears with two different universities (unless the instruction
     allows it): group your intermediate bindings per person and check
     `COUNT(DISTINCT ?university) <= 1` for each.
7. Re-read the instruction once more: right file path, right variable names.
   The solution file is the only required artifact — make sure it exists and
   holds the final version of the query.
8. Optional robustness probe (cheap, catches over/under-matching before the
   hidden tests do): in Python, parse the graph, inject a hypothetical probe
   person into the IN-MEMORY graph only — e.g. a near-miss role the
   instruction excludes (`"Associate Professor of Testing"`) and a spelling
   variant it includes — re-run the saved query, and confirm each probe is
   classified correctly. Never write probe triples into the real `.ttl`.

## Failure modes observed / anticipated

| Symptom | Cause | Fix |
|---|---|---|
| 0 results / parse error | Missing PREFIX in the `.sparql` file | Declare all prefixes in the query |
| Extra rows like Associate/Emeritus | Substring `CONTAINS "Professor"` | Anchored REGEX or explicit value list |
| Missing lowercase/abbreviated titles | Case-sensitive match | `LCASE()` or REGEX `"i"` flag |
| One professor, two universities | Raw UNION of preferred+fallback paths | Guard fallback with `FILTER NOT EXISTS` |
| Duplicate identical rows | Multiple teaches/roles fan-out | `SELECT DISTINCT` on final projection |
| Same person under two names | Multiple `hasName` literals | `GROUP BY ?prof` + `SAMPLE(?name)` subquery |
| Parse error mentioning FILTER/regex | `\.` escape in regex string | Use `[.]` for a literal dot (rdflib) |
| Qualifying spelling missed (e.g. "Full Professor") | Regex copied from seed, not derived | Audition query over `DISTINCT ?role` (Axis 1) |
| Test rejects columns | Extra/helper variable projected | Project only the requested variables |
| Empty university for some professors | Preferred link absent in data | Guarded fallback path (Axis 2) |
| Qualifying professors silently missing | Fixed-length path vs mixed topologies | Length-tolerant property path + type anchor (Axis 2); reconcile counts |
| Rows inflated past person count | `*` path crosses university→university link | Restrict alternation to discovered org→org preds; check counts |
