---
name: xlsx-structure
description: >-
  Structural transformations of .xlsx workbooks with strict preservation of
  everything outside the declared transformation: block-local sorting,
  predicate/style-based filtering and compaction, header-aligned append,
  sparse-record reconciliation, row extraction, and layout transposition.
  The pipeline derives topology from the workbook itself (blank-row-separated
  blocks), evaluates row-local arithmetic formulas from their text (never
  trusting openpyxl caches), performs stable in-place value-only rewrites, and
  verifies the result against the input (formulas gone, geometry, sort order,
  blank separators, styles, dimensions) before finishing.
---

# xlsx-structure

Structured .xlsx transformations where one region of one sheet is transformed
while the rest of the workbook (other sheets, values, styles, filters, merges,
panes, row heights, column widths, dimensions) must survive byte-equivalent in
meaning. The family is defined jointly by `spec.yaml` (five variation axes) and
the anchor case `train/v01` (block-local stable sort by evaluated column D).

## Five axes -> mechanisms (v01 anchors + variant hooks)

| spec axis | v01 mechanism (direct evidence) | variant hook |
|---|---|---|
| `workbook_topology` | Blank-row **block detector**: scan the span's rows; a row is blank iff every used column in the span is empty; blocks are maximal runs of non-blank rows. Never hardcode the 9 block ranges. | Hook: the blank predicate and the scanned span (`--span`). Variants put data in one vs. several sheets, style-marked cells, repeated blocks, sparse tables, ID lists — swap the detector's source (e.g., fill-color predicate) while keeping the run-grouping core. |
| `selection_and_alignment_rule` | **Sort-key extractor**: evaluated numeric value of column D per original row (`--sort-col D`, `--desc`). | Hook: replace the key extractor with membership-in-range, exact header/ID identity, fill color, text predicate with exclusions, source-list order. The stable reorder machinery stays. |
| `transformation_semantics` | **Payload mapper**: evaluate formula columns D–F row-locally to numbers, then stable-sort complete rows (`key=(-d, original_idx)`) and map the payload back onto the block's coordinates. TWO semantics are now executable: `scripts/transform.py` (block-local sort) and `scripts/filter_compact.py` (block-local predicate filter + compaction, with geometry re-derivation). | Hook: filter/compact drops payload rows and compacts (geometry changes!); append maps rows after a header; reconciliation joins sparse records by ID; transposition maps (row,col) -> (col,row). Same detector/evaluator/preservation core, different mapper + mode-aware checks. New semantics follow the contract in the "Two executable semantics" section below. |
| `output_geometry` | Write transformed values into the **same coordinates the block occupied**; blank separators therefore stay exactly at their input rows with zero extra code (within-block sort preserves block sizes). | Hook: `--span` + write-target mapping. Variants may create a destination sheet/range, append at a boundary, or compact — the mapper returns (target_row, payload) pairs instead of the identity layout. |
| `preservation_constraints` | **In-place value-only rewrites** on one openpyxl handle: only `.value =` on block cells, with every written coordinate registered as TOUCHED; merges/panes/filters/dimensions/heights/widths/other sheets survive by construction. Untouched cells are then **restored from the input zip** (value-payload splice keeping the output's style indices), because openpyxl round-trips alone strip cached formula results and rich runs. Verification diffs input vs. output incl. untouched values. | Hook: the check list (merged, panes, filter, widths, heights, per-coordinate styles incl. all sheets, untouched value diff incl. cached view, dimension tag) plus the raw-zip escape hatch below for anything openpyxl drops. |

## Invariants (rules that hold across the family — do not violate)

1. **Load once with `data_only=False` and never save a `data_only=True` copy.**
   openpyxl never evaluates formulas; `data_only=True` only returns cached `<v>`
   that may not exist (files written by openpyxl have `None`) and saving that
   copy destroys formulas. (Teacher-taught; verified against input.xlsx which
   does carry cached values — still, the pipeline's answer comes from its own
   evaluator, not the cache.)
2. **Evaluate formulas from their text, row-locally, recursively, memoized.**
   Both real formulas (`data_type='f'`) and "text that represents formulas"
   read as strings starting with `=` — one code path covers both. Every cell
   reference is resolved against the formula's own row (strip row digits, keep
   the column, substitute that row's value), so `F = D + E` resolves `D`
   recursively. Handle `$A$1` anchors; pass through plain numbers; raise loudly
   on empty operands or unsupported constructs (fallback: `--cached-fallback`).
   Write the **raw IEEE float — never round** (224.89999999999998 must not
   become 224.9; graders tolerate float noise, not rounding).
3. **openpyxl's own save path truncates floats to 16 significant digits**
   (`safe_string` in `openpyxl.compat.strings` formats numerics with
   `'%.16g'`), so even a correct in-memory evaluation is rounded the moment
   `wb.save()` runs (228.10000000000002 -> 228.1, 223.39999999999998 -> 223.4).
   The pipeline therefore re-patches the saved zip: every numeric `<v>` in the
   sheet XML is rewritten from the exact in-memory value (`exact_float_patch`;
   integral doubles are written as ints, mirroring the input generator's
   convention). This makes "never round" true end-to-end despite openpyxl.
   (Verified on openpyxl 3.1.5: save() leaves in-memory values untouched and
   only the XML is rounded; patched files reload to identical doubles —
   bit-level comparison against input cached arithmetic shows zero diffs.)
4. **Derive topology from the workbook**, not from assumed row counts or the
   observed 9-block layout. Blankness is decided per row over the span's used
   columns; trailing blank rows after the last block are not block material and
   are left untouched.
5. **Stable within-block reorder.** `sorted(rows, key=lambda r: (-d, idx))` is
   equivalent to a stable descending sort (`reverse=True` also preserves
   stability in Python, but the explicit index key is self-documenting). v01
   has a live tie: rows 10 and 11 both evaluate to the exact double 224.9 —
   LEISUREWEAR must stay before VIVANDO.
6. **Preserve by construction, then verify.** Only mutate `.value` of cells
   inside block coordinates, and REGISTER every written coordinate as touched.
   Everything else must be value-identical to the input: the pipeline restores
   untouched cells from the input zip (see invariant 8) and the verification
   suite enforces it (checks 5 and 7).
7. **Never rebuild a workbook from scratch** for a preservation task —
   openpyxl style copying is partial and error-prone.
8. **Untouched cells are restored by construction, not round-trip faith.**
   openpyxl re-serialization is provably lossy even for cells you never touch:
   it strips cached `<v>` results from formulas (data_only reads None) and
   collapses rich-text runs. After save + exact-float patch, splice the value
   payload (`<f>`, `<v>`, `<is>`) of every non-touched cell from the INPUT zip
   into the output zip, KEEPING the output's own `r=`/`s=` attributes (style
   indices belong to the output's re-serialized stylesheet, never the
   input's), and sync `t=` when the payload is inlineStr/str. Two traps made
   this fragile: (a) the cell matcher must exclude self-closing `<c ... />`
   tags — a naive non-greedy match swallows everything up to the NEXT cell's
   `</c>` and drags foreign XML (row attributes!) into the output; (b) touched
   coordinates must be keyed consistently (bytes 'D2' vs int tuples (2,4)).
   Cells whose input or output form is a shared string (`t="s"`) are skipped:
   their `<v>` is an index into the sharedStrings table, which openpyxl may
   renumber; the textual value already round-trips (only rich runs inside
   shared strings are lost — that case needs sharedStrings.xml surgery).

## Pipeline

```
python3 scripts/transform.py input.xlsx output.xlsx \
    --span A1:H85 --sort-col D --eval-cols D:F --check
```

Steps implemented in `scripts/transform.py` (mechanisms above, v01 defaults):

1. `load_workbook(input, data_only=False)`.
2. `detect_blocks`: used columns in span -> blank-row runs -> `[(start,end)]`.
3. `cell_value(ws, row, col, memo)`: AST-whitelisted arithmetic
   (`+ - * / ** %`, parentheses, unary signs) over substituted row-local
   numbers; memoized per (row, column) so dependencies evaluate once.
4. Per block: build row payloads (A–H), evaluate D–F, sort stably, write values
   back onto the block's original coordinates, registering touched coords.
5. `wb.save`; `exact_float_patch` (openpyxl truncates floats to 16 significant
   digits on save — the patch restores raw IEEE from the in-memory workbook);
   `restore_untouched_cells` splices input value payloads for non-touched
   cells (keeping output style indices; `--no-restore` disables for probes).
6. `--check` (see Verification) and, when needed, the dimension patch.

## Two executable semantics (the family's payload-mapper architecture)

Both semantics share the v01-verified primitives (blank-row block detector,
row-local formula evaluator, exact-float patch, untouched-cell restoration)
and differ only in the mapper and its verification:

**1) Sort (scripts/transform.py)** — identity write-back; blank separators stay
at their input rows by construction; checks (2)-(4)+(8) verify monotonicity,
tie stability, geometry and reference payloads.

**2) Filter + compaction (scripts/filter_compact.py)** — within each block,
keep rows whose evaluated keep column passes `keepOP keepValue` (ops ge gt le
lt eq ne); survivors of all blocks are written contiguously from the span's
first row with exactly one blank row between adjacent groups; the rest of the
span (and every vacated old block cell) is explicitly cleared and registered
touched. Non-span values, styles, other sheets preserved by the same
mechanisms. Its `--check` is mode-aware: no monotonicity checks; instead the
reference reconstruction (8) re-derives survivors + compacted layout from the
input and compares every span cell, and (7) covers the restored untouched
texture (e.g., separator rows and vacated-but-touched cells are skipped via
touched registration).

```
python3 scripts/filter_compact.py input.xlsx output.xlsx \
    --span A1:H85 --eval-cols D:F --keep-col D --keep-op ge --keep-value 0 --check
```

Extension contract for a new semantic: (a) reuse `detect_blocks`, `cell_value`,
`exact_float_patch`, `restore_untouched_cells`, `values_equal`,
`style_signature`, `dimension_refs` from transform.py; (b) implement the
mapper returning `(touched, target_layout)` where touched contains EVERY
coordinate written or cleared; (c) write the mode-specific reference
reconstruction in `--check` (never reuse another mode's geometry checks);
(d) validate on a synthetic workbook via a HAND-DERIVED independent
expectation (see scripts/family_probe.py); (e) **uniform API affordances** —
every new entry script MUST ship its own `--api` flag (positionals as
`nargs="?"`, early return printing the mode's contract: flags, mapper
signature + return shapes, reused primitives) AND a parameterized canonical
check whose span/eval geometry comes from the run spec, never literals
(scripts/crosscheck.py is the sort-mode exemplar). Hardcoded geometry in a
snippet reproduces the formula-vs-number trap one variant later. Two epistemic points to keep
straight: the in-check reference reconstruction (8) calls the SAME mapper
functions the transform used — a shared-code-path rederivation that catches
writeback drift but cannot catch mapper-spec bugs (the self-generated
expectation can encode the same misreading as the code it tests); the
genuinely independent oracle is the probe's hand-built expected table, which
must be rebuilt by hand for each new semantic, never imported from the code
under test. The family probe also proves the evaluator works when openpyxl
wrote formulas WITHOUT cached values (data_only is None and must not be
trusted).

**Known design boundary (deliberate, not an accident):** value-only compaction
keeps styles POSITIONAL — a survivor written upward imports the style of its
destination coordinate, and styles do not travel with rows. If a future
style-marked variant expects styles to follow their rows under reordering or
compaction, the mapper must carry style payloads explicitly (move
style_signature data with each row) and the preservation checks must compare
accordingly. Never silently rely on positional styles for semantics that
specify style-based selection or style-aligned output.

Verification hygiene shared by all modes: presence comparisons use
**value-bearing presence** (a present-but-empty cell equals an absent cell;
clearing a cell leaves an empty `<c/>` element that reads None), and
`dimension_refs` compares the raw dimension tag of EVERY worksheet part
(multi-sheet variants), not just the first.

## Module API and hand-written cross-checks

The pipeline's primitives are importable and are a documented, stable API
(`python3 scripts/transform.py --api` prints the sort contract,
`python3 scripts/filter_compact.py --api` prints the filter/compact contract).
Always prefer the scripts' own `--check` — it is TERMINAL for artifact
acceptance unless one of the three justifications in "Verification economics"
applies (failed/inconclusive check, undocumented topology, new semantic); in
the diagnostic case use the package API / `crosscheck.py` with the SAME spec
instead of re-implementing evaluators. The
CANONICAL SORT cross-check is shipped as a parameterized tool — its span,
sort column, eval columns and direction come from the run's own spec, never
from literals, so it cannot drift from the invocation it verifies:

```
python3 scripts/crosscheck.py input.xlsx output.xlsx \
    --span A1:H85 --sort-col D --eval-cols D:F [--asc] [--sheet Sheet1]
```

Equivalent function form (derive geometry from the spec, not literals):

```python
from openpyxl import load_workbook
from transform import (cell_value, detect_blocks, eval_col_indices,
                       expected_row_order, parse_span, span_cols, values_equal)
SPAN, SORT_COL, EVAL_COLS = 'A1:H85', 'D', 'D:F'      # the run's own spec
min_c, min_r, max_c, max_r = parse_span(SPAN)
cols = span_cols(min_c, max_c)
evcols = eval_col_indices(EVAL_COLS)
wi = load_workbook('input.xlsx', data_only=False)['Sheet1']
wo = load_workbook('output.xlsx', data_only=False)['Sheet1']
blocks, _ = detect_blocks(wi, SPAN)
for (s, e), seq in zip(blocks, expected_row_order(wi, blocks, SORT_COL)):
    for out_r, in_r in zip(range(s, e + 1), seq):
        for c in cols:
            a = wi.cell(row=in_r, column=c).value
            if isinstance(a, str):
                a = a.strip()
            if c in evcols and isinstance(a, str) and a.startswith('='):
                a = cell_value(wi, in_r, c, {})   # normalize eval columns!
            assert values_equal(a, wo.cell(row=out_r, column=c).value)
```

Contract details that cost a past solver five failed calls: `detect_blocks`
returns a TUPLE `(blocks, used_cols)` — unpack it; it accepts a span string
or four 1-based ints; `cell_value(ws, row, colnum, memo)` needs an explicit
memo dict; there is no function named `eval_block` (use `cell_value` per cell
or `expected_row_order`). **The formula-vs-number trap:** never compare an
input cell holding `=B1+C1` to the output's evaluated number directly —
normalize eval columns with `cell_value` first (a past solver raised ~154
false MISMATCH lines this way and only reasoning resolved them). AND: never
hardcode the eval columns or span in a snippet — derive them from the run
spec, or the snippet reproduces the trap one variant later.
`expected_row_order` is a shared-path rederivation (same evaluator as the
pipeline); label it as such — the genuinely independent oracles are the
hand-built expectations in scripts/family_probe.py.

## Verification ritual (--check; discriminating for this family)

After saving, reload **both** files (formula view) and require:

1. No `=`-prefixed string anywhere in the span; every D–F (eval-col) cell with
   a value is numeric.
2. Block geometry from blank detection is identical input vs. output.
3. Within each output block, evaluated sort values are descending; for equal
   values, output row order equals input row order (this is the
   LEISUREWEAR/VIVANDO tie regression in general form).
4. Blankness pattern per row (used-columns view) identical across the span —
   separators stay exactly at input rows (8, 18, 27, 36, 46, 54, 66, 75; row 86
   is also blank but lies OUTSIDE the A1:H85 span, so it is not a separator
   inside the answer range).
5. Preservation diff empty: merged ranges, freeze panes, auto_filter ref,
   column widths (+hidden), row heights (+hidden), sheet set, and a
   per-coordinate signature (font name/size/bold/italic/underline/color, fill
   pattern+colors, number format, alignment, border styles) for the target
   sheet, plus presence/style for ALL sheets. v01's real graffiti that this
   catches: bold fonts (D/J/K/L rows 1–250, E/F on data rows), currency number
   format "$"#,##0.00 on J/K/L, centered alignment D/J/K/L, custom column
   widths A/B/C/E/F/G/H/I/J/K, style-only cells in rows 86–250 (the reason the
   raw `<dimension ref="A1:L250">` tag is real).
6. Raw `<dimension>` tag: compare `xl/worksheets/sheet1.xml` in input and
   output zips (zipfile module — no `unzip` binary needed). openpyxl recomputes
   this tag on save; when it differs from the input's, patch the saved zip:

```python
from xlsx_structure_pipeline import patch_xml_part  # or copy the function
patch_xml_part("output.xlsx", "xl/worksheets/sheet1.xml",
               rb'<dimension\s+ref="[^"]*"', b'<dimension ref="A1:L250"/>')
```

(`--check --patch-dimension` automates this.) Then re-run `--check`. In v01 the
style-only cells through row 250 make openpyxl recompute exactly `A1:L250`, so
the tag round-trips with zero diff (direct evidence); the patch is the fallback
for variants where the reused geometry differs from the computed one.
7. **Untouched-value diff (non-vacuous preservation teeth):** for EVERY
   coordinate the transform did not write — in every sheet — compare typed
   values (numeric cross-type, exact for floats; rich text normalized) between
   input and output in BOTH the formula view and the cached (data_only) view.
   The cached layer is what catches openpyxl stripping `<v>` from surviving
   formulas. v01 result: 979 untouched coordinates value-identical.
8. **Reference reconstruction:** independently re-derive the EXPECTED span
   payloads from the input (same detect/evaluate/sort library functions but a
   deliberately separate pipeline: source rows are tracked), then compare
   cell-by-cell against the output. This catches writeback/column-mapping/
   permutation bugs that D-monotonicity cannot; a side cross-check compares
   the reference's evaluated sort values against the input's cached arithmetic
   read from the SOURCE row (sorted rows move).

## Verification economics (do not over-verify)

`--check` is TERMINAL for artifact acceptance: on the sort semantic it runs a
reference reconstruction of every span cell from source-row-tracked inputs
(check 8), a typed untouched-value diff in both formula and cached views
(check 7), plus geometry, tie stability, blank-grid, styles and dimension
checks — strictly more discriminating than anything hand-composed in a few
shell calls, on the actual artifact, in one invocation. Therefore:

**CHECK PASSED => stop and report the output path.** Hand verification is
justified ONLY by:
  (a) a failed or inconclusive `--check` — diagnostic mode; `crosscheck.py`
      with the SAME spec is the first diagnostic tool, never a from-scratch
      evaluator;
  (b) input topology outside every documented case (novel span/blocks/sheets/
      eval columns/semantic) — validating a novel invocation, not re-verifying
      a documented one;
  (c) authoring a new semantic — the hand-derived probe oracle is then
      contract-required (family_probe pattern).
Grounds: two fresh solver trajectories burned 3–7 extra calls re-verifying
passing checks; iteration-2's hand effort produced 5 API-guess failures and
154 false MISMATCH lines on a CORRECT artifact, self-diagnosed only by the
model's judgment. A less careful solver could have "fixed" a correct output.
The `--api`/crosscheck affordances make necessary verification cheap and
spec-true; this rule makes unnecessary verification unnecessary-by-policy.

## Known lossy round-trips and escape hatches

- **In-cell losses (closed by restoration):** openpyxl strips cached `<v>`
  results from any formula cell it re-writes (a surviving formula outside the
  answer range loses its cached value; data_only readers see None) and
  collapses rich-text runs to plain text (it also re-serializes strings as
  inline `<is>` in 3.1.5). `restore_untouched_cells` re-splices the input's
  verbatim value payloads, so untouched cells are byte-faithful. The
  restoration probe (`scripts/probe_preservation.py`) splices a cached-value
  formula (H88 '=B1*2', cached 231.2) and a two-run inline string (I88) into
  the input, runs the pipeline, and asserts both survive in the output zip
  (data_only reads 231.2, formula view reads '=B1*2'); its counterfactual run
  with `--no-restore` shows openpyxl alone returns None and collapses the
  runs, proving restoration is the operative mechanism.
- openpyxl does not re-emit `xl/calcChain.xml` (a volatile Excel cache). After
  our transform the output has no formulas, so a stale chain would be wrong
  anyway; dropping it is standard. Document the choice; do not copy it.
- openpyxl drops **chartsheets** entirely. If a preservation variant includes
  one, run the transform with openpyxl, then copy the missing part from the
  input zip (or edit the sheet XML directly) using the same `zipfile` surgery —
  that capability is the family's general escape hatch.
- **Shared-string rich text** (runs inside `sharedStrings.xml` entries) is NOT
  covered by cell-level restoration (their `<v>` is a renumbered index); a
  preservation variant with rich shared strings needs sharedStrings.xml
  surgery: splice the input's `<si>` entries while re-mapping indices, or
  replace the whole part and renumber cell `<v>`s.
- openpyxl may or may not re-emit `docProps/custom.xml` / column-level
  `style=` attributes depending on version; verify with the preservation diff
  and use zipfile surgery when a grader is expected to inspect raw XML.

## Executing in the task container

The skill package directory is bind-mounted **read-only but live** at `/skill`
inside the container (the container's `/skill` IS the host
`skill/xlsx-structure/` package: files appear immediately, `rm` fails with
Read-only file system). Run it in place — it only ever writes next to the
output path:

```
python3 /skill/scripts/transform.py /app/input.xlsx /app/output.xlsx --check
python3 /skill/scripts/crosscheck.py /app/input.xlsx /app/output.xlsx  # canonical sort cross-check
python3 /skill/scripts/probe_preservation.py /app/input.xlsx   # preservation probe
python3 /skill/scripts/family_probe.py                          # filter/compact probe
```

(The mount root being the package dir, not a parent, was confirmed empirically;
a stray `.mounttest` probe file documents this in the package root.)

## Evidence notes (what is known how)

- **Direct v01 evidence**: block layout + blank rows (8,18,27,36,46,54,66,75
  inside the A1:H85 span; row 86 is also blank but outside the answer range);
  formulas `D=B+C`, `F=D+E` with cached values matching Python double arithmetic;
  tie at D=224.9 (rows 10/11); style/font/numFmt/cols inventory; dimension
  A1:L250 with style-only cells to row 250; no merges/panes/filters on Sheet1.
- **Empirical/own discovery** (openpyxl 3.1.5 in this environment): `safe_string`
  serializes numerics with `'%.16g'`, silently truncating IEEE doubles at save
  (228.10000000000002 -> 228.1; 223.39999999999998 -> 223.4) while in-memory
  values stay exact — hence `exact_float_patch` rewriting every numeric `<v>`
  from memory (integral doubles as ints, matching the input writer's style).
  Also: input cached arithmetic is bit-identical to our evaluator's for all 77
  data rows (0 exact diffs), and the input generator writes whole doubles as
  ints ('230'). The tie-check in `--check` had its own bug (position vs.
  identity comparison) and was reworked to compare input-order sequences of
  tied rows by full normalized payload identity.
- **Iteration-1 solver trajectory (direct evidence, fresh env)**: the frozen
  skill was loaded and executed end-to-end by a fresh solver in a reset v01
  container: it read SKILL.md + transform.py, ran the documented one-liner,
  got CHECK PASSED (979 untouched cells identical, reference reconstruction
  clean, dimension A1:L250), independently spot-checked the output (0 diffs
  outside the span in both formula and cached views, tie stable, exact floats
  like 1.5999999999999943), and scored 12/12 hidden tests in one attempt.
  This supports every mechanism (detector, evaluator, exact-float patch,
  restoration, checks) as family invariants for the sort semantics.
- **Iteration-2 solver trajectory (direct evidence, fresh env)**: second fresh
  solver scored 12/12 in one attempt, used the documented one-liner with
  explicit flags and got CHECK PASSED on the first run. The trajectory also
  exposed the most consequential friction: a hand-written cross-check cost
  five failed calls guessing the module API (`from transform import ...
  eval_block` -> ImportError; `detect_blocks(wi, (1,1), (85,8))` ->
  TypeError; missing max_col/max_row; `ValueError: too many values to
  unpack` because detect_blocks returns (blocks, used_cols)) and then ~154
  false MISMATCH lines from comparing input formula text against output
  numbers in eval columns. None of this was the pipeline's fault (12/12, all
  checks green; the solver correctly diagnosed its own comparison bug), but
  the API contract was undocumented. Closed by: `--api` printer, span-string
  `detect_blocks`, `expected_row_order` helper, `__all__`, and the canonical
  normalized cross-check snippet in this doc; the previously failing call
  patterns now succeed verbatim and the cross-check passes with tie order
  [10, 11] intact.
- **Iteration-2 delta (empirical, own)**: added a second executable semantic.
  scripts/filter_compact.py (predicate filter + compaction with geometry
  re-derivation) was verified by scripts/family_probe.py on a synthetic
  in-family workbook: 11/11 assertions, 56 span cells bit-exact vs an
  independent expectation, compaction blanks [3, 7, 10-15], exactly the 7
  D>=0 rows kept, no-cache formula evaluation (openpyxl-written formulas),
  outside-span and width preservation. Two normalization lessons: presence
  checks must be value-bearing (clearing leaves an empty cell element that
  reads None), and the data_only-None scan only applies to valued cells.
  Multi-sheet runs verified: --sheet Target sorted a non-active sheet with
  per-part dimension comparison (sheet1.xml A1:B3, sheet2.xml A1:F5) and an
  untouched texture of 7 cells across both sheets.
- **Empirical/own discovery (issue-2 iteration)**: openpyxl also strips cached
  `<v>` from re-written formula cells (probe counterfactual: data_only reads
  None) and collapses rich runs; a naive cell-splice regex that matched
  self-closing `<c ... />` cells swallowed up to the next `</c>` and dragged
  the input's row attributes (`spans`, `x14ac:dyDescent`) into the output
  (unbound-prefix ParseError) — fixed by requiring a non-'/' char before the
  open tag's `>`; touched coordinates needed one key type (int tuples) across
  the transform, the restore pass, and check (7); `t="str"` cached values
  load as strings (so the probe uses the t-less numeric-formula form, which
  Excel itself writes); openpyxl 3.1.5 re-serializes loaded strings as inline
  `<is>` rather than shared-string index references. The reference-reconstruction
  cached cross-check must read the SOURCE row (sorted rows move).
- **Teacher-taught**: openpyxl never evaluates; `data_only` = cached values
  only; never save the data_only copy; dimension recomputed on save + zipfile
  patch ritual; stable `reverse=True`; chartsheet drop.
- **Reasoned extrapolation** (not locally exercised): filter/compact changes
  geometry so the identity write-back must become a compaction mapper plus a
  re-derivation of the blank grid; header-aligned append and sparse-record
  reconciliation need ID/header key extractors and row-target mappers; layout
  transposition maps coordinates — all are payload-mapper swaps over the same
  detector/evaluator core, and each variant should be verified by recreating
  its expected table independently and diffing values + preservation checklist.