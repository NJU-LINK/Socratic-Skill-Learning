---
name: xlsx-structure
description: >-
  Structural transformations of Excel .xlsx workbooks (block-local sorting,
  predicate- or style-based filtering and compaction, header-aligned append,
  sparse-record reconciliation, row extraction, layout transposition) with
  strict preservation of everything else. Two-mode openpyxl load rule
  (mutate the formulas-mode workbook, cache-mode read-only), row-local
  evaluation of task-declared formula columns under Excel precedence, opaque
  row-unit snapshot writes, in-place editing, and a full verification battery
  (precedence probes, hard bit-equality vs cache, block/multiset identity,
  outside-range feature diff, raw-XML expectations).
---

# xlsx-structure

Structural transformations of Excel `.xlsx` workbooks: block-local sorting,
predicate/style-based filtering and compaction, header-aligned append,
sparse-record reconciliation, row extraction, and layout transposition —
with strict preservation of every workbook state outside the declared
transformation.

## When to use

The task names an input workbook, a *structural* relation over its tables
(sort/filter/append/reconcile/extract/transpose), a selection or alignment
rule (numeric order, membership, header/ID identity, fill color, text
predicate, source-list order, positional correspondence), an output geometry
(existing or new sheet/range, orientation, append or compaction boundary),
and an explicit preservation clause (sheets, values, styles, dimensions,
filters, merges, panes, row heights, column widths). Workbooks are
openpyxl-readable `.xlsx`; formulas may be present in the data columns and
must be evaluated, not preserved as formulas, in the answer range.

## Non-negotiable architecture (evidence: v01 verified + Teacher-taught)

1. **Two-mode load rule.** Mutate and save ONLY a workbook loaded with
   `data_only=False` (it keeps formulas, styles, features). Load a *second*,
   read-only workbook with `data_only=True` purely as a cached-value
   reference for cross-check/fallback. **Never save a `data_only=True`
   load**: openpyxl then serializes cached values and silently deletes every
   formula in the file — including ones outside the answer range that you
   were told to preserve.
2. **Self-evaluate scoped to the task-declared formula columns — don't trust
   the cache.** Compute evaluated values with your own row-local arithmetic
   evaluator (`+ - * / ^ %`, parentheses, unary minus, same-row cell
   references resolved recursively with memoization). Evaluation is scoped to
   the columns the task declares formula-bearing (v01: D–F); *outside* those
   columns a string such as `"007"` or `"E2"` is data — preserve its value
   **and type** exactly, never treat it as arithmetic. Within the declared
   columns, strings that start with `=` or fully parse as arithmetic count as
   formulas ("text that represents formulas") and are written as plain
   numbers. Treat cached values only as a cross-check.
   Bit-exactness is a *hard assertion, not an assumption*: for `+ - * /` of
   stored doubles, Python reproduces Excel's cached doubles bit-for-bit only
   when evaluating the same operation sequence under Excel precedence. The
   evaluator must implement Excel semantics: negation binds tighter than `^`
   (`=-2^2` → 4), `^` is LEFT-associative (`=2^3^2` → 64, unlike Python's
   right-assoc `**`), `%` binds tightest (`=50%^2` → 0.25). The verification
   battery runs precedence probes and asserts parser output == cache exactly
   (`==`, not `isclose`) for every input formula; **any mismatch is an
   evaluator bug (precedence/fold/%), never rounding noise** — trust the
   cache over the docstring, fix the parser (v01: 0 mismatches over 154
   formula cells).  SCOPE of the doctrine: bit-equality is the evaluate-leg
   guarantee for BARE arithmetic of stored doubles (identical IEEE-754 op
   sequence on identical operands is deterministic).  Function-bearing
   formulas (SUM/AVERAGE/... over ranges) have NO such guarantee: engines
   do not document accumulation order, and engine caches may be quantized
   (15 significant digits) — those check by 1e-9-relative tolerance
   (verify check B2), never bitwise.  Note the two legs: the EVALUATE leg
   is bit-exact in memory; the SERIALIZE leg is lossy by ≤1 ulp for
   17-significant-digit doubles because openpyxl writes numerics with
   `%.16g` (see Environment facts) — reloaded-vs-computed comparisons need
   tolerance, never bit-exactness or type-strictness.
3. **Opaque row units + snapshot before write, at BOTH granularities.**
   Any reorder/compaction must treat each row as a unit: cell state
   (value, `data_type`, `_style` (StyleArrays are immutable;
   reference-sharing is openpyxl's native dedup), `_hyperlink`, `_comment`)
   AND row-level state (`row_dimensions`: height, customHeight (derived),
   hidden, outlineLevel, collapsed, row style `s`, customFormat (derived),
   thickBot/top).  Row dims move with the content (Excel row-sort
   semantics) — they do NOT stay positional — and must be snapshotted from
   the pristine worksheet BEFORE any write: a live read mid-write sees
   already-traveled dims (the checkpoint-2 corruption class at row
   granularity).  Travel mechanics (probed on 3.1.5): `.s`/`style_id` has
   NO setter — copy a non-default row style with `rd._style =
   wb._cell_styles[d.s]`; `s == 0` is the implicit default and must not be
   re-applied; `customHeight`/`customFormat` derive from ht/s and travel
   implicitly; `ws.row_dimensions.get(r)` is the side-effect-free read
   (no auto-create), `ws.row_dimensions[r]` auto-creates.  Never read
   live cells during the write phase — earlier destination writes
   overwrite rows that later destinations still need as sources (v01 bug:
   "key column right, everything else wrong": D/F came from the precomputed
   dict while A–C, E, G, H were read from already-rewritten rows).
4. **In-place editing only.** Reorder by writing values back into the
   original row numbers. Never `delete_rows`/`insert_rows` (shifts destroy
   row heights, merged ranges, panes), never recreate sheets, never touch
   cells outside the declared answer/insertion range. Blank separator rows
   are never written, so "exactly one blank row between blocks" holds
   automatically.
5. **Stability is explicit.** For descending order use
   `sorted(rows, key=lambda r: (-evaluated[r], r))` — ascending by the
   negated key with the original index as an explicit tie-break. For
   ascending order use `(evaluated[r], r)`. Do not rely on `reverse=True`
   subtleties or on value-keyed lookups (ties make them ambiguous).
6. **Merged-range guard.** openpyxl raises when writing a cell that is a
   non-anchor member of a merged range. Check `ws.merged_cells.ranges ∩
   write-range` before writing. Merges usually lie outside the answer range
   (the preservation clause exists because of them) — leave them untouched.
   If a merge DOES intersect the write range (unverified in v01 — v01 has no
   merges; strategy implemented in scripts/solve.py): unmerge before
   writing, remerge after, with each merge traveling with its anchor row's
   content (Excel row-sort semantics): rows move to
   `dest_of[anchor_row] .. dest_of[anchor_row] + span`; merges whose anchors
   sit outside the sorted blocks stay put. Merge geometry (sorted range
   strings) is part of the verification battery.
7. **Regenerate, never transform the output.** If the first attempt is
   wrong, re-run from the pristine input; transforming already-transformed
   output just re-permutes the corruption.

## Workflow

### 1. Inventory (before touching anything)

- List sheets; for each sheet record `max_row/max_col`, `ws.dimensions`,
  `merged_cells.ranges`, `auto_filter.ref`, `freeze_panes`,
  `row_dimensions` heights, `column_dimensions` widths, and workbook
  `defined_names`.
- Scan the cell table (`ws._cells`) not just `ws.cell()` probes:
  - cells with values (both modes: `data_only=False` for formula text +
    `data_type`, `data_only=True` for cached values),
  - **styled-but-empty cells** (`has_style and value is None`) — these
    legitimately extend `dimensions` to e.g. A1:L250 while holding no
    values (v01: 915 such cells in J1:L250).
- Identify the answer range and the transformation columns from the task
  text; identify fingerprint columns if any (e.g. block id / in-block
  position columns) — they let you verify permutations exactly.
- Record the <dimension> tag from raw XML
  (`zipfile.ZipFile(path).read('xl/worksheets/sheet1.xml')`) — it is
  *metadata*, not truth; a stale tag can claim A1:L250 with no content.

### 2. Plan the semantics

- Parse the transformation from the task: which blocks/ranges are selected,
  by what rule (evaluated numeric order, membership in another range,
  header/ID identity, fill color, text predicate, source-list order,
  positional correspondence), and what the output geometry is (existing
  range written in place, append below existing data, new sheet, transposed
  orientation).
- Identify the DECLARED formula-bearing columns from the task text (v01:
  "Columns D–F may contain formulas or text that represents formulas") —
  evaluation scope = those columns ONLY. Any cell with `data_type == 'f'`
  or a string starting with `=` or fully parsing as arithmetic inside those
  columns is evaluated; a bare reference like `B2` without `=` is NOT a
  formula (protects plain text names); a bare number is converted.
- Define the row unit and the destination rows (same set of row numbers for
  sort-in-place; subset for filtering/compaction; new rows below an
  existing table for append; transposed coordinates for transposition).

### 3. Transform (see scripts/solve.py for the realized block-sort)

- The transform is a pluggable `TRANSFORM` setting: the default
  `"block_stable_sort"` (KEY_COL, DESCENDING) is the v01 path;
  `"filter_by_key"` and `"append_by_copy"` are SYNTHETIC built-ins
  exercised by toy_tests.py (T5/T6) to prove the machinery — a real
  predicate/geometry variant should be written as a new callable with the
  contract `transform(blocks, snap, evaluated, ws, ref_ws) -> (plan,
  clears)` where `plan` maps dest_row -> src_row (snapshot keys) and
  `clears` lists rows to remove from the grid.  Solver machinery
  (snapshot/evaluate/write/merge-travel/clears) is shared by every
  transform.

- Detect blocks: maximal runs of rows (within the answer range) where at
  least one cell in the range is non-None; a row is a separator when all
  range cells are None. Style-only rows inside the range count as blank
  unless the task keys selection on style.
- Per block: snapshot rows → evaluate formula-like cells in the declared
  columns only (row-local resolver: same-row refs evaluate recursively from
  the snapshot with memo + cycle safety; cross-row refs fall back to cached
  values) → compute one ordering → write every destination row's cells from
  its snapshot source.
- After writing, the DECLARED columns of the answer range must contain
  zero `data_type=='f'` cells and zero `=`-prefixed or arithmetic strings
  (write through the public `cell.value` setter so `_bind_value` sets
  `data_type` correctly; never assign strings that start with `=` — that
  creates a new formula). Other answer-range columns must equal the input
  record's values bit-for-bit, type included.
- Styles travel with row content (Excel row-sort behavior): copy `_style`
  per cell from the snapshot source. If the column styles are uniform this
  is unobservable (v01: D styled on all 85 rows, E/F styled on data rows);
  if rows carry distinct styles the grader may check the moved styles.
- For filtering/compaction: write the surviving rows in order into the
  destination range (front of the block/table), leaving the tail empty
  (values = None) but styles per surviving rows; keep everything else
  untouched. Verify the dropped-set exactly.
- For append: destination rows are the first empty rows after the existing
  table; write only there; existing rows are never rewritten.
- For transposition: same snapshot discipline with (row,col)↔(col,row)
  destination mapping; verify orientation swap and that the source range
  itself is untouched unless the task says otherwise.

### 4. Verify (scripts/verify.py implements the full battery)

- Reload the OUTPUT in both modes. Asserts:
  1. Declared formula columns of the answer range: NO FORMULA ARTIFACTS —
     zero `data_type=='f'` cells, zero `=`-prefixed or formula-like
     strings.  Preserved non-formula values (numbers, text like "N/A",
     None) are contract-satisfying: the task forbids formula strings and
     unevaluated formulas, not data text.  (Checks C in verify.py; the
     earlier "values numeric" wording was wrong and was removed in
     iteration 3.)  Other answer-range columns: values identical to the
     input record (type included).  Scoped scans only — a legitimate text
     like `"007"` in a non-declared column must NOT be flagged or
     converted.
  2. Block structure: separator rows exactly the input's separator rows;
     block sizes equal.
  3. Transformation property: per block, key values non-increasing
     (descending) / non-decreasing, ties in original relative order —
     verified via fingerprint columns (v01: column H = in-block position;
     expected H per block = permutation of the stable sort) or via
     normalized multiset identity.
  4. Multiset identity per block: normalize input rows (declared formula
     columns → evaluated numbers) and compare the sorted multiset of row
     tuples against the output block — catches rows lost/duplicated/swapped.
  5. Everything outside the answer range: values identical; styled-cell
     inventory as a set of (coordinate, style_id) identical (v01: 915
     cells); merged ranges (including merges inside the range after
     unmerge/remerge), auto_filter.ref, freeze_panes, row dims TRAVELING
     with content (rekeyed through the permutation; unmoved rows
     positional), column widths positional, sheet names and defined names
     identical.  v01 evidence for the row-dims check is VACUOUS (zero
     input row_dimensions entries); the property is toy-verified (T5/T8)
     under the declared Excel-row-sort semantics.
  6. Bit-exactness as a HARD assertion, scoped by formula class: evaluate
     every input formula in the declared columns with the parser over the
     production path; BARE arithmetic (+, -, *, /, ^, %) must equal the
     cache with `==` (identical op sequences are deterministic);
     FUNCTION-bearing formulas (SUM/AVERAGE/... over ranges) check with
     1e-9-relative tolerance (check B2) because accumulation order is
     unspecified and engine caches may be quantized.  Any bare-arithmetic
     mismatch aborts as an evaluator bug (precedence / `%` / left-fold
     `^`), not rounding noise.  Unit probes first: `-2^2==4`, `2^3^2==64`,
     `50%^2==0.25`, `2^-2==0.25`, plus function/error-domain probes
     (`=SUM(B1:C1)`, `=MOD(5,0)`->None, `=(-2)^0.5`->None, data strings
     `"N/A"`/`"12:30"` not formula-like).
  7. Serialization-leg drift (check H): reloaded output values vs in-memory
     evaluated values over EVAL_COLS, mapped through the stable permutation;
     assert max abs drift ≤ 1e-9. v01 observation: 24 EVAL_COLS cells (all
     D/F) drift at ≤5.7e-14 (e.g. F7, D2, ALBAYAADER's D
     `1.5999999999999943`→`1.599999999999994`) — 17-significant-digit
     doubles under `%.16g`. The count is diagnostic, not a spec value; the
     threshold is the guarantee. Any cell outside EVAL_COLS or drift >
     ~1e-12 means the pipeline broke.
- Raw XML expectations (observed v01):
  - `<dimension ref>` survives IF styled-empty cells are serialized
    (`<c r="L250" s="7" t="n"/>`); if nothing extends the range, a stale
    tag collapses to the true used range — expected for any openpyxl
    reference. Do not "fix" the dimension by fabricating cells.
  - `xl/calcChain.xml` is dropped on save — correct and desirable (the
    answer range has no formulas left).
  - openpyxl 3.1 serializes strings inline (`t="inlineStr"`) even when the
    input uses `xl/sharedStrings.xml`; values are openpyxl-equivalent.
  - The ONLY non-deterministic output entry is `docProps/core.xml`:
    openpyxl refreshes `dcterms:modified` on save (creator/lastModifiedBy/
    created are preserved). Two saves of identical content differ only in
    that timestamp — compare zip entries, not raw files, when verifying
    reproducibility.

## Variation axes (spec.yaml) and how to handle them

| Axis | Realized in v01 | Handled by |
|---|---|---|
| transformation_semantics | block-local stable sort by evaluated column D, descending | snapshot+opaque-row-unit core; pluggable `TRANSFORM` (default block sort; filter_by_key/append_by_copy built-ins toy-exercised in toy_tests.py T5/T6; custom callables with the (plan, clears) contract) |
| workbook_topology | one sheet, blank-row-separated blocks, contiguous A1:H85 | block detection from the workbook; topology variants (sparse ranges, ID lists + sparse tables, style-marked cells) reduce to scanning `_cells` + the named ranges in the task |
| selection_and_alignment_rule | evaluated numeric order with tie stability | stable sort on evaluated key; membership/ID/header/predicate rules are different key functions over the same evaluated row units; fill-color selection reads `cell.fill` from the styles-mode workbook |
| output_geometry | existing Sheet1, in-place A1:H85 | in-place write to original row numbers; append = write to first empty rows; new sheet = `wb.create_sheet` (or `wb.copy_worksheet` when the new sheet must inherit existing styles) |
| preservation_constraints | blank separators, 915 styled-empty J:L cells, column widths | never touch out-of-range cells/features; diff the full feature inventory in verify |

Coverage note: v01 directly verified the sort + evaluation + preservation
mechanisms. Filtering, append, reconciliation, extraction, and
transposition are spec-declared variations of the same architecture; their
verification procedure is: (a) define surviving/destination rows from the
task rule, (b) reuse snapshot/evaluation/write discipline, (c) extend the
battery with the task-specific property (dropped-set equality, appended
boundary, matched-ID equality, transposed coordinates). Do not claim v01
evidence for them.

Identified family boundary — separator normalization: v01 has exactly one
blank row between blocks (verified repeatedly), so the clause "retain
exactly one blank row between adjacent blocks" is a no-op here.  A variant
with variable-length blank runs would require NORMALIZING separators to
one blank row.  The mechanism is a ROW MOVE, expressed with the same
pluggable-transform machinery as T5/T6: build
`plan{src_row -> src_row - k}` over the compacted layout plus `clears` for
the freed blank rows — NOT delete_rows/insert_rows and NOT an ad-hoc
"shift subsequent rows up" loop (both destroy merges/panes/row heights;
the same reason non-negotiable #4 bans the row-shifting APIs applies to
hand-rolled shifting).  Row-dim travel becomes load-bearing the same day:
content moving across row coordinates must carry heights/hidden/banding
(v01-style styled blank rows must keep exactly one styled blank row per
gap).  NOT locally exercised; future verification: build a toy with 2-3
blank rows between blocks, assert exactly one blank row remains per gap,
every data row's content+style+row-dims intact via the transform's map,
and the feature inventory unchanged except the declared separator
changes.  (Preservation checks over row-unit attributes ALWAYS compare
through the transform's row map, never by coordinates.)

## Failure modes seen / to avoid

- Saving a `data_only=True` workbook → all formulas (including preserved
  ones outside the answer range) silently become static values.
- Reading live cells during a row-reorder write phase → permutation
  corruption; symptom: key column correct, other columns scrambled,
  duplicates of some rows and loss of others.
- Value-keyed lookups under ties (e.g. mapping D value → row) → wrong rows
  on 224.9/111.9/112.6-style ties.
- Treating `ws.dimensions` as truth → you may "discover" phantom content or
  panic that styled-empty cells were lost; probe `_cells` and raw XML
  instead.
- Regex "no formula" checks that miss `t="n"` attributes, or row-wise
  value diffs after a reorder (rows legitimately moved) → false alarms;
  verify per-record identity with fingerprint columns / normalized
  multisets.
- Leaving a `=`-prefixed string in the answer range → grader counts it as
  an unevaluated formula.
- Applying the arithmetic parser outside the task-declared formula columns
  → text IDs like `"007"` or `"E2"` silently change type to numbers.
- Ad-hoc checkers that fake their own evaluation: they miscompute when they
  read output positions instead of the input snapshot, or when they key on
  `evaluate_block`'s memoized dict for NON-EVAL columns (the resolver
  memoizes same-row numeric cells referenced by formulas as floats, while
  non-declared columns are correctly written verbatim from the snapshot —
  int vs float there is a checker artifact). When an ad-hoc check disagrees
  with scripts/verify.py's production-path battery, debug the CHECKER
  first: recompute its expectation from the input snapshot at the source
  row. (Observed in the iteration-1 fresh-solver replay: a self-built
  checker reported "ORDER MISMATCH"/"exp 230.0 got 230" for most blocks
  while verify.py and the 12/12 hidden tests were green; both reports were
  checker artifacts.)
- Comparing reloaded numbers bit-exactly or type-strictly → false alarms:
  the writer's `%.16g` drops 1 ulp from 17-digit doubles (F7/D2 in v01) and
  turns integral floats into decimal-free strings that reload as ints.
- Implementing `^` right-associatively (Python `**` habit) or unary minus
  looser than `^` → `2^3^2` / `-2^2` diverge from every Excel-compatible
  engine the moment a variant contains `^`; the bit-equality assertion
  catches it only if you RUN it.
- Classifying formula-likeness by TOKENIZEABILITY instead of PARSEABILITY:
  with an extended tokenizer, data strings like `"N/A"`, `"12:30"`,
  `"E2/TAX"` tokenize and would be misread as formulas → crash or silent
  cache overwrite.  Classification must be by full lenient parse
  (`is_formula_text` uses a lenient resolver where every ref/range
  resolves): only strings that genuinely parse are formulas; bare refs,
  bare words, and parse-failing mixed text stay data.
- Allowing math-domain failures to escape as non-EvalError exceptions:
  `MOD(5,0)`, `1/0`, `0^-1`, and `(-2)^0.5` raise ZeroDivisionError or
  produce complex in Python — guard each as EvalError (`#DIV/0!`/`#NUM!`)
  so evaluation falls back to the cache or aborts loudly, instead of the
  pipeline dying at save time with a complex value in a cell.

## Artifacts

- `scripts/solve.py` — parameterized solver (configure INPUT/OUTPUT, SHEET,
  answer range, KEY_COL, DESCENDING, EVAL_COLS, MERGE_POLICY, and the
  pluggable TRANSFORM at the top; evaluator implements Excel precedence
  with left-associative `^`, plus functions SUM/AVERAGE/MIN/MAX/PRODUCT/
  COUNT/ABS/INT/ROUND/MOD and single-row ranges; snapshot/opaque-row-unit
  write discipline; unmerge→write→remerge for intersecting merges;
  classification-by-parse is_formula_text).
- `scripts/verify.py` — full verification battery (precedence + function +
  error-domain probes; bit-exact B for bare arithmetic, tolerance B2 for
  function cells; hygiene = no formula artifacts; block/multiset identity;
  serialization-drift H; preservation diff; raw XML observations); imports
  the evaluator from solve.py so they cannot drift.
- `scripts/toy_tests.py` — parameterization edge-case unit tests: numeric
  KEY_COL outside EVAL_COLS, non-numeric key aborts, no-cache formulas,
  function formulas with/without cache, cross-row range abort, synthetic
  filter_by_key and append_by_copy transforms, data-text preservation in
  a declared column, error-domain probes, and row-dim travel
  (height/hidden/banding) in sort (T8) and filter (T5) — expectations
  computed from each toy's own inputs (three expectation bugs were caught
  this way: forgetting the sort in T4's expected order, probing cells
  with ws.cell() before a grid-absence assertion, and assuming no reorder
  in T4).

## Environment facts

- openpyxl 3.1.5 writes numeric cells with `openpyxl.compat.strings.safe_string`
  → `"%.16g" % value` (16 significant digits): integral floats lose `.0`
  (`230.0` → `<v>230</v>`), and 17-significant-digit doubles lose the last
  ulp IN THE FILE (≤~1e-12 in practice; v01 exhibits 24 cells, all D/F,
  at ≤5.7e-14 — e.g. F7
  `-0.29999999999999716` → `-0.2999999999999972`, D2
  `224.89999999999998` → `224.9`, ALBAYAADER's D `1.5999999999999943` →
  `1.599999999999994`). There is NO int-cast/is_integer in the writer.
- The reader (`openpyxl.worksheet._reader._cast_number`) parses decimal-free
  numeric strings as `int`, others as `float` — so the int/float drift is a
  round-trip property, not a save-only one. Policy: reloaded-vs-computed
  numeric comparisons need tolerance (round to ≤10 decimals or 1e-9 abs;
  generous for ≤1-ulp drift), never bit-exact and never type-strict. Sort
  keys use full-precision in-memory doubles and are unaffected.
- Scripts must be recreated inside /app when the /skill mount is absent
  (fresh-solver environments): solve.py+verify.py+toy_tests.py are ~600
  lines total and transcribe cleanly with quoted heredocs; run `python3 -m
  py_compile` after transcription before relying on them.
- openpyxl 3.1.5 `Cell` slots are `('row','column','_value','data_type',
  'parent','_hyperlink','_comment')` — there is no `_data_type`; use the
  public `cell.value` setter (it infers `data_type` via `_bind_value`, and
  a string starting with `=` becomes a formula — never assign one in the
  answer range). `Cell.copy` does not exist in 3.1.x.
- StyleArray objects are immutable and shared; `cell._style = src._style`
  is safe (openpyxl's own dedup model).
- numpy/pandas are typically NOT installed — pure openpyxl + stdlib only.
- Evaluator capabilities (iteration 3, toy-verified, NOT v01-verified):
  functions SUM/AVERAGE/MIN/MAX/PRODUCT/COUNT/ABS/INT/ROUND/MOD and
  single-row ranges (B1:C1) on the formula's own row.  Boundaries (all
  raise EvalError -> cache fallback or loud abort): cross-row and
  whole-column ranges, unknown functions (unknown-function TEXT is treated
  as data, not a crash — hygiene flags it loudly if it lands in a declared
  column), division by zero / MOD(,0) / 0^neg / negative-base fractional
  exponent (#DIV/0! / #NUM! — Python's ZeroDivisionError/complex must
  never escape; complex is guarded because openpyxl dies at SAVE time on a
  complex cell value, far from the formula).

## Evidence log

- Iteration 1 fresh-solver replay (separate model, frozen Skill): passed all
  12 hidden tests (test_outputs: exists + values; test_workbook_contract: 8
  answer-value groups + sheet/value preservation + structure/style
  preservation) on the first attempt, after transcribing the scripts into
  /app. Its trajectory independently confirmed: block sizes [7,9,8,8,9,7,
  11,8,10], separators 8/18/27/36/46/54/66/75, 154 formula cells, 915
  styled-empty J1:L250 cells, dimension A1:L250 survival, calcChain drop,
  and the %.16g/int round-trip mechanism (this section).
- Iteration 2: serialization-leg check H added (≤1e-9 threshold; observed
  24 EVAL_COLS drift cells at ≤5.7e-14); write substitution scoped to
  EVAL_COLS by definition (resolver memoization must not leak into
  non-declared writes); both changes are no-ops on v01 (regenerated output
  byte-identical except docProps/core.xml's `modified` timestamp);
  int/float round-trip mechanism pinned to source (`safe_string` `%.16g`
  writer-side, `_reader._cast_number` reader-side).
- Iteration 2 fresh-solver replay (separate model, frozen Skill): 12/12
  hidden tests again, in 15 tool calls; this time it found the /skill
  mount, copied the three scripts into /app, ran solve -> verify -> toy ->
  spot-check with zero confusion (the %.16g / 24-drift-cell facts were
  used as documented).
- Iteration 3: pluggable TRANSFORM (v01 path preserved byte-identical),
  evaluator extended to functions + single-row ranges, classification
  switched to parse-based (data like "N/A"/"12:30" preserved instead of
  crashing), error-domain guards (division by zero, MOD(,0), 0^neg,
  (-2)^0.5 -> #NUM!), verify B split bare/function + hygiene narrowed to
  formula artifacts.  Row-level state (row_dimensions: height, hidden,
  outlineLevel, collapsed, row style s) declared to travel with row
  content, implemented via frozen rowdims snapshot (`.s` has no setter;
  `_style = wb._cell_styles[n]` is the copy path), and asserted by a
  travel-aware F check rekeyed through the stable permutation (the
  positional row-heights check was removed — it fails on correct output
  under travel semantics).  Toys T5/T8 exercise height+hidden+banding
  travel and ghost-dims removal; T5/T6 exercise the filter/append
  machinery — all SYNTHETIC, NOT v01-verified or hidden-test-verified.
  Zero-op certificate: /app/output.xlsx regenerated with the final
  iteration-3 package is byte-identical to the iteration-3 baseline in
  every zip entry except docProps/core.xml's timestamp.