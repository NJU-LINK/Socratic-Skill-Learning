---
name: sparql-professors-universities
description: >
  Write a SPARQL SELECT query over a university Turtle knowledge graph that
  returns one row per qualifying professor-university pair, projecting exactly
  the requested variables (e.g. ?professorName ?universityName). Covers rank
  filters (string roles or rank resources), robust person-to-university
  affiliation chains (worksAt preferred, teaches fallback when stated), and
  duplicate-row control, verified locally with python3 + rdflib before saving
  /app/solution.sparql.
---

# SPARQL: Professor names and their universities

The task is always the same shape: **one Turtle file describes a university
knowledge graph; produce a SPARQL query file that selects professors (some
professor ranks) and the name of the university each works at.** The word
"professor" in this skill means *the qualifying personnel the current task
instruction defines*; the exact ranks vary per case, so read the instruction
first every time.

## Hard family invariants

1. Solution artifact is a **query text file** (anchor: `/app/solution.sparql` —
   re-read the instruction for the exact path; only the query text belongs in it).
2. Project exactly the variables the instruction names, in the order given
   (anchor: `?professorName ?universityName`). No extra projection variables.
3. One row per qualifying professor–university pair: use `SELECT DISTINCT`.
4. Output values are the **stored literals** (names from the name predicate).
   Keep accents ("Müller") as-is; never reconstruct or normalize names.
5. Persons who are **not** the qualifying rank — anchor evidence: `Lecturer`,
   `Student` — must never appear in the result.
6. A professor is attached to a university through an **employment /
   affiliation chain** (anchor: `worksAt` → `partOfUniversity`), not teaching
   activity, unless the instruction explicitly gives a teaching fallback.
7. Reliable local SPARQL execution in the task container is **python3 +
   rdflib** (6.x); assume the grader works the same way. The query must be
   plain SPARQL 1.1 that rdflib parses: declare every prefix used; limits
   tested OK: `regex` with flags, property paths (`* +`), `UNION`,
   `FILTER NOT EXISTS`, `a`/`rdf:type`. Avoid Jena-only or exotic extensions.

## Workflow

### Step 1 — Read the task instruction for the two content clauses

Before touching the graph, extract from the instruction:
- **which ranks qualify** (anchor says Full Professors and Assistant
  Professors; a variant may say "all ranks containing professor", "only Full
  Professors", or add Associate/etc.),
- **which affiliation relations the case promises** (anchor promises
  `uni:role` strings and `worksAt`, one university per professor; a variant may
  mention rank resources, longer chains, or a teaching fallback when `worksAt`
  is absent),
- the exact output variable names and file path.

### Step 2 — Inspect the actual graph with one preflight command (never skip)

Vocabulary varies per case; this single heredoc prints everything the three
decision axes need: the declared prefixes, classes, predicates, every
rank/role value, per-person out-links, org-tree edges, and typed
organizations. Run it verbatim (adjust the PATH for the file the instruction
names).

```bash
python3 - <<'PYEOF'
import re, rdflib
from collections import Counter
PATH = '/app/university_graph.ttl'   # from the instruction
RDF = rdflib.RDF
print("PREFIXES:", dict(re.findall(r'@prefix\s+(\w+):\s+<([^>]+)>', open(PATH).read())))
g = rdflib.Graph(); g.parse(PATH, format='turtle')
def loc(p): return str(p).split('#')[-1].split('/')[-1].lower().replace('_','').replace('-','')
print("TRIPLES:", len(g))
print("CLASSES:", Counter(loc(o) for o in g.objects(None, RDF.type)))
preds = set(g.predicates()); print("PREDICATES:", sorted(loc(p) for p in preds))
rolep = {p for p in preds if any(k in loc(p) for k in ("role","rank","position","title"))}
namep = {p for p in preds if loc(p).endswith("name") or loc(p).endswith("label")}
print("RANK-VALUE CENSUS:", sorted({str(o) for p in rolep for o in g.objects(None, p)}))
typmap = dict((s, o) for s, o in g.subject_objects(RDF.type))
persons = {s for p in rolep for s in g.subjects(p, None)}
persons |= {s for s, t in typmap.items() if any(k in loc(t) for k in ("person","emplo","fac","staff","researcher"))}
print("\n-- PERSONS & RANK NODES (name / rank / out-links) --")
for s in sorted(persons, key=str):
    n = sorted({str(o) for p in namep for o in g.objects(s, p)})
    r = sorted({str(o) for p in rolep for o in g.objects(s, p)})
    out = sorted(f"{loc(p)}>{loc(o)}" for p, o in g.predicate_objects(s) if isinstance(o, rdflib.URIRef))
    print(f"{loc(s)}  name={n} rank={r} links={out}")
partp = {p for p in preds if any(k in loc(p) for k in ("partof","suborg","inside","container","organization"))}
print("\n-- ORG-TREE EDGES (subject -pred> object) --")
for p in partp:
    for s, o in g.subject_objects(p): print(f"  {loc(s)} -{loc(p)}> {loc(o)}")
print("\n-- TYPED ORGS --")
for s, t in sorted(typmap.items(), key=lambda x: str(x[0])):
    if any(k in loc(t) for k in ("university","college","faculty","department","school","institute","org","course")):
        n = sorted({str(o) for p in namep for o in g.objects(s, p)})
        print(f"  {loc(s)} a {loc(t)} {n}")
PYEOF
```

Read the output as a decision sheet:

- **PREFIXES** → the exact namespace to `PREFIX` in the query (may differ
  from the anchor's `uni:`).
- **CLASSES / TYPED ORGS** → the university class (the one carrying the name;
  departments/courses usually have none) and the person class.
- **RANK-VALUE CENSUS** → the Axis-1 IN/OUT list, including abbreviations,
  near-misses, and any rank-label literals from rank resources.
- **PERSONS links** → the person→org bridge as written in the data: `worksat>`
  (plain), `holds>` plus an `-atorganization>` tree edge (appointment
  bridge), inverted edges (`emplo` etc. pointing *at* the person appear in
  subjects elsewhere — search the output), or no org link (fallback case).
  It also exposes teaching links that cross into a *different* org — the
  anchor trap detector.
- **ORG-TREE EDGES** → the exact upward predicate and direction; if the chain
  mixes predicates across hops, use a path alternation (see Axis 2).

`head -n 40` of the Turtle file remains a good one-line sanity check for the
prefix/format, but the preflight is the discovery step.

### Step 3 — Choose the patterns (keyed to the spec's variation axes)

**Axis 1: professor identification.** Work from the rank census (Step 2 / Step
4 prints it) plus the instruction, in this order:

1. Collect the distinct rank values. Every spelling variant is visible in the
   census before you write the filter — decide IN/OUT per value.
2. Mark each census value IN or OUT according to the instruction's rank
   vocabulary (anchor: `Professor of X` + `Assistant Professor of X` IN,
   `Lecturer`/`Student` OUT). Never match on the subject-area suffix (e.g.
   "of Computer Science") — only the rank token carries the semantics; a
   typo like the anchor's `Scienceand Technology` must not break the filter.
3. String rank values (e.g. `uni:role`): choose the filter that matches the IN
   set and nothing in the OUT set. Default:
   `FILTER (regex(?role, "professor", "i"))`.
   If any IN value abbreviates the rank — `Prof`, `Prof.`, `Full Prof of X`
   (spec axis: "spelling and abbreviations") — the default misses it; use the
   abbreviation-aware form instead:
   `FILTER (regex(?role, "(^|\\s)(prof\\.?|professor)(\\s|$)", "i"))`
   (simulation-verified: keeps `Prof`/`Prof.`/`Professor of X`/`Assistant
   Professor of X`/`Associate Prof. of Y`/lowercase forms; drops
   `professional staff`, `Professor's Assistant`, `Lecturer`, `Student`).
   If the instruction enumerates an *exact* rank set (e.g. only Full and
   Assistant), collapse to that set explicitly:
   `FILTER (regex(?role, "^(Full|Assistant) Professor", "i"))`.
4. Rank as a resource (no string role predicate):
   `?p uni:hasAcademicRank ?r . ?r uni:rankLabel ?role .` and filter the label;
   or filter the rank node's `rdf:type` when ranks are individually typed
   (`?r a uni:FullProfessor`). If the filter silently yields zero rows, the
   variant likely moved the rank off a string — check the census again.
   If the two representations coexist across different persons (some have
   `uni:role` strings, others only rank resources), UNION both rank patterns
   so nobody qualifying is missed.
5. Post-check (always): print which values actually passed the filter and
   confirm against the IN list. A non-rank description that still passes
   (e.g. the boundary form keeps `Assistant to the Professor`) is then
   blocked with an explicit disjunction of the IN values. Decide from observed
   data, not from guesses.

**Axis 2: affiliation chain.** Prefer employment; fall back to teaching only
when the case states it (spec axis explicitly lists a "preferred worksAt path
with a teaching-course fallback"). Canonical chain shape, robust to depth:

```sparql
?person uni:worksAt ?org .
?org uni:partOfUniversity* ?university .
?university a uni:University ; uni:hasName ?universityName .
```

- `partOfUniversity*` plus the `a uni:University` filter handles **both**
  direct affiliation (person works at the university; zero-length step) and
  chains of any depth (department → faculty → university). Anchor-verified:
  identical results to the simple one-step version. Rename predicates/class to
  whatever the graph actually uses (mind inverse-direction variants: match
  edge direction as written in the data, e.g. `?university uni:hasDepartment
  ?dept . ?dept uni:employs ?person`).
- Do **not** require `?professor a uni:Person` — persons may be untyped or
  typed with a different class in variants; the name + rank patterns already
  constrain the candidates, and the person type facts in the data could be
  missing or renamed.
- If the upward walk mixes predicates across hops (dept `partOfUniversity`
  faculty, faculty `subOrganizationOf` university), use a path alternation
  instead of a single predicate:
  `?org (uni:partOfUniversity|uni:subOrganizationOf)* ?university .`
  plus the university class filter as the chain terminator.
- Appointment resources (person → appointment node → organization): treat the
  appointment node as the person–org bridge —
  `?professor uni:holds ?appointment . ?appointment uni:atOrganization ?org .`
  then the usual `?org uni:partOfUniversity*` chain. The rank may sit on the
  person or on the appointment node; read the actual bridge predicates from
  the data (simulation-verified: `holds` → `atOrganization`).
- When the instruction defines a fallback ("if a professor has no worksAt,
  use the courses they teach"), use UNION where the second branch is guarded
  so it can't add a wrong second university for people who *do* have worksAt:

```sparql
SELECT DISTINCT ?professorName ?universityName WHERE {
  { # preferred branch: worksAt chain
    ?professor uni:hasName ?professorName ; uni:role ?role ; uni:worksAt ?org .
    ?org uni:partOfUniversity* ?university .
    ?university a uni:University ; uni:hasName ?universityName .
    FILTER (regex(?role, "professor", "i")) }
  UNION
  { # fallback branch: only for professors with NO worksAt (guard is mandatory)
    ?professor uni:hasName ?professorName ; uni:role ?role .
    FILTER (regex(?role, "professor", "i"))
    FILTER NOT EXISTS { ?professor uni:worksAt ?any }
    ?professor uni:teaches ?course . ?course uni:isTaughtIn ?org .
    ?org uni:partOfUniversity* ?university .
    ?university a uni:University ; uni:hasName ?universityName . }
}
```

  A naive `UNION` without `FILTER NOT EXISTS` **double-binds professors who
  teach cross-university** (anchor trap, see below). Verified on the anchor:
  guarded version = 7 correct rows; unguarded teaches-path = 8 rows including
  a wrong university.

**Axis 3: noise and cardinality.** Structural defenses, apply always:

- `SELECT DISTINCT` on the projection (protects against a person having
  several name literals, several departments, or several courses in one
  university).
- Never join through `teaches` unless the fallback branch above is being used.
- Do not project extra helper variables (`?role`, `?university`) even as
  checks — the result file must have exactly the requested two columns.
- Cross-check counts: the distinct count of qualifying professors should
  equal the final row count (per the one-university-per-professor promise).

### Step 4 — Verify locally before finishing (rdflib, same as the grader)

Skill files live host-side and are **not mounted inside /app** — `cp`-ing
`scripts/...` into the container fails, so do not depend on it. Run the
compact verifier below directly inside the container; it prints the projected
variables, sorted rows, any first-column duplicates, the rank-value census
(the IN/OUT decision set), and the classes in the graph:

```bash
python3 - <<'EOF'
import rdflib
from collections import Counter
g = rdflib.Graph(); g.parse('/app/university_graph.ttl', format='turtle')
res = g.query(open('/app/solution.sparql').read())
rows = sorted(tuple(str(x) for x in r) for r in res)
print("VARS:", [str(v) for v in res.vars])
print("ROWS:", len(rows))
for r in rows: print("   " + " | ".join(r))
dups = {n: c for n, c in Counter(r[0] for r in rows).items() if c > 1}
print("DUP first-column names:", dups or "none")
role_preds = [p for p in set(g.predicates())
              if any(k in str(p).lower() for k in ("role", "rank"))]
print("RANK-VALUE CENSUS:", sorted({str(o) for p in role_preds
                                     for o in g.objects(None, p)}))
print("CLASSES:", sorted({str(o).split('#')[-1]
                          for o in g.objects(None, rdflib.RDF.type)}))
EOF
```

(Adjust the graph/query paths to whatever the instruction names. The fuller
diagnostic dump in `scripts/check_query.py` is optional, not required.) Then
assert each of these:

1. Variables printed == exactly the requested names, in the requested order.
2. Every known near-miss (`Lecturer`, `Student`, `Staff`, ...) is absent from
   the rows.
3. No professor appears with two universities, and no row is obviously
   attached through a teaching relationship (e.g. a professor whose `worksAt`
   is in university A but who appears with B).
4. Row count == count of qualifying persons (if some qualify but have no
   affiliation at all, either the case intends a fallback you missed or those
   persons must be excluded — re-read the instruction).
5. The query parses without warnings; no undeclared prefixes.

If verification fails, debug by running the same query with the `FILTER` and
`DISTINCT` temporarily removed to see what changed, then re-tighten.

**Empty or wrong-sized result — debug ladder.** Diagnose before editing
blindly:
- **0 rows** → delete the FILTER first. Rows appear → the rank filter missed
  (see Axis 1: abbreviations, rank resources, case). Still 0 → the
  affiliation shape is wrong: use the diagnostics to find which predicate
  actually links persons to organizations (`worksAt`-like, appointment
  bridge, or inverted university→department→person edges) and rebuild the
  chain from the data.
- **rows < professor count** → some qualifying persons lack the chosen
  affiliation predicate; either the case wants a fallback (teaches / another
  path) or those persons genuinely should not appear — re-read the
  instruction, then add the guard `FILTER NOT EXISTS` fallback branch only if
  the instruction calls for it.
- **rows > professor count or DUP names** → duplicate bindings from several
  name literals, several departments, or a teaching/cross-university join
  leak. Find the duplicated person in the printed rows, locate the extra
  binding in the diagnostics, and keep only the employment path. Two rows
  sharing a name but pointing at *different* universities means the person
  has genuine multiple org links in the data — re-read the instruction, then
  re-check which predicate the case defines as the affiliation (employment
  wins over teaching; prune the other path, don't guess).

## Known trap (observed in anchor v01) — teaching is not employment

Anchor has `Felix Wagner` with `role "Professor of Mathematics"`,
`worksAt` the math department of university IST, while `teaches` a course in
the computer-science department of university NTUA. A
`teaches → isTaughtIn → partOfUniversity` path yields a duplicate row and a
*second, wrong* university for him (8 rows instead of 7). **Consequence:**
prefer the employment relation for affiliation; when the case really does use
teaching, apply the `NOT EXISTS` guard above, and if both relations exist and
disagree, the employment relation wins (the spec's "preferred worksAt path").

## Observed vs. extrapolated

- *Observed in anchor:* `uni:` namespace `http://university.org/ontology#`;
  classes `University/Department/Course/Person`; predicates `hasName, role,
  worksAt, partOfUniversity, teaches, isTaughtIn`; rank strings `Professor of
  X` / `Assistant Professor of X`, excluded `Lecturer`/`Student`; one cross-
  university teaching trap; every qualifying professor has `worksAt`.
- *Extrapolated from spec axes (treat as possibilities to detect, not assume):*
  rank resources + `rankLabel` or typed ranks; broader/narrower rank sets;
  abbreviations (`Prof`, `Prof.`); professor-like near-misses; direct,
  multi-step, inverted, or appointment-bridged affiliation chains; mixed
  upward predicates across hops; a teaches fallback; larger noisier graphs
  with duplicated name literals or multi-department professors. These were
  executed against simulated variant graphs — rankLabel-only ranks,
  abbreviation-aware regex, appointment bridges, inverse edges, guarded
  fallback, and one graph combining all of them (mixed rank representations +
  abbreviation + path-alternation chain + fallback + possessive near-miss) —
  and behave as described. The Step-2 preflight prints the structures the
  axes depend on for any graph, so variant handling reduces to reading its
  output rather than recalling recipes.