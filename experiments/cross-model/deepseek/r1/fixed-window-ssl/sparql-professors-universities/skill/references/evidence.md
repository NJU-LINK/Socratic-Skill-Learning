# Evidence log for sparql-professors-universities

Provenance labels:
- **[V01]** directly verified against the anchor graph `/app/university_graph.ttl`
  (129 triples) with rdflib 6.1.1 in the task container.
- **[T+E]** Teacher-taught claim, confirmed by my experiment.
- **[X]** my reasoned extrapolation, exercised on a synthetic variant (mechanism
  evidence only — row counts come from my mutated graphs, not the family).

## E1 — Affiliation path / course fallback (T+E, on mutated v01 graph)

Mutation: removed `Felix_Wagner uni:worksAt` (128 triples).

- E1a plain unconditional UNION `worksAt OR teaches`:
  **14 rows** — every professor doubled (worksAt-branch row + teaches-branch row
  even when both branches resolve to the same department), plus a bogus
  `Felix Wagner → National Technical University of Athens` fabricated from
  `teaches AI101` (NTUA) while Felix works at IST.
- E1b guarded fallback (`FILTER NOT EXISTS { ?person uni:worksAt ?w }` in the
  teaches branch): **8 rows** — 7 seed rows, plus `Felix → NTUA` via the fallback
  (Felix has no worksAt in this mutation and teaches courses in two universities).
  → Semantics decision: with the fallback active and courses spanning universities,
    the axis-3 invariant read as *one row per (person, university) pair* yields one
    row per reachable university. Documented in SKILL.md; a plain UNION is never
    acceptable (duplicates + fabrication).

## E2 — BOUND-guarded vs unguarded multi-signal filter (T+E, rdflib behavior)

Graph: v01.

- E2a unguarded `CONTAINS(role) || CONTAINS(?lbl)` with `?lbl` never bound:
  **7 rows** (rdflib leniency: `true || error` → true).
- E2b same with BOUND guards: **7 rows** (identical on this graph).
- E2c roles removed, hasAcademicRank absent, BOUND-guarded: **0 rows, no crash**
  (correct: nobody qualifies).

## E3 — Multi-valued person names (X => E7 refinement)

Mutation: added second `hasName "O. Morgan"` for Alex.

- E3a names inside inner `SELECT DISTINCT ?person ?pname ?university`:
  **8 rows** (Alex twice).
- E3b names outside dedupe, i.e. `DISTINCT ?person ?university` then outer name
  join: **8 rows** too. → The naive "dedupe IRIs then decorate" does NOT pin
  pair cardinality under multi-valued names; only aggregation does (E7).

## E4 — Same-named distinct professors vs final DISTINCT (T+E)

Mutation: added a second distinct professor IRI `John_Smith2` also named
"John Smith" at MIT Biology.

- E4a `SELECT DISTINCT ?professorName ?universityName` at top level:
  **7 rows** — the two John Smiths COLLAPSE into one.
- E4b `DISTINCT ?person ?university` inner + outer decoration: **8 rows** —
  both professors preserved.
→ Dedupe/distinct granularity must be person+university IRIs, never the projected
  name strings.

## E5 — rdflib filter-error semantics on unbound variables (T+E)

- E5a `CONTAINS(role) && CONTAINS(?missing)` (error in AND): **0 rows** — the
  whole result set silently dies.
- E5b `CONTAINS(role,'zzz') || CONTAINS(?missing)` (`false || error`): **0 rows** —
  every row dropped silently.
- E5c `CONTAINS(role,'professor') || CONTAINS(?missing)` (`true || error`):
  **7 rows** — lenient.
- E5c′ (exp2a) same leniency confirmed in the OPTIONAL-bound `?lbl` scenario.
→ Never rely on engine leniency: BOUND-guard every optional-bound variable used in
  a filter expression. Other engines may be stricter than rdflib.

## E6 — rankLabel-only identification (X, synthetic variant)

Mutation: deleted all `uni:role` triples; `uni:hasAcademicRank uni:FullProfessor`
+ `uni:rankLabel "Full Professor"` for Alex and John Smith only.

- E6a BOUND-guarded two-signal filter: **2 rows** (Alex → NTUA,
  John Smith → MIT). Correct.
- E6b same graph, unguarded filter: **2 rows** (rdflib leniency again —
  `error || true`); guard still prescribed for the E5 failure modes.

## E7 — GROUP BY + MIN pins pair cardinality (X, synthetic variant)

Mutation: two names for Alex (as E3).

- `GROUP BY ?person ?university` + `MIN(?pname)`: **7 rows**, Alex appears once.
  Also preserves the two John Smiths (E4-style mutation): **8 rows**.
- Note: MIN is lexicographic, so with `hasName "Alex Morgan"` + `hasName
  "O. Morgan"` the aggregate selected `"O. Morgan"` (the alias by sort order).
  This is why the template binds `?pname` exclusively from the primary name
  predicate: alias predicates must never feed the name aggregate.

## E8 — University name symmetry (T+E, synthetic variant)

Mutation: added second `uni:hasName "M.I.T."` for `uni:MIT`.

- Current template (university name decorated OUTSIDE the GROUP BY subquery):
  **8 rows** — `John Smith → Massachusetts Institute of Technology` and
  `John Smith → M.I.T.` side by side, exactly the E3 mechanism at university
  level.
- Fixed template (`MIN(?uname)` inside the same GROUP BY scope): **7 rows**,
  one per pair. The selected MIT spelling in this mutation was `"M.I.T."`
  (MIN is lexicographic: `"M.I.T." < "Massachusetts Institute of Technology"`);
  row cardinality is pinned, and spelling is deterministic but not
  "canonical" — with a multi-valued primary name predicate the data itself is
  ambiguous under MIN. Expectation-setting: the template's MIN guarantees pair
  cardinality; it does not substitute for a single-valued primary name
  predicate, which is what the task text ("the name of the university")
  assumes.
→ Rule: every projected literal lives inside the IRI-grouped subquery; nothing
  decorative joins after the dedupe.

## Decision record — /app/solution.sparql vs the family template

For the graded v01 anchor, `/app/solution.sparql` deliberately uses the simpler
validated shape (single name predicates, inner `SELECT DISTINCT ?person
?university`, outer decoration) rather than the full family template. Rationale:
v01 data is single-valued on every relation the query touches, the simpler query
is engine-robust and verified to produce the exact 7 expected rows, and grading
solvency of the deliverable outweighs internal consistency with the general
artifact. The template is the generalization surface; the solution is the anchor
answer. A future run on a noisier variant should port the template, not the
solution.

## G1–G3 — Containment depth and terminal anchor (T+E, synthetic variant)

Mutation: `Biology_MIT partOfUniversity SchoolOfScience` (named intermediate,
`a uni:Faculty`, `uni:hasName "School of Science"`), `SchoolOfScience
partOfUniversity MIT`; removed direct `Biology_MIT → MIT`.

- G1 one-hop `?dept uni:partOfUniversity ?u`:
  **7 rows** but `John Smith → School of Science` (bogus intermediate).
- G2 `partOfUniversity+` with NO type anchor: **8 rows** — John Smith appears
  twice (`MIT` and `School of Science`); every ancestor is bound.
- G3 `partOfUniversity+` with `?u a uni:University` anchor: **7 rows**, clean.
→ Property paths must be anchored at the terminal by type; `*` additionally needs
  the anchor so the zero-hop self-binding of a non-University unit is pruned.

## G4 — Inverse containment (X, synthetic variant)

Mutation: removed all `partOfUniversity`/`teaches`/`isTaughtIn`/`isEnrolledIn`;
rebuilt containment as `uni:University uni:hasDepartment uni:Department`.

- Query `?u uni:hasDepartment ?d . ?u a uni:University ; uni:hasName ?univName`:
  **7 rows**, clean. Direction decided from the mutated data, not from seed memory.

## D1/D2 — Direct university affiliation (T+E, synthetic variant)

Mutation: Alex `worksAt uni:NTUA` directly (no department hop).

- D1 `partOfUniversity+` + anchor: **6 rows** — Alex silently VANISHES
  (zero-hop case unrepresentable with `+`).
- D2 `partOfUniversity*` + anchor: **7 rows** — Alex returns via the zero-hop
  self-binding (unit IS a University).
→ Containment step count is `*` with a terminal type anchor, never bare `+`.

## Full-suite regression (template)

`templates/query_template.sparql` passes, in one run:
v01 (7), two same-named John Smiths @ MIT (8), multi-valued names (7),
Felix-without-worksAt fallback (8, pair semantics), rankLabel-only identification
(2), deep chain with named intermediate (7, no leak), direct affiliation (7).

---

# Iteration-2 additions (guided practice, second cycle)

## Replay evidence — the skill as used by a fresh solver (feedback/iteration-1.json)

The iteration-1 fresh-solver run was one-shot in a reset v01 container with the
frozen Skill package: **3/3 tests passed, exitCode 0, 14 tool calls, 1 attempt**.
All four resources (SKILL.md, evidence.md, verify.py, query_template.sparql)
were read; `scripts/verify.py` was executed for the final check. The fresh
solver followed the documented decision record and wrote the simple anchor shape
rather than the full template — the decision record mechanism worked exactly as
designed. Friction observed in the trajectory, fixed this iteration:

1. `/skill` mount layout probe: the solver first looked for
   `/skill/sparql-professors-universities/scripts` (the mount exposes package
   CONTENTS at /skill directly). SKILL.md now documents the exact layout.
2. Anchor-query reconstruction risk: the solver rebuilt the v01 query from
   prose in evidence.md. The exact validated query is now shipped as
   `references/v01_solution.sparql`, gated by the fingerprint check below.
3. Projected-variable names were checked by eye only. verify.py now enforces
   them mechanically (see next section).

## Projection check — stable results surface (T+E)

rdflib query algebra internals are private (`SelectQuery` CompValue exposes
`PV`/`p`; top-level `project` was `None` on 6.1.1) — do NOT mine them. Probe:
`res.vars` → `[Variable('professorName'), Variable('universityName')]`; `Variable`
subclasses `str`, so `str(v)` yields the bare name. Fallback: first result row's
`.labels` is a DICT `{'professorName': 0, 'universityName': 1}` — take `.keys()`.
verify.py now checks `{professorName, universityName}` exactly, with the
row-length >= 2 check kept as the shape backstop.

## Fingerprint gate (copy-vs-adapt dispatch) — anti-overfit mechanism

As long as every visible run uses v01's graph, a blindly copied reference
solution is an overfit trap. `scripts/fingerprint_v01.py` turns the copy-vs-adapt
decision into a mechanical dispatch over four conjuncts:
[a] rank = string roles on uni:role, no hasAcademicRank/rankLabel;
[b] every qualifying person has >= 1 uni:worksAt;
[c] every worksAt unit has exactly one partOfUniversity target, typed
uni:University, with hasName (and the unit is not itself a University, so a
direct-affiliation deviation cannot slip through);
[d] exactly one uni:hasName per person/university in scope.
All PASS -> copy references/v01_solution.sparql verbatim + verify. Any FAIL ->
follow the axis procedure; the failing conjunct names the required template
edit ([a] rank discovery, [b] guarded course fallback, [c] affiliation shape,
[d] name exclusivity + GROUP BY/MIN). Validated on v01 (all PASS, exit 0) and on
the four mutation classes (each FAILs exactly its own conjunct).

Diagnostic-precision sweep (empirically verified, mutation classes built in
memory from the anchor graph):

| mutation | exit | failed conjuncts |
|---|---|---|
| M1 rank-resource (hasAcademicRank+rankLabel added) | 1 | exactly [a] |
| M2 Marie's worksAt removed | 1 | exactly [b] |
| M3 named Faculty inserted in the chain | 1 | exactly [c] |
| M4 second hasName for Alex | 1 | exactly [d] |
| v01 anchor graph | 0 | none (all PASS) |

The conjuncts are independent: a dispatch gate is only useful if a deviation
trips exactly its own conjunct, so the solver receives unambiguous hints.

`references/v01_solution.sparql` is byte-identical to the graded
`/app/solution.sparql` (494 bytes, verified by copy + `diff -q`), so a verbatim
copy under a full fingerprint match reproduces the graded artifact exactly.

## Multiset comparison — cardinality violations can no longer slip through (T+E)

REPRODUCED false PASS: mutated v01 so every professor teaches only at home
(`AI101 isTaughtIn Mathematics_IST` instead of NTUA CS) — a plain UNION of
worksAt/teaches paths then yields **15 rows** (Felix binds IST three times)
whose 7 DISTINCT pairs exactly match the expected file. The set-based harness
printed PASS. After switching the expected comparison to `collections.Counter`
(multiset), the same command FAILs with the full duplicate list; the family
template on the same mutation yields 7 rows PASS. Provenance: /tmp/verify_setbased.py
(preserved set-based harness), /tmp/retargeted.ttl, /tmp/plain_union.sparql,
/tmp/retargeted_expected.txt. SKILL.md Step-3 now states multiset semantics; the
old docstring claim "duplicates caught by --max-rows" is gone — duplicates are
rejected automatically.

---

# Iteration-3 additions (guided practice, third cycle)

## Tool-boundary friction (from feedback/iteration-2.json trajectory)

The iteration-2 fresh solver (3/3, 10 calls) spent two calls on
`read /app/university_graph.ttl` and `read /skill/references/v01_solution.sparql`,
both returning WORKSPACE_BOUNDARY: the host read tool cannot see the container,
even though the eval prompt said to use task_shell. Lesson: preamble
instructions get skipped; instructions adjacent to the triggering step get
followed. SKILL.md now carries the boundary rule inside the tool-boundary note
at the package layout AND inside Steps 1-3 of the solve procedure.

## FAIL-branch drill — complete execution evidence for BOTH dispatch regimes

Until iteration 3, the fingerprint's FAIL branch had been validated only by
isolated synthetic mutations, never as a full solving flow.
`scripts/drill_fail_branch.py` rehearses it end-to-end for six spec-declared
deviations, in two regimes:

- PRE-ENCODED (S1-S4): the deviation is already absorbed by the stock
  template; the drill verifies the whole dispatch flow, adapted query == stock.
- HAND-EDIT (S5-S6): the solver must edit the template (containment rewrite,
  predicate substitution). The drill additionally asserts three things: the
  STOCK template FAILS on the mutated graph (edit is NECESSARY), the edited
  text differs from stock (an edit was applied), and the EDITED template PASSES
  (edit is SUFFICIENT) — turning each hand-edit scenario into a regression
  test of the edit itself.

Every scenario: mutate graph -> fingerprint (assert exit=1 and FAIL exactly
the expected conjunct) -> dispatch walkthrough text -> adapted query ->
independent Python BFS oracle asserts (1) qualifying-person set, (2) per-person
reachable university sets, (3) pair multiset, layer-by-layer for early
diagnosis -> verify.py PASS against the derived rows.

Oracle independence: the BFS implements the SKILL.md semantics (qualify by
role-token OR rankLabel-token; worksAt units, else taught-course isTaughtIn
units; walk containment edges past terminals collecting every University-typed
node at any depth; primary-name decoration; multiset pair-reading), with the
worksAt/containment predicates parameterized per scenario from the data. It
shares no structure with the SPARQL template (no UNION, no NOT EXISTS, no
property paths), so agreement is evidence of correctness, not
mirror-consistency.

Executed result (DRILL_EXIT=0):

| scenario | regime | fingerprint | oracle layers | stock verify | edited verify |
|---|---|---|---|---|---|
| S1 [b] Felix worksAt removed | pre-encoded | exit=1, exactly [b] | 7 qual / Felix {IST, NTUA} / 8 pairs | PASS | - |
| S2 [a] roles -> hasAcademicRank+rankLabel | pre-encoded | exit=1, exactly [a] | 7 qual / 7 pairs | PASS | - |
| S3 [c] named Faculty in chain | pre-encoded | exit=1, exactly [c] | 7 qual / John {MIT} / 7 pairs | PASS | - |
| S4 [c] Alex worksAt NTUA directly | pre-encoded | exit=1, exactly [c] | 7 qual / Alex {NTUA} / 7 pairs | PASS | - |
| S5 [c] containment inverted to uni:hasDepartment | HAND-EDIT | exit=1, exactly [c] | 7 qual / 7 pairs | FAIL (edit necessary) | PASS (`^uni:hasDepartment*` rewrite) |
| S6 [b] uni:worksAt renamed uni:employedBy | HAND-EDIT | exit=1, exactly [b] | 7 qual / 7 pairs | FAIL (fallback fabricates Felix->NTUA) | PASS (predicate substitution at ALL occurrence sites incl. FILTER NOT EXISTS) |

HAND-EDIT lessons, now rehearsed rather than assumed:
- S5: the `?unit ^uni:hasDepartment* ?university` rewrite (previously only a
  standalone G4 query) is walked end-to-end with the same terminal anchor.
- S6: a person-to-organization rename must be substituted at every occurrence
  — the primary branch, the fallback branch's guard, and above all the
  `FILTER NOT EXISTS { ?person uni:worksAt ?anyUnit }` guard, which becomes
  vacuously true otherwise, so the fallback fires alongside the primary branch
  and Felix's two-university teaching blows the pair count up. The
  stock-fails/edited-passes pair exposes exactly this near-miss class.

Debugging bonus (evidence for the layered design): the first run of the
six-scenario drill failed at layer [2] for every scenario because the oracle
passed a plain string as the containment predicate (`containment[0]`) where
rdflib needs a URIRef (a str is coerced to a Literal and matches nothing). The
per-person reachable-set layer diagnosed it in one line — the early-failure
layering did its job.

## Shipped anchor expected rows

`references/v01_expected.txt` (7 rows, pipe-separated) removes the
hand-transcription step fresh solvers performed every run, including its
typo/accent risk ("Instituto Superior Técnico"). Used automatically in Step 3
on a full fingerprint match; verified identical to the solver-derived sets in
iterations 1-2.

## Promoted regression — one entry point for every layer (repeatability fix)

The precision sweep (M1-M4) and the seven-case adversarial suite previously
lived only as /tmp scripts inside the task container — and the container is
reset every iteration, so those artifacts were memory, not evidence. They are
now promoted into the package as `scripts/regression.py`, which self-contains
all four layers: (A) anchor flow — fingerprint MATCH -> copy reference ->
verify PASS; (B) fingerprint precision sweep M1-M4, each mutation built in
memory and failing exactly its own conjunct; (C) the six-scenario fail-branch
drill (subprocess, with an --outdir in the run's TemporaryDirectory);
(D) the seven-case adversarial suite against the family template. All
mutations are built in memory; files exist only inside one
`tempfile.TemporaryDirectory()` (auto-cleaned), and resource paths resolve
relative to `__file__` so the script works from `/skill` or the author
workspace. The drill gained `--outdir` + `__file__`-relative paths for the
same reason (its /tmp hardcodes would silently collide across runs and vanish
on reset).

Executed result on the promoted copy (iteration 3, in-container):
REGRESSION_EXIT=0 — LAYER A PASS, LAYER B PASS (M1-[a], M2-[b], M3-[c],
M4-[d] each exit=1 with exactly its own conjunct), LAYER C PASS (6 scenarios,
S1-S4 pre-encoded, S5-S6 hand-edit), LAYER D PASS (D1 7, D2 8, D3 7, D4 8,
D5 2, D6 7, D7 7). This run reproduces the results previously recorded from
the /tmp suites, now repeatably.