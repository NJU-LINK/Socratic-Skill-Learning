---
name: sparql-professors-universities
description: >
  Write and verify SPARQL queries over Turtle knowledge graphs of universities
  (departments, people, courses) that return, for every qualifying professor,
  the professor's name and the university they work in — exactly one row per
  professor-university pair and exactly the requested projection variables.
  Covers professor identification via role strings, academic-rank resources,
  or person types; several person-to-university affiliation chains (direct,
  department, course fallback with NOT EXISTS guard, appointment, inverse
  containment); renamed namespaces/prefixes and name predicates; and
  graph-noise traps (lecturers, students, near-miss titles, duplicate paths,
  multi-course professors). Self-contained: includes an inline verification
  bootstrap that needs only rdflib, no external files.
---

# sparql-professors-universities

## 1. Task family (joint definition: spec.yaml + v01)

Task: *"In a Turtle knowledge graph, find all professors; for each, return
the professor's name and the name of the university they work in."* The graph
mixes universities, departments, courses, professors, near-miss staff, and
students. Deliverable: a SPARQL query saved at a fixed path (seed:
`/app/solution.sparql`). Three declared variation axes (spec.yaml); everything
else is family invariant:

| Axis | Seed (v01) | Expected variation |
|---|---|---|
| **professor_identification_semantics** | `uni:role` string; qualifying = `"Professor ..."` and `"Assistant Professor ..."`; excluded = `Lecturer`, `Student` | broader/narrower ranks (Associate, Full, Adjunct, Emeritus, ...), spelling/abbreviation variants (`Prof.`, `Prof`), professor-like near misses ("Assistant to the Professor", "Professional Staff"), rank as resource `uni:hasAcademicRank` + `uni:rankLabel`, or rank encoded as the person's rdf:type (`uni:FullProfessor`, ...) |
| **affiliation_structure_to_university** | `uni:worksAt` person→department, `uni:partOfUniversity` department→university | direct person→university link, different predicates (`employedBy`, `affiliatedWith`, `memberOf`, ...), longer/heterogeneous chains, inverse containment (department `hasMember` person), appointment resources (possibly blank nodes), or preferred `worksAt` with a `teaches`→course→department fallback |
| **graph_noise_and_result_cardinality** | 8 employed people (7 professors + 1 lecturer), 3 students, professors work at exactly 1 university, multiple courses per department | graph size, professor count, more non-professor roles, overlapping org paths, multiple departments/courses per university, duplicate professor signals. **Invariant: exactly one row per qualifying professor-university pair, exactly the requested projection variables.** |

## 2. Invariants (grounded in v01, expected to hold in every variant)

- Input is one Turtle file (seed: `/app/university_graph.ttl`) holding ontology
  + instance data in a `uni:` namespace. **A query that declares a wrong
  namespace URI or omits the prefix yields 0 rows / parse errors — copy the
  exact `@prefix` line(s) from the file** (verified: a v01-namespace query
  returns 0 rows on a renamed-namespace graph, while the file-derived prefix
  works).
- People are typed (e.g. `uni:Person`); universities are typed (e.g.
  `uni:University`); names are name-predicate literals (`uni:hasName` in seed,
  `rdfs:label` possible — bind whichever the file has).
- The professor signal is attached to the person (role string, rank resource,
  or person type). Professors are distinguished from lecturers/students/staff
  **by that signal, not by reachability**: in v01 a Lecturer and students are
  also connected to universities.
- The answer ties the person to a university via an *affiliation* relation
  ("work in"), not merely any reachable university.
- Output variables are named exactly as the instruction says (seed:
  `?professorName`, `?universityName`); one row per qualifying
  professor-university pair; duplicates collapse.

## 3. Workflow (apply in this order — do not skip the inspection step)

### Step 1 — Read the instruction, then inventory the graph
The instruction names the qualifying ranks and the affiliation semantics.

**Tool notes (learned from a real run):** the host `read` tool CANNOT open
files inside the container — `/app/...` raises `WORKSPACE_BOUNDARY`. Use
`task_shell` for everything in `/app` (e.g. `cat /app/university_graph.ttl`).
The host `read` tool is for workspace files only (task.yaml, skill files).

**Bootstrap (self-contained; needs only rdflib, which is installed):**

```bash
cat > /tmp/probe.py <<'PY'
import sys, rdflib
from collections import Counter
from rdflib.plugins.sparql import prepareQuery
g = rdflib.Graph(); g.parse(sys.argv[1], format="turtle")
loc = lambda u: str(u).rsplit('#',1)[-1].rsplit('/',1)[-1]
print("triples:", len(g))
print("prefixes:", [l.strip() for l in open(sys.argv[1]) if l.strip().startswith("@prefix")])
print("types:", {loc(o): n for o, n in Counter(o for s,p,o in g if p == rdflib.RDF.type).items()})
print("predicates:", {loc(p): n for p, n in Counter(p for s,p,o in g).items()})
for name in ("role", "rankLabel", "label"):
    vals = Counter(str(o) for s,p,o in g if loc(p) == name)
    if vals: print(f"{name}:", dict(vals))
if len(sys.argv) > 2:
    rows = sorted(tuple(str(x) for x in r) for r in g.query(prepareQuery(open(sys.argv[2]).read())))
    print(f"query rows ({len(rows)}):")
    for r in rows: print("  ", r)
PY
python3 /tmp/probe.py /app/university_graph.ttl            # inventory only
python3 /tmp/probe.py /app/university_graph.ttl /app/solution.sparql   # + run your query
```

If the skill package is mounted in the container (e.g. `/skill/` contains `SKILL.md`/`scripts/`), you may copy and use the richer helper `scripts/inspect_graph.py` instead — it also prints per-person university reachability and incoming links. Otherwise the snippet above is sufficient; it prints the @prefix lines
(use them verbatim in the query), class counts, predicates, and all
role/rankLabel/label values.

Use the inventory to answer: (1) which role/rank/type values are professors
(§5); (2) which predicates form the person→university chain(s) (§6); (3) who
is caught by a naive `teaches`-based path (§7).

### Step 2 — Choose the professor filter (§5)
### Step 3 — Choose the affiliation pattern(s) (§6)
### Step 4 — Assemble the query
Canonical shape for the seed family shape (role strings + worksAt chain):

```sparql
PREFIX uni: <http://university.org/ontology#>   # copy from the file's @prefix
SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?professor a uni:Person ;
             uni:hasName ?professorName ;
             uni:role ?role ;
             uni:worksAt ?department .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
}
```

Rules: declare the prefix (copy the URI!); project **exactly** the requested
variables — **copy their names from the instruction; the seed's
`?professorName`/`?universityName` are examples, not invariants**;
`SELECT DISTINCT`; filter the professor signal
**case-insensitively**; bind names with the file's name predicate; follow the
affiliation chain. **Fail-fast rule:** if this seed-shaped query returns 0
rows or a suspicious count on your graph, the variant changed shape — go back
to the inventory and pick from §4's template map; do not blindly tweak the
seed query.

### Step 5 — Verify locally, adversarially
Run the bootstrap with your query; compare rows against the expected set
(instruction + §7 counting method). **Adversarial fixture discipline
(mandatory for any "verified" claim):** a probe that passes on a degenerate
input certifies nothing — the fixture must make candidate encodings disagree.
For affiliation patterns, build a minimal fixture with at least:

1. **≥ 2 universities**, plus a worksAt-professor who teaches a course housed
   in the *other* university — exposes an unguarded fallback firing (extra
   row).
2. A professor with **no worksAt** whose courses reach a university —
   confirms the fallback actually fires.
3. A fallback professor with **≥ 2 courses in the same university** —
   confirms `DISTINCT` collapses same-pair multiplicity.
4. A heterogeneous graph containing all observed shapes **plus a trap person
   with two affiliations pointing at different universities** (e.g. current +
   emeritus) — plain UNION keeps both pairs, guards drop one (verified); the
   instruction decides whether both rows are wanted.

On this fixture the bare UNION and the guarded UNION *must* disagree on case 1
(verified: bare emits the extra row). If two encodings cannot be made to
disagree, the result is indeterminate, not support.

## 4. Quick template selection map

Grep/inspect first, then pick the row(s). The skeleton column shows the
discriminating part; keep `PREFIX` (from file), `SELECT DISTINCT` (exact
projection), the professor filter, and the name-binding predicate from the
inventory.

| Observed in inventory | Query skeleton (inside WHERE) |
|---|---|
| `role` strings like "Professor of ..." / "Assistant Professor ..." | `?p uni:role ?role . FILTER(CONTAINS(LCASE(?role), "professor"))` — see §5 for abbreviations/allowlists |
| No role strings; people typed `FullProfessor`/`AssistantProfessor`/... | `?p a ?type . FILTER(CONTAINS(LCASE(STR(?type)), "professor"))` or allowlist `?type IN (uni:FullProfessor, uni:AssistantProfessor)` (verified 2/2) |
| `hasAcademicRank` → rank node with `rankLabel` | join the rank resource, filter `LCASE(?rankLabel)` (verified) |
| `worksAt` points straight at a University node | `?p uni:worksAt ?u . ?u uni:hasName ?un .` (1 hop) |
| `worksAt` → Department with `partOfUniversity` → University | canonical chain (verified on v01) |
| some people lack `worksAt` but `teaches` courses (`isTaughtIn` → dept) | guarded UNION with `FILTER NOT EXISTS { ?p uni:worksAt ?anyDept . }` (§6) |
| department points back at person (`hasMember`/`contains`) | `?d uni:hasMember ?p . ?d uni:partOfUniversity ?u .` (verified) |
| appointment/reified resources (blank nodes bind fine) | `?p uni:hasAppointment ?a . ?a uni:atUniversity ?u . ?u uni:hasName ?un .` — resource points **directly** at the university (verified) |
| appointment via position (two hops) | `?p uni:hasAppointment ?a . ?a uni:positionIn ?d . ?d uni:partOfUniversity ?u . ?u uni:hasName ?un .` (verified) |
| longer containment chains (faculty→school→university, any depth) | `?p uni:worksAt ?org . ?org uni:partOfUniversity+ ?u . ?u uni:hasName ?un .` — property path `+` = one-or-more hops (verified at depth 2; identical to seed at depth 1; **covers depth ≥ 1 only — if some persons worksAt a University directly, UNION the direct branch `?p uni:worksAt ?u .` with the `+` branch**, verified). rdflib supports `/`, `|`, `^`, `+`, `*`; negated property sets `!` are NOT supported. |
| heterogeneous shapes (different people use different predicates) | `UNION` over the observed branch skeletons + `SELECT DISTINCT` — **no NOT EXISTS guards** (guards are for per-person preference, not per-graph shape diversity; verified: guards on heterogeneous branches silently drop pairs of multi-relation people) |
| name predicate is `rdfs:label`/other | bind names with that predicate (`?u rdfs:label ?universityName`) (verified) |

### 4.1 Complete verified templates — copy, adapt, verify

Every template below is a **complete query** (not a fragment): adapt the
`PREFIX` (from the file), the predicates/name predicate (from the inventory),
and the projection variable names (from the instruction), then verify with the
bootstrap. Verified tags cite the fixtures in §9.

**T1 — seed canonical (role strings, `worksAt` → department → university).**
Verified: v01, 7/7 (the `teaches` variant gives the wrong 8).

```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?professorName ?universityName WHERE {
  ?p a uni:Person ; uni:hasName ?professorName ; uni:role ?role ; uni:worksAt ?d .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  ?d uni:partOfUniversity ?u . ?u uni:hasName ?universityName .
}
```

**T2 — guarded fallback (worksAt preferred; teaches route only for
worksAt-less people).** Verified: v01 7/7; adversarial fixture 3/3; bare UNION
would give 8/4 (wrong).

```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?professorName ?universityName WHERE {
  ?p a uni:Person ; uni:hasName ?professorName ; uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  { ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u . }
  UNION
  { ?p uni:teaches ?c . ?c uni:isTaughtIn ?d . ?d uni:partOfUniversity ?u .
    FILTER NOT EXISTS { ?p uni:worksAt ?anyDept . } }
  ?u uni:hasName ?universityName .
}
```

**T3 — appointment resources** (blank nodes bind fine as `?a`). Verified:
direct 1/1, via-position 1/1, both encodings UNIONed 2/2; the seed skeleton
and `?a uni:partOfUniversity ?u` both return 0 rows on such graphs.

```sparql
# (a) resource points directly at the university:
?p uni:hasAppointment ?a . ?a uni:atUniversity ?u . ?u uni:hasName ?universityName .
# (b) resource points at a department (two hops):
?p uni:hasAppointment ?a . ?a uni:positionIn ?d . ?d uni:partOfUniversity ?u . ?u uni:hasName ?universityName .
# if BOTH encodings occur in one graph, put (a) and (b) as UNION branches
# (add the professor filter to the shared prefix: ?p a uni:Person ; uni:hasName
#  ?professorName ; uni:role ?role . FILTER(...) before the branches).
```

**T4 — heterogeneous shapes (different people use different predicates).**
Verified: 5/5 on the mixed fixture, including a trap person with two
affiliations at different universities (two rows — an instruction decision).
No NOT EXISTS guards here (see §6).

```sparql
PREFIX uni: <http://university.org/ontology#>
SELECT DISTINCT ?professorName ?universityName WHERE {
  ?p a uni:Person ; uni:hasName ?professorName ; uni:role ?role .
  FILTER(CONTAINS(LCASE(?role), "professor"))
  { ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u . }
  UNION
  { ?p uni:employedBy ?d . ?d uni:partOfUniversity ?u . }
  UNION
  { ?d uni:hasMember ?p . ?d uni:partOfUniversity ?u . }
  ?u uni:hasName ?universityName .
}
```

**T5 — depth-agnostic containment (faculty/school between department and
university).** Verified at depth 2 and identical to T1 at depth 1 (v01 7/7).
Replace T1's last two triples with: `?p uni:worksAt ?org . ?org uni:partOfUniversity+ ?u . ?u uni:hasName ?universityName .`
**`+` covers depth ≥ 1 only:** if the inventory also shows persons whose
`worksAt` points **directly** at a University node (0 hops), they silently
drop out (verified: 1 row instead of 2). For mixed depths, UNION the direct
form with the `+` branch: `{ ?p uni:worksAt ?u . } UNION { ?p uni:worksAt ?org . ?org uni:partOfUniversity+ ?u . }`
— `SELECT DISTINCT` keeps it safe (verified 2/2).

**T6 — rank as resource** (replace T1's role triples+filter):
`?p uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?rankLabel . FILTER(CONTAINS(LCASE(?rankLabel), "professor"))`
— verified alone and composed with appointment chains (X1/X2: 1/1 each).

**T7 — rank as person type** (replaces BOTH T1's `a uni:Person` type triple
and the role triples+filter — remove `a uni:Person`; keep it only if the
inventory shows rank-typed persons are also typed Person, otherwise the query
returns **0 rows**, verified on the type-only fixture):
`?p a ?type ; uni:hasName ?professorName . FILTER(CONTAINS(LCASE(STR(?type)), "professor"))` or the allowlist
`FILTER(?type IN (uni:FullProfessor, uni:AssistantProfessor))` — verified 2/2.

**T8 — optional affiliation (only if the instruction asks to include
professors with no university).** Replace the chain triples with
`OPTIONAL { ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u . ?u uni:hasName ?universityName . }` —
verified: an unaffiliated professor is then included with the university name
unbound (renders as None in rdflib rows). The seed's instruction rules this
case out; do not use OPTIONAL unless the instruction requires it, because
unbound cells may mismatch a grader that expects only complete pairs.

## 5. Professor identification (axis 1) — decision procedure

Enumerate the values first (bootstrap output). Then:

- **Default (seed shape, free-form role titles):** case-insensitive substring
  — `FILTER(CONTAINS(LCASE(?role), "professor"))`. Verified on v01: matches
  all 7 professors, rejects "Lecturer" and "Student". **Case-sensitivity is
  fatal**: a plain `CONTAINS(?role, "professor")` returns **0 rows** on v01
  (roles start with capital "Professor"). `regex(?role, "professor", "i")` is
  equivalent (verified).
- **Abbreviations (`Prof.`, `Prof`):** word-boundary regex with **both** boundaries — `FILTER regex(?role, "(^|[^A-Za-z])prof(?:essor)?[.]?(?:[^A-Za-z]|$)", "i")` (verified: admits Prof., Prof, Professor, Assistant/Adjunct/Full Professor, Professor Emeritus; rejects Professorial Assistant, Professorship Coordinator, Professional Staff — the leading-boundary-only version admits all three impostors).
- **Regex escapes — two decoding layers, plus rdflib's decoder quirk (all byte-verified):** SPARQL decodes one layer of string escapes (legal: `\t \b \n \r \f \" \' \\ \uXXXX \UXXXXXXXX`; anything else, e.g. `\.`, is an **illegal escape → parse error**, verified), then the regex engine reads what remains. **In the .sparql file, `\X` = SPARQL control character; `\\X` = regex metacharacter `\X`** — so a regex escaped dot needs file bytes `\\.` (SPARQL collapses `\\`→`\`, regex receives `\.`; verified at byte level). **rdflib 6.1.1 quirk (genuine — mechanism: its `decodeUnicodeEscape` replaces the single-character escapes `\b \t \n \r \f` BEFORE collapsing `\\`→`\`):** file bytes `\\b`/`\\t`/`\\n`/`\\r`/`\\f` become backslash + control character, NOT the regex metacharacter. Verified: `\\bprof` → 0 rows where a word boundary should match; meanwhile `\\.` (literal dot), `\\d` (digit matched "Prof2"), `\\s` (whitespace matched "Professor of CS") all work as regex metacharacters. Conclusion: regex word boundaries must use character classes `(^|[^A-Za-z])` / `(?:[^A-Za-z]|$)` and literal dots `[.]` — the portable, verified choices. **Regex claim protocol (standing):** (a) create the .sparql file with a **quoted heredoc** (no Python/shell escape processing), (b) audit bytes with `od -c FILE` (confirm the intended backslash count inside the quotes), (c) execute via `prepareQuery` from that file, and (d) make sure every projected variable is bound in the WHERE (an unbound SELECT variable silently yields 0 rows). A regex claim without this byte audit is not "verified".
- **Professor-like near misses** ("Assistant to the Professor", "Professional
  Staff"): no pure string rule can exclude a role containing the word
  "Professor" while keeping real ones (verified: substring, word-boundary, and
  `STRSTARTS` rules all admit some impostor). Resolution: read the
  instruction; if the role set is enumerable use an **allowlist** —
  `FILTER(?role IN (...))` (verified exact) — or explicit exclusions
  (`&& !CONTAINS(LCASE(?role), "assistant to")`). The general rule: "any role
  whose title denotes an academic rank containing *professor* as the rank
  word, per the instruction".
- **Rank as resource:** `?p uni:hasAcademicRank ?rank . ?rank uni:rankLabel ?rankLabel .`
  then filter `LCASE(?rankLabel)` (verified pattern). Narrower-rank variants
  (only Full Professors) → exclude `"assistant"`/`"associate"` or allowlist
  the instruction-named ranks.
- **Rank as person type (no role strings):** `?p a ?type` and filter the type
  IRI/local name (verified 2/2 on a FullProfessor/AssistantProfessor/Lecturer
  fixture via both `CONTAINS(LCASE(STR(?type)), "professor")` and an
  allowlist). Combine with the affiliation chain as usual.
- **Instruction beats pattern-matching:** whenever the instruction names the
  qualifying ranks explicitly, prefer a filter that implements exactly that
  definition (allowlist or refined regex), and confirm each enumerated value
  is classified as the instruction implies.

## 6. Affiliation structure (axis 2) — chain patterns

Seed chain: **person `uni:worksAt` department, department
`uni:partOfUniversity` university** (verified: 7 professors → 7 rows).

**Fallback semantics — "preferred, else fallback" is a per-person
conditional.** The variant is: use `worksAt` when the person has it; use the
teaching-course route only for persons who lack `worksAt`. A bare `UNION`
does NOT express this: on v01 it fires the teaches branch for every teaching
professor and leaks (Felix Wagner, NTUA) via AI101 → **8 rows** (verified).
The fallback branch must carry a negated-existence guard on the preferred
relation, with a **fresh variable** inside the guard (never one correlated
with an outer binding):

```sparql
{ ?p uni:worksAt ?d . ?d uni:partOfUniversity ?u . }
UNION
{ ?p uni:teaches ?c . ?c uni:isTaughtIn ?d . ?d uni:partOfUniversity ?u .
  FILTER NOT EXISTS { ?p uni:worksAt ?anyDept . } }
```

`FILTER NOT EXISTS` works in rdflib 6.1.1 (verified). Prefer it over `MINUS`
(works here too, but its left-associativity subtlety buys nothing). On v01 the
guarded branch contributes 0 rows (total 7); on a fixture with a worksAt-less
professor the fallback fires (verified 3/3). Equivalent alternative:
`OPTIONAL` both routes + `BIND(COALESCE(?wu, ?cu) AS ?u)` with the same guard
on the fallback OPTIONAL (verified 7/7 on v01 and 3/3 on the adversarial
fixture). Heterogeneous graphs also need `SELECT DISTINCT`: DISTINCT
collapses same-pair duplicates (multi-course fallback) only — it cannot fix
cross-university contamination, which is the guard's job.

**Chain discipline (top-line rule):** the last hop of the chain must
terminate at a node typed University (or otherwise identifiable as one), and
each intermediate's outgoing predicate must come from the inventory — never
assume every intermediate uses `partOfUniversity`. Verified failure modes on
an appointment graph: the seed skeleton (`worksAt`→`partOfUniversity`) and
`?a uni:partOfUniversity ?u` both return **0 rows**; the working skeletons are
the two appointment rows in §4: resource→`atUniversity`→university (direct)
or resource→`positionIn`→department→`partOfUniversity`→university (two
hops, verified).

**Other shapes (all verified):** direct person→university (1 hop); inverse
containment `?d uni:hasMember ?p`; longer chains — `?org uni:partOfUniversity+ ?u`
covers any depth when the containment predicate repeats (verified at depth 2;
identical to the seed at depth 1). **How to inspect a chain you have never
seen:** follow a person's outgoing predicates until you hit a node typed
University; note which predicate sequence the instruction describes as
"works/affiliated", then encode exactly that sequence (UNION if multiple).

**Heterogeneity vs fallback — two different UNION uses (do not confuse):**
- *Per-person preference* (worksAt preferred over teaches): the fallback
  branch carries `FILTER NOT EXISTS` on the preferred relation (above).
- *Per-graph shape diversity* (different people use `worksAt` / `employedBy` /
  inverse `hasMember`): plain `UNION` over the observed branch skeletons +
  `SELECT DISTINCT`. **Do NOT add NOT EXISTS guards here** — verified: on a
  graph where one person has both `worksAt` (dept A) and `employedBy` (dept
  B), the guarded version silently drops the B pair while plain UNION keeps
  all pairs. The instruction decides whether multi-affiliation people yield
  multiple rows (see §7 counting rule).

**Professors with no resolvable affiliation** (neither worksAt nor
teaches-path nor any chain): they are necessarily omitted from the output —
there is no university name to emit (verified: an "orphan" professor does not
appear, and the instruction's assumptions normally rule this out). Don't try
to invent a university for them. Only if the **instruction explicitly asks to
include professors without a university** should you use the OPTIONAL form of
the affiliation chain (template T8 in §4.1) — with the caveat that the
unbound university name renders as None in rdflib result rows.

## 7. Cardinality and traps (axis 3) — verified failures on v01

- **`teaches`-path trap:** naive `teaches → isTaughtIn → partOfUniversity`
  yields **8 rows** on v01 (Felix Wagner teaches AI101 in another
  university's department). "Works at" semantics require worksAt; the same
  8-row failure reappears with a bare UNION fallback (verified). Guard the
  fallback (`NOT EXISTS` on worksAt) — never OR paths globally.
- **Students look connected:** students are enrolled in courses → departments
  → universities but lack the professor signal; the filter excludes them.
  Never identify professors by "has a university" — everyone does.
- **Case sensitivity:** capital-P "Professor" → `LCASE` or regex `i` flag
  (verified: 0 rows otherwise).
- **Missing DISTINCT:** safe on the seed worksAt path (7 rows without it) but
  mandatory for variants with multiple departments/courses/paths per professor
  (verified: fallback shapes need it to collapse same-pair duplicates).
- **Wrong namespace/prefix:** declaring a namespace URI that is not in the
  file returns **0 rows** (verified on a renamed-namespace fixture). Always
  copy the `@prefix` line from the TTL; if the prefix label differs (e.g.
  `uo:`), use that label in the query.
- **Extra variables:** project only the instruction-named variables.
- **Hardcoding answers:** never hardcode names/universities; bind via the name
  predicate (values may contain non-ASCII chars).
- **Missing prefix:** parse error `Unknown namespace prefix` (verified).

**Counting the expected answer:** one row per qualifying **(professor,
university) pair**, not per professor. A professor affirmed to two
universities legitimately yields two rows; do not "fix" such an answer back
down to one row unless the instruction states a single-university assumption
(the seed does — v01: 7 professors, each with one university → 7 expected
rows). When a person is reachable via several paths, `DISTINCT` collapses
same-pair duplicates only; different pairs remain distinct rows.

## 8. Verification procedure (use every time)

1. Inventory the graph (bootstrap; task_shell, not the host read tool).
2. Build the query from §4's map using the file's actual prefixes,
   predicates, name predicate, and the instruction's semantics.
3. Run the bootstrap with your query; compare count and each
   (professor, university) pair against the instruction's examples and the
   computed expected set.
4. Re-run with a deliberately *wrong* filter (case-sensitive, teaches-based,
   or wrong-namespace) to confirm your query does the discriminating work and
   the traps change results. If two filters give identical output, the graph
   does not exercise the distinction — keep the safer one. For any
   regex-based filter, use §5's standing byte protocol (quoted heredoc →
   `od -c` audit → execute from the file) — harness text layers can silently
   change what the engine actually received.
5. Confirm exact output-variable names and save path from the instruction
   (`/app/solution.sparql` for the seed).

Environment facts: the verdict runs in a fresh container with Python 3 and
rdflib (v6.1.1 verified); comparison is pytest-based on the query results, so
correctness = exact expected row set (string values of the name literals).

## 9. Evidence log (what is verified where)

- **Direct v01 evidence:** 129 triples, 11 persons, 9 universities, 11
  departments, 9 courses; worksAt→partOfUniversity gives the correct 7 rows;
  teaches-path gives wrong 8 rows; bare-UNION fallback gives wrong 8 rows;
  case-sensitive filter gives 0 rows; `regex(..., "i")` ≡ `LCASE`+`CONTAINS`;
  no-DISTINCT worksAt path gives 7 rows; missing prefix →
  `Unknown namespace prefix`.
- **Negative finding (first draft, retracted):** the bare UNION fallback was
  briefly labeled "verified synthetically" from a one-university fixture where
  DISTINCT masked the leak; that fixture could not discriminate encodings, so
  the label was false evidence. Corrected by the adversarial fixture.
- **Synthetic probes (fixtures built for this skill, rdflib):** guarded
  worksAt-with-teaches-fallback UNION — 7/7 on v01 and 3/3 on the 3-case
  adversarial fixture; OPTIONAL + `COALESCE` guarded — 7/7 on v01 and 3/3 on
  the fixture; guarded-via-`MINUS` — 3/3; bare UNION — 4/4-wrong on the
  fixture (3 correct + 1 leaked); rank-as-resource (`hasAcademicRank`/
  `rankLabel`); rank-as-type (`?p a ?type` filter on type IRI, and allowlist)
  — 2/2 excluding a Lecturer-typed person; direct worksAt→university;
  inverse `hasMember`; **appointment resources — both encodings**
  (`hasAppointment`→`atUniversity`→university and
  `hasAppointment`→`positionIn`→department→`partOfUniversity`→university),
  blank nodes bind fine, and the wrong skeletons (`worksAt`→`partOfUniversity`
  or `?a partOfUniversity ?u` on the appointment graph) return 0 rows;
  **longer chains — `partOfUniversity+` property path returns the correct row
  at depth 2** (rdflib supports `/`, `|`, `^`, `+`, `*`; negated property
  sets `!` unsupported); **heterogeneous shapes — plain UNION over worksAt /
  employedBy / hasMember branches keeps all 5 pairs including a trap person
  with two affiliations (Alpha+Beta), while adding NOT EXISTS guards drops
  the multi-relation person's second pair (4 rows) — guards belong to
  per-person preference, not shape diversity**; renamed
  namespace+prefix+`rdfs:label` fixture — v01-hardcoded query 0 rows,
  file-derived query 1 row (correct); "orphan" professor without affiliation
  omitted; allowlist `IN(...)`; **escape layers at byte level (quoted heredoc
  + `od -c` byte audit + execute from file): a single `\.` in the file fails
  SPARQL parsing (illegal escape per the SPARQL 1.1 grammar — legal: \t \b
  \n \r \f \" \' \\ \u \U); `\\.` parses and the regex receives `\.`
  (matches "Prof."). rdflib 6.1.1 decoder quirk with mechanism: its
  `decodeUnicodeEscape` replaces the single-character escapes `\b \t \n \r
  \f` BEFORE collapsing `\\`→`\`, so file `\\b` → backslash + backspace and
  `\\t`/`\\n`/`\\r`/`\\f` are likewise mangled (0 rows where `\b`/`\n`
  should match), while `\\.`, `\\d`, `\\s` work as regex metacharacters
  (digit matched "Prof2", whitespace matched "Professor of CS") — use
  `(^|[^A-Za-z])` / `(?:[^A-Za-z]|$)` and `[.]` for portability**;
  **T7 scope check: keeping `a uni:Person` while adding `?p a ?type` returns
  0 rows on the type-only fixture; dropping `a uni:Person` returns 2/2;
  T5 mixed-depth check: `partOfUniversity+` alone drops a person whose
  `worksAt` points directly at a University (1/2); UNIONing the direct branch
  recovers 2/2**; abbreviation regex with both
  boundaries admits Prof./Professor/Assistant/Adjunct/Full/Emeritus and
  rejects Professorial Assistant, Professorship Coordinator, Professional
  Staff (the leading-boundary-only version admits all three impostors);
  near-miss ambiguity ("Assistant to the Professor", "Professional Staff");
  bootstrap traversal of blank-node appointment resources and per-person
  incoming-links inventory (inspect_graph.py); **complete-query templates**:
  full guarded-fallback query (T2) 3/3 on the adversarial fixture and 7/7 on
  v01; `rankLabel` filter composed with appointment-direct 1/1 and
  appointment-via-position 1/1, and both appointment encodings in one UNION
  2/2 (X1–X3); OPTIONAL-affiliation probe — an unaffiliated professor appears
  with the university name unbound (None) under OPTIONAL and is omitted
  otherwise (Y1/Y2).
- **Reasoned extrapolation (not locally exercisable):** arbitrary predicate
  names and name-predicate spellings beyond the tested ones, grader
  comparison semantics, graph sizes beyond the tested scale. Mitigation is the
  workflow itself: inventory first, copy prefixes, encode the instruction's
  semantics, verify adversarially. **Coverage checklist discipline:** every
  shape named in spec.yaml's axes should be either verified or explicitly
  labeled with the reason it cannot be probed locally — "reasoned
  extrapolation" is a shrinking region, not a resting place. For any unseen
  variant, rerun §3–§8 rather than assuming the seed shapes.

## 10. Package contents

- `SKILL.md` — this skill (self-contained; §3 embeds a bootstrap that needs
  only rdflib, so it works even if no script file reaches the container).
- `scripts/inspect_graph.py` — optional richer inventory helper
  (`python3 inspect_graph.py graph.ttl [solution.sparql]`): per-person
  university reachability over URIRefs *and* blank nodes, per-person incoming
  links (inverse containment), role/rankLabel inventories. If the package is
  mounted in the container (check for `SKILL.md`/`scripts/` under `/skill` or
  a similar path), copy the script into `/app` first; otherwise the §3
  bootstrap is sufficient.