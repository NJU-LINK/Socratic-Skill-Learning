---
name: sparql-professors-universities
description: >-
  Given a Turtle knowledge graph describing universities, departments, employees,
  students and courses, produce a SPARQL query that returns exactly two projected
  variables -- ?professorName and ?universityName -- with one row per qualifying
  professor-university pair. The skill covers (a) identifying professors by
  case-insensitive rank-token matching over role strings and/or academic-rank
  resources (excluding near-miss roles like lecturers, students, staff),
  (b) resolving each person to their university through worksAt departments,
  partOfUniversity containment chains of any depth, inverse containment,
  direct university affiliation, or a guarded teaching-course fallback when the
  preferred relation is absent, and (c) enforcing pair-level cardinality by
  grouping on person/university IRIs before decorating with human-readable
  names, so graph noise never creates duplicate or bogus rows nor silently
  collapses distinct same-named professors. Ships an anchor-fingerprint gate
  that mechanically decides between copying the validated v01 reference query
  and adapting the family template, plus an rdflib-based verification harness
  that enforces the exact projection, multiset pair cardinality, and
  near-miss exclusions.
---

# Skill: sparql-professors-universities

## Package layout (exact paths inside the task container)

The skill package is mounted read-only with its **contents at `/skill` directly**
(there is NO `/skill/sparql-professors-universities/` subdirectory):

```
/skill/SKILL.md                              this document
/skill/scripts/verify.py                     query verification harness (rdflib)
/skill/scripts/fingerprint_v01.py            anchor fingerprint gate (copy-vs-adapt)
/skill/scripts/drill_fail_branch.py          end-to-end rehearsal of the dispatch FAIL branch
/skill/scripts/regression.py                 package-level regression: all layers in one entry point
/skill/templates/query_template.sparql       family-general query template
/skill/references/v01_solution.sparql        EXACT validated anchor query (copy only on fingerprint match)
/skill/references/v01_expected.txt           EXACT expected rows for the anchor (use with verify.py)
/skill/references/evidence.md                experiment log (E1-E8, G1-G4, D1/D2) + decision records
```

TOOL BOUNDARY: the host `read`/`write`/`grep` tools reach ONLY the author
workspace. Anything under `/app` or `/skill` lives in the isolated task
container — access it with `task_shell` (`cat`, `grep`, `cp`, `python3`),
never with the host `read`/`grep` tools (they return WORKSPACE_BOUNDARY
errors and waste a call).

## When to use

The task text (family `sparql-professors-universities`) provides a Turtle file at
`/app/university_graph.ttl` (ontology + instance data) and asks for a SPARQL query
that retrieves "all professor names" together with "the name of the university they
work in", exact projection variables `?professorName ?universityName`, one row per
professor–university pair. The answer must be saved as `/app/solution.sparql`.

## Ground truth about the anchor member (v01)

Direct evidence from `train/v01` (verbatim structure, verified by loading the graph
and running the query with rdflib 6.1.1):

- Universities: `uni:X a uni:University ; uni:hasName "..." ; uni:locatedInCountry ".."`.
- Departments: `uni:X a uni:Department ; uni:partOfUniversity uni:Y`.
- Persons: `uni:X a uni:Person ; uni:hasName "..." ; uni:role "..." ; uni:teaches ... ; uni:worksAt uni:dept`.
- Roles are **literal strings**: qualifying `"Professor of ..."` and
  `"Assistant Professor of ..."`; non-qualifying `"Lecturer"`, `"Student"`.
- Expected result: **7 rows** (Alex Morgan, Thomas Berger → NTUA;
  Felix Wagner → Instituto Superior Técnico; Martin Keller → NKUA;
  John Smith → MIT; Marie Dubois → Sorbonne University; Stefan Mueller → LMU).
- Trap planted in the seed: `Felix Wagner` `uni:teaches` `Math101` (IST) **and**
  `AI101` (NTUA CS) while `worksAt` IST — a professor teaching at another
  university. Any unconditional course-based path fabricates `Felix → NTUA`.
- The v01 turtle contains **no schema triples** (`grep -E "rdfs:|owl:"` finds
  nothing); the "ontology" is only instance usage of `uni:` predicates.

## Family invariants (hold across all variants per spec.yaml + v01)

1. Output projection is exactly `?professorName ?universityName` (v01 instruction;
   treat as invariant).
2. One row **per qualifying (person, university) pair** — pair granularity, not
   person granularity (spec axis 3).
3. Professors are distinguished from near-misses by some *rank signal* that must
   be matched on a **token**, case-insensitively, never by whole-string equality.
4. The university is reachable from the person through some affiliation/containment
   structure the query must follow (axis 2); the returned name is the value of the
   university's name predicate, and intermediate organizations must not leak into
   results.

## Variation dimensions (spec.yaml) and how to handle them

### Axis 1 — professor identification semantics

Procedure: **discover the rank-carrying predicates from the variant data**, then
decide the qualifying token set.

1. `grep -E "rdfs:|owl:" /app/*.ttl` for schema declarations; otherwise enumerate
   predicates used on `a uni:Person` subjects (or grep for `"Professor`).
2. Bind **every** candidate rank signal with OPTIONAL patterns and test with a
   BOUND-guarded case-insensitive token filter:
   ```sparql
   OPTIONAL { ?person uni:role ?roleStr }
   OPTIONAL { ?person uni:hasAcademicRank ?rankRes . ?rankRes uni:rankLabel ?rankLabel }
   FILTER( (BOUND(?roleStr)   && CONTAINS(LCASE(?roleStr),   "professor")) ||
           (BOUND(?rankLabel) && CONTAINS(LCASE(?rankLabel), "professor")) )
   ```
   Why BOUND-guarded: `CONTAINS` on an unbound variable is a filter **error**. In
   rdflib, `false || error` and `error && ...` silently drop the row (and can kill
   the whole result), while other engines (e.g. Virtuoso, known for strictness) may
   hard-fail the query. Verified experimentally (see evidence E5a–E5c).
3. **Decision point — qualifying token set.** Seed: `{"professor"}` (covers
   "Professor of X" and "Assistant Professor of X", rejects "Lecturer"/"Student").
   Spec-declared variation: broaden/narrow ranks (associate, adjunct, visiting,
   emeritus), abbreviations ("Prof."), rank resources (`uni:hasAcademicRank` +
   `uni:rankLabel`). Whatever the set, match *any token in the set*,
   case-insensitively — and trust the token to survive typo'd surrounding words
   (v01 ships "Professor of History of Scienceand Technology").
4. Mistakes that fail: exact equality on a whole title (`?role = "Professor"` drops
   Assistant Professors); case-sensitive matching (roles are capitalized);
   whole-string regexes; hardcoding only `uni:role` when the variant uses
   `hasAcademicRank` (returns zero rows silently — see evidence E6).

### Axis 2 — affiliation structure to university

Core shape (validated template):

```sparql
?person uni:worksAt ?unit .
?unit  uni:partOfUniversity* ?university .
?university a uni:University .
```

`*` **plus terminal type anchor** is the family-general containment pattern:

- **Direct affiliation** (`worksAt` straight onto a university): `*` binds the unit
  itself (zero hops); the anchor keeps it because it IS a University. Bare `+`
  silently loses these professors (evidence D1/D2).
- **Seed depth** (dept → uni, one hop): `+` and `*` behave identically.
- **Deep/heterogeneous chains** (dept → faculty → uni, with named intermediates):
  `*`/`+` bind every ancestor; the `a uni:University` anchor prunes intermediates,
  so "School of Science" rows never appear (evidence G1–G3). **Never use a bare
  property path without the anchor** — with `*` it also emits the unit itself.
- **Inverse containment** (e.g. `uni:hasDepartment` running university→department):
  either `?university uni:hasDepartment ?unit` or `?unit ^uni:hasDepartment
  ?university`; decide the direction by reading the data, then anchor the terminal
  exactly as above (evidence G4).
- **Appointment resources** (person → appointment → department/chair): add the
  appointment hops as a pattern; same `*` + anchor discipline at the end.
- **Course fallback** when `worksAt` is absent: guarded UNION only:
  ```sparql
  { ?person uni:worksAt ?unit . ?unit uni:partOfUniversity* ?university . ?university a uni:University . }
  UNION
  { FILTER NOT EXISTS { ?person uni:worksAt ?anyUnit }
    ?person uni:teaches ?course . ?course uni:isTaughtIn ?unit .
    ?unit uni:partOfUniversity* ?university . ?university a uni:University . }
  ```
  **Never a plain UNION of the two paths**: it doubles every professor who has both
  `worksAt` and `teaches` (14 rows vs 8 in the mutation test) and fabricates bogus
  universities from cross-institutional teaching (Felix → NTUA) (evidence E1a/E1b).
  Semantic decision (documented, tested): when the fallback fires and courses span
  several universities, the pair-reading of the invariant yields one row per
  reachable university (Felix → IST **and** Felix → NTUA in the no-worksAt variant).
  If the task instead demands exactly one university per professor, the data must
  provide a primary signal to pick one; the seed data does not, so pair rows are
  the defensible default.

### Axis 3 — graph noise and result cardinality

Order of operations matters. **Group by IRI pair first, keep every projected
literal inside the grouped subquery:**

```sparql
{ SELECT ?person ?university
         (MIN(?pname) AS ?professorName)
         (MIN(?uname)  AS ?universityName)
  WHERE { ...rank filter... ...affiliation path...
          ?person uni:hasName ?pname .
          ?university uni:hasName ?uname . }
  GROUP BY ?person ?university }
```

Why GROUP BY on IRIs rather than `SELECT DISTINCT` on names:

- **Two distinct professors with the same name at one university** must yield two
  rows (pair invariant). `SELECT DISTINCT ?professorName ?universityName` at the
  top collapses them to one (7 vs 8 rows, evidence E4a/E4b). Grouping by `?person ?university`
  keeps both groups.
- **Multi-valued names** (multi-language labels, synonyms): a DISTINCT-over-IRIs
  subquery still re-expands rows at the name join (8 rows for a two-name
  professor — evidence E3). `GROUP BY ?person ?university` + `MIN(?pname)` pins
  exactly one row per pair regardless of name multiplicity (evidence E7).
- Same logic applies to university names, symmetrically: **every projected
  literal lives inside the IRI-grouped subquery** (`MIN(?pname) AS
  ?professorName`, `MIN(?uname) AS ?universityName`), and *nothing decorative
  joins after the grouping*. A second `hasName` literal on a university
  re-expands pair rows post-dedupe exactly like person names do (evidence E8:
  8 rows in the two-name-MIT mutation with an outer decoration; 7 with the
  symmetric template).
- **Name selection is exclusive, rank identification is disjunctive — do not
  unify them.** Rank signals may be many (role string, rankLabel, ...) and any
  may qualify a person. But `?pname`/`?uname` must be bound ONLY by the
  variant's primary, expected-output name predicates (the ones the task
  instruction names). `MIN(?x)` is lexicographic, so folding alias predicates
  (`uni:hasAlternateName`, `skos:altLabel`, ...) into the same variable
  systematically emits the alias (`"O. Morgan" < "Alex Morgan"` — see
  evidence E7 note). If the variant is not single-valued even on the primary
  predicate, MIN still picks one deterministic spelling; SAMPLE is
  nondeterministic, so prefer MIN.
- The rated anchor answer (/app/solution.sparql) may legitimately stay simpler
  than the family template: v01 data is single-valued, the simple query is
  validated and minimal, and grading solvency of the deliverable outweighs
  internal consistency with the template (decision recorded in evidence.md).

## Solve procedure (follow in order)

**Step 0 — fingerprint gate (anchor detection, run FIRST).** Decide copy-vs-adapt
mechanically, never by memory (all container work via `task_shell`; the host
read/grep tools cannot see /app or /skill):

```bash
python3 /skill/scripts/fingerprint_v01.py --graph /app/university_graph.ttl
```

It tests four conjuncts the validated anchor query silently relies on:
[a] rank = string literals on `uni:role` (>=1 contains "professor"), no
`hasAcademicRank`/`rankLabel`; [b] every qualifying person has >=1 `uni:worksAt`;
[c] every worksAt unit maps via exactly one `uni:partOfUniversity` to a
`uni:University`-typed, `hasName`'d terminal; [d] exactly one `uni:hasName` per
person/university in scope.

- **All four PASS** → the graph is anchor-shaped: copy
  `/skill/references/v01_solution.sparql` verbatim to `/app/solution.sparql` and
  proceed to Step 3 (verification is still mandatory).
- **Any FAIL** → do NOT copy the reference. The failing conjunct names the edit:
  [a] fail → axis-1 rank-signal discovery; [b] fail → keep the guarded course
  fallback; [c] fail → axis-2 affiliation work (`*` + terminal anchor, inverse
  containment, appointment hops); [d] fail → name-predicate exclusivity +
  GROUP BY/MIN. Start from `/skill/templates/query_template.sparql` and apply
  exactly those edits, then proceed. The whole flow is rehearsed end-to-end by
  `/skill/scripts/drill_fail_branch.py` — 6 deviations in two regimes:
  S1–S4 pre-encoded (fingerprint FAIL → stock template handles it) and S5–S6
  hand-edit (inverse containment rewrite; person→org predicate substitution,
  where the drill proves the stock template FAILS and the edited template
  PASSES). Run it with `task_shell` to see the walkthroughs before adapting.

**Step 1 — build the expected answer by reading the data.** Enumerate every
person node, its rank signal, and its affiliation chain; write down the expected
(name, university) pairs by hand (the seed has a planted trap: Felix Wagner
teaches AI101 at NTUA but worksAt IST — only the worksAt chain counts). This set
is your ground truth for Step 3, independent of any query. On a full fingerprint
match you can skip the hand-derivation and use the shipped
`/skill/references/v01_expected.txt`. (All graph inspection goes through
`task_shell`: `cat /app/university_graph.ttl`, `grep` for role strings, etc.)

**Step 2 — write `/app/solution.sparql`** (reference copy or template adaptation
per Step 0). Project exactly `?professorName ?universityName`. (Copy via
`task_shell`: `cp /skill/references/v01_solution.sparql /app/solution.sparql`.)

**Step 3 — verify mechanically**:

```bash
# fingerprint MATCH: use the shipped expected file
python3 /skill/scripts/verify.py --graph /app/university_graph.ttl \
  --query /app/solution.sparql --expected-file /skill/references/v01_expected.txt \
  --exclude-substr Lecturer --exclude-substr Student
# otherwise: write your derived pairs to /app/expected.txt (one 'Name|University' per line)
# and pass --expected-file /app/expected.txt
```

PASS = projected variables are exactly {professorName, universityName}, every
row has 2 columns, expected pairs match as **multisets** (duplicate emissions
are rejected automatically with a "duplicate rows" diagnostic — do NOT rely on
--max-rows to notice them), no excluded substrings, row bounds hold.

## Working template

Two artifacts, used by the Step-0 dispatch:

- `references/v01_solution.sparql` — the EXACT validated anchor query (grader
  passed 3/3 in iteration 1). Copy verbatim ONLY on a full fingerprint match;
  the fingerprint gate is what prevents silent overfit when the graph deviates.
- `templates/query_template.sparql` — the family-general query; starts from the
  patterns above; adapt predicate names and the qualifying token set to the
  variant's data. It passed the full adversarial suite (v01 +
  two-same-named-professors + multi-valued names + missing-worksAt fallback +
  rankLabel-only identification + deep chain with named intermediate + direct
  affiliation). Use it whenever any fingerprint conjunct fails.

## Verification workflow (run this before finishing; rdflib is preinstalled)

```bash
# within the task container (skill package contents mounted read-only at /skill):
python3 /skill/scripts/verify.py --graph /app/university_graph.ttl --query /app/solution.sparql \
  --expected-file expected.txt --exclude-substr Lecturer --exclude-substr Student
# or in the author workspace:
python3 skill/sparql-professors-universities/scripts/verify.py --graph GRAPH.ttl --query Q.sparql ...
```

The harness exits non-zero on any violation. Checks performed (all automatic):
projected variables are EXACTLY {professorName, universityName} (read from the
engine-result surface, not the query algebra); every row has >= 2 columns;
expected pairs match as multisets; no excluded substrings in any projected value;
row-count bounds. For a fresh variant, run it with `--print` first to eyeball
rows before pinning the expected set.

Package-level regression (run before finishing any iteration; repeats every
layer: anchor flow, fingerprint precision M1-M4, 6-scenario fail-branch drill,
7-case adversarial suite):

```bash
python3 /skill/scripts/regression.py --graph /app/university_graph.ttl
# or from the author workspace:
python3 skill/sparql-professors-universities/scripts/regression.py --graph ...
```

Exit 0 = all layers passed. Everything the regression checks is now promoted
into the package — artifacts kept only in the container's /tmp are lost on
reset and are not evidence.

Checks that catch the family's failure modes:

| Symptom | Likely cause | Fix |
|---|---|---|
| projected variables wrong | query aliases/renames or drops a column | enforce exact {professorName, universityName} (verify.py does this automatically) |
| 0 rows | rank predicate wrong (role vs hasAcademicRank vs other); type guard too strict (`a uni:Person` absent in variant); token case mismatch | enumerate rank signals from data; drop/adjust type guard; match token case-insensitively |
| row count = 2× professors | plain UNION of worksAt and teaches paths | guarded fallback with `FILTER NOT EXISTS` |
| bogus university name | intermediate org in containment chain; cross-university teaching leaked through unguarded course path | terminal `a uni:University` anchor; guard the fallback |
| same-name duplicates collapsed | `SELECT DISTINCT` on projected names | GROUP BY person+university IRIs |
| multi-name professor duplicated | name literal inside dedupe scope / outer join re-expansion | GROUP BY + MIN(name) |
| direct-affiliation professors missing | `partOfUniversity+` instead of `*` | zero-hop `*` + anchor |
| `false || error` filters | unguarded CONTAINS/STRSTARTS on optional-bound variables | BOUND guards |

## Evidence and provenance

- **[V01] directly verified on the anchor graph**: 7-row expected set; role-string
  identification; one-hop `worksAt → partOfUniversity`; no schema triples.
- **[T] Teacher-taught, confirmed by my experiments**: guarded-fallback UNION
  semantics (E1a/E1b); final-DISTINCT half-safety and IRI-granularity (E4);
  BOUND-guard necessity — rdflib silently drops rows on `false || error` and
  `error &&` (E5a/E5b), lenient on `true || error` (E5c/E2a); GROUP BY+MIN strict
  cardinality (E7); `+` vs `*` with terminal anchor (D1/D2, G1–G3); inverse
  containment direction from data (G4).
- **[X] my reasoned extrapolation, exercised on synthetic variants**: rankLabel-only
  identification (E6), intermediate named faculty (G1–G3), direct affiliation (D1/D2),
  multi-valued names (E3/E7), same-named distinct professors (E4). These are
  synthetic, so treat exact row counts as evidence of mechanism, not as family
  ground truth; the mechanism transfers, the data varies.
- Full experiment log: `references/evidence.md`.