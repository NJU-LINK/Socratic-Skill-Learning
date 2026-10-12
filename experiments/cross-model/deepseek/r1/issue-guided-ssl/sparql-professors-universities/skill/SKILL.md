---
name: sparql-professors-universities
description: >
  Build and verify SPARQL queries that return one row per qualifying professor
  together with the university they work at (?professorName, ?universityName),
  from a Turtle knowledge graph of universities, departments, employees,
  students, and courses. Encodes a three-knob query skeleton mapped to the
  family's three variation axes (professor identification semantics,
  affiliation structure to university, graph noise and result cardinality):
  semantic anchor-family role inclusion (NOT enumeration of observed
  literals), per-instance hand-traced affiliation reachability with a
  uni:University type check, and pair-level DISTINCT. Includes a
  data-inspection procedure, a local rdflib verification loop, and a
  cross-draw discriminator that guards against the draw-regeneration failure
  (evaluated instances redraw names/title strings/cardinality while
  predicates, types, and task semantics stay fixed).
---

# sparql-professors-universities

## 1. Task shape and invariants

Input: a Turtle file (e.g. `/app/university_graph.ttl`) containing an ontology
prefix `uni:` (`http://university.org/ontology#`) and instance data:
universities (`a uni:University`, `uni:hasName`), departments
(`a uni:Department`), courses, persons (`a uni:Person`, `uni:hasName`), and
roles/affiliations linking them.

Contract (family invariant):
- Query saved to the path given by the task (e.g. `/app/solution.sparql`).
- Projects **exactly** the two variables `?professorName` and `?universityName`.
- **One row per qualifying (professor, university) pair** — never per
  department, course, or duplicate signal.
- Students, staff, lecturers, and other non-professor persons excluded.

**DRAW-REGENERATION BOUNDARY (evidenced, do not forget):** the `/app`
instance values are a *preview draw*, not the evaluated instance. The
benchmark regenerates the instance per evaluation: person names, role-title
strings, field suffixes, and professor cardinality vary between draws.
What stays fixed is the ontology (predicates `uni:role`, `uni:worksAt`,
`uni:partOfUniversity`, `uni:hasName`; class types) and the *semantic rule*
from the task statement ("Assistant Professors and Full Professors;
lecturers/students/staff excluded"). Therefore: **never encode observed
instance strings (names, titles, cardinality) into the query**; encode the
semantic rule. A locally "VERIFIED" result against your draw is necessary
but NOT sufficient evidence of correctness — the iteration-1 evaluator
failure (7/8 rows, one silently dropped unseen professor) happened while
both the author's and the fresh solver's local checks printed VERIFIED.

The three family variation axes (from spec.yaml) are:
1. **professor_identification_semantics** — how qualifying persons are
   recognized (role-string titles vs. rank resources; which ranks count;
   near-miss roles; abbreviations).
2. **affiliation_structure_to_university** — how a person links to a
   university (worksAt→department→partOfUniversity chain, direct link, longer
   chains, inverse containment, appointment resources, teaching-course
   fallback).
3. **graph_noise_and_result_cardinality** — distractors, duplicate signals,
   overlapping paths, multiple departments/courses per university.

## 2. Core artifact: the three-knob parameterized skeleton

Every instance query in this family is one instantiation of this skeleton.
Each knob is tied to exactly one axis and guards exactly one failure mode.

```sparql
PREFIX uni: <http://university.org/ontology#>

# KNOB A (axis 1, role): SEMANTIC ANCHOR-FAMILY INCLUSION. Write the
# accepted rank anchors from the TASK STATEMENT (not from observed
# literals): for v01, "Assistant Professor" and "Full Professor" ("referred
# to simply as Professors"), plus the "Prof." abbreviation and case
# variants. Encode as a case-insensitive prefix over the anchor family:
#   (optional 'assistant ' | 'full ') + ('prof.' | 'professor')
# This matches "Professor of X", "Assistant Professor of X", unseen
# "Full Professor of X", "Prof. X" and structurally cannot match
# "Associate/Visiting/Adjunct Professor", "Lecturer", "Student".
# NEVER enumerate observed qualifying literals (VALUES of draw strings):
# any unseen qualifying form (e.g. "Full Professor of ...") drops silently.
# If the task semantics DEMOTE an anchor-passing status ("Professor
# Emeritus", "Professor of Practice"), add an explicit subtraction:
#   FILTER(LCASE(?role) NOT IN ("professor emeritus", ...))
# KNOB B (axis 2, affiliation): the person→university path traced per
# instance from a real person IRI to a university IRI in the TTL
# (predicates, direction, hop count, interposed nodes). Add
# ?u a uni:University to prune chain targets.
# KNOB C (axis 3, cardinality): SELECT DISTINCT on the two projection
# variables; pairs checkers compare sets of value tuples. DISTINCT
# collapses duplicate (name, university) tuples from multi-department/
# multi-course multiplicity but CANNOT repair wrongly bound pairs.

SELECT DISTINCT ?professorName ?universityName
WHERE {
  ?p a uni:Person ;
     uni:role ?role ;
     uni:hasName ?professorName ;
     uni:worksAt/uni:partOfUniversity ?u .   # KNOB B: traced path
  ?u a uni:University ;                      # KNOB B: type-prune chain targets
     uni:hasName ?universityName .
  FILTER(REGEX(LCASE(?role), "^(assistant\\s+|full\\s+)?(prof\\.|professor)"))  # KNOB A
  # KNOB A amendment, only when semantics demote an anchor-passing status:
  # FILTER(LCASE(?role) NOT IN ("professor emeritus"))
}
ORDER BY ?professorName                       # optional; keeps output stable
```

Mechanics and limits:
- **Knob A**: read the literals from the file only to *learn which forms the
  generator uses* and to extend the pattern from the inventory (e.g. if the
  draw shows `Assist. Prof. of X`, extend the prefix alternation to
  `assist\.\s+`; if it shows `Prof.` alone, the `prof\.` alternative already
  covers it). The qualifying decision comes from the task statement. If rank
  is a resource (`uni:hasAcademicRank` + `uni:rankLabel`), apply the same
  anchor pattern to `uni:rankLabel` (possibly plus `?r a uni:XRank`) — the
  principle is invariant: include by semantic anchor, subtract by explicit
  demotion, never enumerate observed labels. **Known boundary of prefix
  anchoring**: a trailing-status title ("Professor Emeritus") DOES pass the
  prefix anchor; demote it with the subtraction amendment only when the
  variant's semantics say so — do not subtract by default without evidence
  (v01 semantics mention only Assistant/Full).
- **Knob B**: the compact path is two subject→object hops. Trace by hand
  2–3 known qualifying persons before trusting it (see §3). If chains
  lengthen (faculty/school nodes interposed), use path repetition
  `uni:worksAt+` / `uni:partOfUniversity+` with the type check; if the
  containment direction is inverse, invert the path (`^uni:hasDepartment`).
  **Known limit of the type-check pruning**: if the graph also contains
  university→university containment, both endpoints pass `a uni:University`
  and DISTINCT cannot repair the extra length — handle by hop-length selection
  (fix the path shape, do not add DISTINCT) or by eliminating such edges.
- **Knob C**: keep the projection to exactly the two contract variables; do
  not smuggle diagnostic COUNT/aggregates into the solution file. DISTINCT is
  required because the checker compares sets of pairs; expect multiplicity
  whenever a professor teaches N courses or sits in N departments of one
  university (axis-3 duplicate-binding risk). If the trace shows two genuinely
  distinct universities for one person, the task's "exactly one university"
  assumption is violated for that variant: either filter (task hint), or
  report the ambiguity — DISTINCT will NOT deduplicate different pairs.

## 3. Reusable instantiation procedure

1. **Inventory the draw** (preview only): `grep -n 'uni:role' <graph>.ttl` or
   `python3 scripts/inspect_graph.py <graph>.ttl` (prints role/rankLabel
   literals with counts, name-predicate coverage, outgoing affiliation
   predicates). Note the FORMS present ("Professor of X", "Assistant
   Professor of X", abbreviations) — these extend the anchor pattern — but do
   not let them define the qualifying set.
2. **Derive the anchor family from the task statement**: which ranks
   qualify, which are explicitly demoted. Write the inclusion pattern and
   any subtraction list. For v01: anchors = plain/assistant/full professor +
   `Prof.` abbreviation; no subtractions.
3. **Trace the affiliation (Knob B)**: run `python3 scripts/trace_affiliations.py
   <graph>.ttl` — it BFS-discovers each role-bearing node's minimal path to a
   `uni:University` (predicates AND directions; persons are walls; schema
   `rdf:type` edges are excluded so class nodes cannot teleport the search),
   reports nodes with zero/multiple universities (axis-3 ambiguity risk), a
   signature frequency table, and a coverage score of the standard candidate
   path expressions, suggesting the full-coverage one. **When no candidate
   covers the reachable targets (the candidate list is hardcoded), read the
   SIGNATURE FREQUENCIES and build the path from the most common signature**:
   fix the first hop, make the tail alternation-in-repetition over every
   predicate observed at later hop positions (`^pred` hops become
   `^uni:pred`); the tracer automates this as its DERIVED expression (e.g.
   `uni:worksAt/(uni:partOfUniversity|uni:subOrganizationOf)+` on
   heterogeneous chains). Interpret: uncovered
   nodes whose role is student/lecturer are Knob-A noise, not Knob-B gaps.
   Confirm the university object carries the name predicate
   (`uni:hasName`) and persons do too (usually the same predicate — verify,
   variants may differ). Sanity-check the tracer's report against 2–3
   persons by hand.
4. **Count expected rows in the preview draw**: number of distinct
   qualifying persons (= pairs under the one-university assumption). This
   number is a *preview-draw sanity oracle* only — it must NOT be hard-coded
   anywhere, because cardinality varies across draws.
5. **Write the query**: instantiate the skeleton; the Knob A pattern
   annotated against the task semantics, the traced path as Knob B.
6. **Verify locally and cross-draw** (§5). Record the numbers and commands;
   then reason about semantics (local "VERIFIED" is not correctness).

## 4. Axis-by-axis variation playbook

### Axis 1 — professor identification
- v01 seed: string `uni:role` titles; semantic rule = Assistant + Full
  Professors ("referred to simply as Professors"); excluded: Lecturer,
  Student. Forms observed in preview draws: `"Professor of <field>"` and
  `"Assistant Professor of <field>"` (also `"Full Professor of <field>"` in
  other draws of the same variant — the word "Full" from the task text
  appears as a title token in evaluation draws, so the pattern must admit
  it even when your preview draw never shows it).
- **Inclusion by anchor**: `"^(assistant\s+|full\s+)?(prof\.|professor)"`
  (case-insensitive through LCASE). Structurally excludes pre-anchor near
  misses: Associate Professor, Visiting Professor, Adjunct Professor,
  Clinical Professor. A near-miss only enters if you ADD its token to the
  anchor — which you never do unless the task says that rank qualifies.
- **Subtraction by demand**: anchor-PASSING literals that the task semantics
  demote (e.g. "Professor Emeritus", "Professor of Practice") need an
  explicit `NOT IN` / negative-regex amendment. Decide per variant from the
  inventory + task statement; do not subtract speculatively.
- Abbreviation/spelling variants ("Prof.", "prof", "Assist. Prof.",
  uppercase/lowercase): extend the alternation from the inventory
  (`prof\.`, `assist\.\s+`, ...); keep case-insensitivity.
- Rank-as-resource variants: `?p uni:hasAcademicRank ?r . ?r uni:rankLabel
  ?l` — same anchor pattern on the labels (Knob A principle invariant).
- Variants may broaden/narrow ranks (e.g. include Associate, exclude
  Assistant): the anchor alternation is the single edit point.

### Axis 2 — affiliation structure

Choose the Knob B template from the shape that `trace_affiliations.py`
reports on the current draw (all templates verified in
`scripts/affiliation_check.py`, recorded output in §6):

| tracer shape | Knob B template (path to `?u`) | notes |
|---|---|---|
| direct worksAt | `?p uni:worksAt ?u` | target must be `a uni:University` |
| chain, 2 hops (v01) | `?p uni:worksAt/uni:partOfUniversity ?u` | seed shape |
| longer chain, HOMOGENEOUS | `?p uni:worksAt/uni:partOfUniversity+ ?u` | `+` repeats ONE predicate: fine only when every hop uses that same predicate |
| HETEROGENEOUS chain | `?p uni:worksAt/(uni:partOfUniversity|uni:subOrganizationOf)+ ?u` | alternation-in-repetition `(p1|p2)+` = one hop of p1 *or* p2, any depth; hop predicates come from tracer signatures / its DERIVED expression; plain `+` silently drops mixed-predicate professors (G_hetero check) |
| inverse containment | `?p uni:worksAt/^uni:hasDepartment ?u` (use the observed containment predicate) | trace direction first — `^`-paths encode what the data actually says |
| appointment resource | `?app a uni:Appointment ; uni:appointee ?p ; uni:role ?role ; uni:atUniversity ?u` | Knob A MOVES to the appointment node; on-Person role filter yields 0 rows (playbook check) |
| course-only fallback | `?p uni:teaches/uni:isTaughtIn/uni:partOfUniversity ?u` GUARDED | see guard below |

**Fallback guard (Felix-Wagner hazard)**: a professor may teach a course
located in ANOTHER university's department (v01: Felix Wagner works at
IST but teaches AI101, which is taught in NTUA's CS department). An
unguarded course-path UNION would bind him to TWO universities and
DISTINCT cannot repair that. When some qualifying persons lack
`uni:worksAt`, build the fallback with precedence:

```sparql
{ ?p uni:worksAt/uni:partOfUniversity ?u . }
UNION
{ ?p uni:teaches/uni:isTaughtIn/uni:partOfUniversity ?u .
  FILTER NOT EXISTS { ?p uni:worksAt ?_any . } }
```

`affiliation_check.py` F2_crosslink shape proves the unguarded variant
double-binds (recorded in §6). Only add the fallback when the tracer
shows qualifying nodes unreachable via `worksAt`; never by default.

### Axis 3 — noise and cardinality
- Duplicate signals: professor teaches many courses / appears in many
  departments of one university → DISTINCT collapses to one pair row.
- Overlapping organization paths: two departments of one university both
  linking a professor → DISTINCT still yields one row; the traced-pairs
  check in verification detects genuine double binding.
- Wrongly bound pairs (person mis-linked to a second university): DISTINCT
  does NOT fix; the pair-set verification against hand tracing catches it.
- Non-professor noise (lecturers, students, staff with `uni:worksAt`):
  excluded at knob A; their presence must not change the row count. The
  number of noise persons varies across draws — never assert a fixed total.

## 5. Verification procedure

Two complementary layers — local (draw sanity) and cross-draw (semantic
robustness) — plus the axis-2 shapes playbook. Local success alone is NOT
correctness: the iteration-1 failure had a perfect local VERIFIED.

1. **Local structural check** (per draw): `python3 scripts/verify.py
   <graph.ttl> <query.sparql> [preview_pairs.tsv]` (rdflib 6.x; check
   `python3 -c "import rdflib"` first). Prints the row count; with an
   expected-pairs file (one `professorName<TAB>universityName` per line,
   `#` comments allowed, hand-traced in §3.4) it checks count and set
   equality. **A preview oracle is only valid for its own draw** — never
   ship a fixed cardinality or fixed name pairs as a cross-draw oracle
   (`references/expected_pairs_v01.tsv` is a preview artifact).
2. **Cross-draw discriminator** (semantic check): `python3
   scripts/cross_draw_check.py` — the package's acceptance evidence. It
   builds two synthetic v01-style draws (Draw A = familiar literals + near
   misses; Draw B = Draw A + unseen qualifying form "Full Professor of
   Robotics" + extra near misses), then asserts:
   - the OLD enumeration mechanism passes Draw A but fails Draw B by
     dropping exactly the unseen professor (reproduces the evaluator
     7/8 failure);
   - the NEW anchor+subtraction mechanism passes BOTH draws and excludes
     every near miss (Associate/Emeritus/Visiting/Lecturer/Student);
   - the pure anchor's emeritus capture is visible (caveat demonstrated).
   Recorded output lives in §6. Exit 0 only when all assertions hold.
3. **Affiliation-structure checks** (axis-2 evidence): `python3
   scripts/affiliation_check.py` — the executable playbook: synthetic
   shapes for direct, chain2, chain3, inverse containment, appointment,
   course-only, the F2 cross-link hazard, and G_hetero (heterogeneous
   chain: homogeneous `partOfUniversity+` returns 1 of 2 rows, the
   alternation-in-repetition `(partOfUniversity|subOrganizationOf)+`
   returns both, noise excluded); asserts each dedicated template returns
   the exact pair set with noise excluded, that the v01 two-hop template
   does NOT solve the other shapes (why tracing precedes template choice),
   that Knob A must sit on the appointment node, and that an unguarded
   course fallback double-binds (guarded variant passes).
   Also re-run `scripts/trace_affiliations.py <graph.ttl>` on the solution
   draw and confirm the query's Knob B matches the reported shape; its
   DERIVED expression covers heterogeneous chains with predicates the
   hardcoded candidate list never saw.
4. **Reason over semantics**: state which task-statement anchor family the
   pattern encodes and why no nearby role form can leak in. This, not the
   local oracle, is the correctness argument that survives redraws.
5. Negative control (optional per variant): on a copy of the draw, run the
   query with a deliberately weakened knob A (substring "professor") and
   compare — equal counts are expected when the draw has no near misses and
   prove nothing; discrimination power comes from cross_draw_check.py.

## 6. Worked evidence (v01: iteration-1 failure, iteration-2 fix,
iteration-3 axis-2 machinery)

**Data preview (draw 1, author's run)**: `/app/university_graph.ttl`
(9 universities, 11 departments, 9 courses, 11 persons). Role literals
found (`grep -n 'uni:role'`): `"Professor of Computer Science"`,
`"Assistant Professor of Computer Science"`, `"Professor of Mathematics"`
(×2 persons), `"Professor of History of Scienceand Technology"`,
`"Professor of Biology"`, `"Assistant Professor of Engineering"`,
`"Lecturer"` (Jane Petterson), `"Student"` (×3). These are DISPLAYED
evidence of forms, not the qualifying definition.

**Evaluator failure (fresh clean-v01 run, unresolved by iteration-1 skill):
2/3 tests, 7/8 rows.** Expected 8 professors included `Nathan Cole→
University of California, Berkeley`; got = expected minus Cole. The
preview-draw names `Alex Morgan`, `Felix Wagner` do not appear in the
evaluated reference at all — the evaluated instance was regenerated with
different names, and one professor's role-title form was unseen in the
preview (plausibly `"Full Professor of ..."`), so the closed six-literal
VALUES query silently dropped it. Local verification had printed VERIFIED
against the preview draw. This is the draw-regeneration mechanism.

**Fix (iteration-2)**: Knob A = anchor-family regex
`"^(assistant\\s+|full\\s+)?(prof\\.|professor)"` (LCASE'd). On the
preview draw it returns the same 7 correct rows; on synthetic draws it
admits "Full Professor of Robotics". Verified in rdflib 6.1.1:
`Professor of Computer Science`→match, `Assistant Professor of
Engineering`→match, `Full Professor of Engineering`→match, `Prof. X`→match;
`Associate Professor`/`Visiting Professor`/`Adjunct Professor`/
`Lecturer`/`Student`→no match; **`Professor Emeritus`→match** (trailing
status passes the prefix anchor → subtraction amendment when demoted).

**Cross-draw discriminator recorded output** (`python3
scripts/cross_draw_check.py`, run 2026-09-15, exit 0):

```
== cross-draw discriminator ==
Draw A: qualifying=6  Draw B: qualifying=7
OLD (VALUES enumeration):  A=6 rows (passes: True)   B=6 rows (passes: False)
   -> missing on B: ['Robotics Newcomer']
NEW (anchor + subtraction): A=6 rows (passes: True)   B=7 rows (passes: True)
   -> near misses excluded: True
PURE anchor (no subtraction): A=7 B=8; captures emeritus on A: True -> demoted anchor-passing literals need the subtraction amendment

  [PASS] OLD passes Draw A (local success is draw-specific)
  [PASS] OLD fails Draw B exactly like the evaluator (drops unseen form)
  [PASS] NEW passes BOTH draws
  [PASS] NEW excludes all near misses
  [PASS] Pure-anchor emeritus capture is visible (caveat demonstrated)
DISCRIMINATOR OK
```

**Local verification of the fixed query on draw 1** (rdflib 6.1.1,
`scripts/verify.py` + `references/expected_pairs_v01.tsv`): 7 rows,
count equality True, pair set equality True, VERIFIED, exit 0 — accepted
ONLY as preview-draw sanity; the cross-draw discriminator + the semantic
argument are the correctness evidence that survives regeneration.

Calibration: v01 previews contain no near-miss roles and no "Full
Professor" tokens — the anchor pattern's coverage of unseen forms is
established by the synthetic draws, not by v01 itself. The synthetic
shapes are hypotheses about what the variant generator emits; their
passing proves internal consistency, not coverage. The spec axis
enumeration is the coverage checklist: different person-to-organization
predicates (alternation rule, §4 axis 2), longer chains (C_chain3),
HETEROGENEOUS chains (G_hetero, issue-2 fix), inverse containment
(D_inverse), appointment resources (E_appointment), teaching-course
fallback (F_course_only/F2_crosslink). Every row must still be
re-verified on a variant's own draw with `trace_affiliations.py`.

**Affiliation tracer on the v01 preview draw** (`python3
scripts/trace_affiliations.py university_graph.ttl`, run 2026-09-15,
exit 0 — abbreviated):

```
== rank info placement (Knob A node) == roles on: {'Person': 11}
== reachability (role-bearing/person nodes: 11) ==
  reach a university: 11   unreachable: 0   multi-university: 4
  multi-university Felix_Wagner: 2 universities via worksAt/partOfUniversity ...
  multi-university Student1: 4 universities via isEnrolledIn/...
  ...
== minimal path signatures (frequencies) ==
    8 x  worksAt/partOfUniversity
    3 x  isEnrolledIn/isTaughtIn/partOfUniversity
== candidate path-expression coverage (query templates) ==
    0/11  direct worksAt
    8/11  worksAt -> partOfUniversity+ (chain)     <- chosen Knob B
    7/11  teaches -> isTaughtIn -> partOfUniversity+
   ... uncovered: Student1/2/3 only via isEnrolledIn/isTaughtIn/... (Knob-A noise)
```

The tracer surfaced the genuine axis-3 hazard in v01's own draw: **Felix
Wagner reaches two universities** — worksAt → IST, but the course
AI101 he teaches belongs to NTUA's CS department. The chosen query uses
only the worksAt path, so he binds exactly once to IST; this is precisely
why the course fallback must be guarded (§4 axis 2).

**Affiliation playbook recorded output** (`python3
scripts/affiliation_check.py`, run 2026-09-15, exit 0 — abbreviated):

```
== axis-2 affiliation-shape playbook ==
  [PASS] A_direct        template rows=2 expected=2   (v01 template: rows=0, wrong)
  [PASS] B_chain2        template rows=2 expected=2
  [PASS] C_chain3        template rows=2 expected=2   (v01 template: rows=0, wrong)
  [PASS] D_inverse       template rows=2 expected=2   (v01 template: rows=0, wrong)
  [PASS] E_appointment   template rows=2 expected=2   (v01 template: rows=0, wrong)
  [PASS] F_course_only   template rows=2 expected=2   (v01 template: rows=1, wrong)
  [PASS] F2_crosslink    template rows=2 expected=2
  [PASS] G_hetero         template rows=2 expected=2
  [PASS] role-on-Person template on E_appointment yields 0 rows (Knob A moves)
  [PASS] homogeneous partOfUniversity+ on G_hetero returns 1 of 2 rows
         (silent drop of the two-hop professor reproduced)
  [PASS] alternation-in-repetition (partOfUniversity|subOrganizationOf)+ on
         G_hetero returns both professors, lecturer excluded
  [PASS] unguarded course fallback on F2_crosslink double-binds Cross Prof
         to Beta University -> fallback must prefer worksAt
PLAYBOOK OK
```

**Heterogeneous-chain tracer evidence**: on the G_hetero synthetic shape,
`trace_affiliations.py` scores the hardcoded candidates 0–1/3 targets
(`worksAt -> partOfUniversity+` covers only 1/3 — the silent-drop shape of
this spec variant) while its DERIVED expression covers 3/3 and is
suggested: `?p uni:worksAt/(uni:partOfUniversity|uni:subOrganizationOf)+ ?u`.
The derivation rule (most common signature; tail becomes
alternation-in-repetition over all observed tail predicates) needs no
prior knowledge of `subOrganizationOf`. On the v01 preview it derives
`uni:worksAt/(uni:isTaughtIn|uni:partOfUniversity)+` (8/11; the extra
`isTaughtIn` alternative is inert under the university type check).

## 7. Tooling notes

- rdflib 6.x is usually preinstalled (`python3 -c "import rdflib"`); `pip`
  may be absent. `g.query(text)` works directly (no `prepareQuery` import
  needed in rdflib 6).
- **Never name a helper script `inspect.py`**: it shadows the stdlib module
  `inspect` that rdflib imports internally and crashes every tool with
  `AttributeError: module 'inspect' has no attribute 'getmro'` when run from
  the scripts directory (`sys.path[0]`). This package therefore ships the
  inspector as `inspect_graph.py`; the residual `inspect.py` in scripts/ is a
  transparent re-exporter of the stdlib module, kept only because the file
  cannot be removed from the package.
- chmod +x scripts/*.py (or always invoke as `python3 scripts/script.py`).
- Script roster: `inspect_graph.py` (role/rank/name/predicate inventory),
  `trace_affiliations.py` (automated Knob B shape discovery),
  `verify.py` (preview-draw sanity), `cross_draw_check.py` (axis-1
  discriminator), `affiliation_check.py` (axis-2 playbook). All rdflib-only;
  none needs pip.
- SPARQL REGEX uses XPath regex: `\\s`/`\\.` in the query file are `\s`/`\.`
  in the regex; LCASE precedes it for case-insensitivity (avoid the `i`
  flag which is not universally supported).

## 8. Failure-mode quick table

| Symptom | Likely cause | Fix |
|---|---|---|
| One qualifying professor missing (evaluator only) | Knob A enumerates observed literals; evaluated draw has unseen title form | semantic anchor inclusion (regex over task-defined rank anchors) |
| Near-miss roles appear (Associate/Visiting...) | substring/REGEX "professor" anywhere | prefix anchor regex (anchor at title start) |
| Demoted status appears ("Professor Emeritus") | anchor-passing trailing status not subtracted | explicit NOT IN / negative amendment when semantics demote it |
| Too many rows | extra path binding (multi department/university per person) | tighten knob B; only then DISTINCT |
| Professor bound to 2 universities (fallback case) | unguarded course-path UNION; professor teaches a course in another university's dept | prefer worksAt; guard fallback with `FILTER NOT EXISTS { ?p uni:worksAt ?_ }` |
| Tracer reports multi-university for a professor | worksAt path vs teaches path cross universities (v01: Felix Wagner) | semantic path = worksAt per task; never union unguarded |
| Whole query returns 0 rows | wrong Knob B template for the shape (direct/inverse/appointment/...) | run trace_affiliations.py; pick matching template (§4 axis 2) |
| One professor missing on a chain variant | homogeneous `+` used on a HETEROGENEOUS chain (mixed predicates per hop) | alternation-in-repetition `(p1|p2)+` from tracer signatures / DERIVED expression (§4 axis 2) |
| Too few rows (local) | anchor pattern too narrow / different name predicate | extend alternation from inventory; check predicates |
| Wrong university per professor | path direction/hops misread | re-run trace_affiliations.py and pick the reported shape's template (§4 axis 2) |
| Duplicates for same pair | multi-course/multi-department signals | DISTINCT on the two vars (knob C) |
| Trusting local VERIFIED as correctness | draw regeneration not accounted for | run cross_draw_check.py; argue semantics, not oracle |