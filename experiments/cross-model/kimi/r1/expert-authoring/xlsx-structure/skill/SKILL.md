---
name: xlsx-structure
description: >
  Structural transformations of .xlsx workbooks with openpyxl: block-local
  sorting, predicate/style-based filtering and compaction, header-aligned
  append, sparse-record reconciliation by ID, row extraction, and layout
  transposition. Covers layout detection from the workbook, evaluation of
  formulas and formula-like text to numbers, stable selection/alignment of
  records, strict preservation of untouched workbook state (styles, widths,
  merges, filters, panes), and a reload-and-diff self-verification protocol.
---

# xlsx-structure: structural workbook transformations

## What this family is

Each task hands you an input workbook (commonly `/app/input.xlsx`) and an
instruction to rewrite one declared region/sheet by a **structural rule**,
saving to a fixed output path (commonly `/app/output.xlsx`). A hidden pytest
grader checks the transformed region cell-by-cell **and** that everything
outside the transformation survived intact.

Variation axes (from the family spec) — expect any combination:

- **Transformation semantics**: block-local sort; filter + compact by value
  predicate or by style (e.g., fill color); append rows aligned by headers;
  reconcile a sparse table against an ordered ID list; extract rows;
  transpose a layout.
- **Workbook topology**: one or several sheets; contiguous tables; repeated
  blocks separated by blank rows; style-marked cells; ordered ID lists paired
  with sparse tables; sparse source/destination ranges.
- **Selection/alignment rule**: evaluated numeric order; membership in
  another range; exact header or ID identity; fill color; text predicates
  with exclusions; source-list order; positional correspondence.
- **Output geometry**: existing or newly created sheet; declared range;
  append / insertion / compaction boundary; orientation.
- **Preservation constraints**: input sheets, values outside the declared
  range, styles, row heights, column widths, filters, merged ranges, panes.

Family invariants (observed in the anchor case, expected to generalize):

1. The instruction always names exact input/output paths, sheet(s), and the
   answer range. Treat these literals as the contract.
2. Formulas (and text that looks like formulas) in the answer range must be
   **evaluated to numbers**; sorting/comparison keys use those numbers.
3. Everything not named by the transformation must be preserved.
4. Sizes must be **detected from the workbook**, never assumed.

## Step 0 — Parse the contract before touching data

Extract and write down explicitly:

- Input path, output path, sheet name(s), source range, destination range.
- The record unit (row? block? column?) and the separator/boundary rule.
- The selection rule (which records) and alignment rule (which order/where).
- Which columns need formula evaluation, and the final value type required
  (numeric, keep text, etc.).
- The preservation set (everything else, by default).

Re-read the instruction after your first implementation and tick each clause
off — graders encode one check per clause.

## Step 1 — Probe the environment and the workbook

- `openpyxl` is available (3.1.5 observed); LibreOffice, pandas, and formula
  engines (pycel/formulas) were **absent** in the anchor environment — plan
  to evaluate formulas yourself. Re-check per task.
- Load the workbook twice:
  `wb = load_workbook(path)` (formulas as `'=B1+C1'`) and
  `wbv = load_workbook(path, data_only=True)` (cached results, present only
  if a calculating app saved the file). Use cached values as a free
  **oracle to cross-check** your own evaluation — never as sole truth; they
  can be missing (None) or stale.
- Inventory: sheet names/order, used ranges, merged cells, freeze panes,
  auto-filters, column widths, row heights, per-cell styles (font/fill/
  border/number format), cell data types (`'f'` formula vs `'s'` string vs
  `'n'` number). Text cells whose value starts with `'='` are
  text-that-represents-a-formula and must be evaluated too.

## Step 2 — READ phase / WRITE phase separation (the critical rule)

**Finish every read, evaluation, sort decision, and row snapshot from the
pristine worksheet before writing a single cell.** Observed failure: after
overwriting early rows, a later formula evaluation re-read the mutated sheet
and silently picked up already-written values (F of one record computed from
another record's row). The same trap appears if you keep "input" worksheet
handles and read them during verification after mutating — reload from disk
instead. Recipe:

1. READ: detect layout; evaluate all needed cells; snapshot every movable
   record as `[(final_value, style_copy), ...]`; build the complete output
   plan (a list of row snapshots and `None` separators) in memory. For
   in-place rewrites the plan must account for **every row of the declared
   region** — pad short plans with blank-row snapshots so leftover cells
   end up empty in value and style.
2. Sanity-check the plan (length, counts, key order) with asserts.
3. WRITE: replay the plan onto the sheet(s); save.
4. VERIFY from a freshly loaded workbook (Step 5).

## Step 3 — Building blocks (helper script provided)

### Accessing the helper from inside the task container (read this first)

Observed friction in iteration 1: the solver pasted the host-workspace path
(shown by the `read`/`find` file tools) into container code and got
`ModuleNotFoundError` twice. Rules:

- Inside the isolated task container, this skill package is mounted
  read-only at **`/skill/`**. Import with `sys.path.insert(0, '/skill/scripts')`.
- The host-workspace path displayed by file tools is **not visible inside
  the container** — never use it in `task_shell` commands.
- If the import still fails, locate the mount with
  `find / -name 'xlsx_structural.py' 2>/dev/null`. Mount-independent last
  resort: you have already read the script via the host `read` tool — write
  its content verbatim to `/app/xlsx_structural.py` and import from `/app`.

### Utilities (all tested against the anchor case)

- `load_pair(path)` — the two load modes above.
- `make_evaluator(ws)` — memoized recursive `cell_num(row, col)` evaluator:
  real formulas, `'='`-prefixed text, numeric text, `$` anchors, `+ - * /`,
  parentheses, unary minus, rectangular ranges inside aggregates, and
  `SUM/ABS/MIN/MAX/AVERAGE/ROUND`. Unknown functions raise loudly (never
  silently wrong). Evaluate **before** mutating `ws`.
- `row_is_blank` / `detect_blocks` — blank-row-separated block detection
  over exactly the declared columns (values outside the region must not
  count). Blank means `None` or `''`.
- `first_empty_row(ws, col, start)` — append boundary detection.
- `header_index(ws, row, cols)` — exact-text header → column map.
- `fill_key(cell)` — normalized fill identifier for style predicates.
- `snapshot_row` / `write_rows` — move `(value, style)` pairs so per-record
  styles travel with their record; `None` entries write cleared separator
  rows.
- `num_eq`, `diff_region`, `style_signature` — verification helpers.

Decision rules by semantics keyword:

- **Sort within blocks**: `sorted(rows, key=lambda r: ev(r, keycol), reverse=True)`.
  Python's sort is stable, so equal keys keep original relative order —
  exactly what "ties preserve original order" requires, in both ascending
  and descending mode. Sort by **evaluated numbers, never text** ("10" < "9"
  lexically). Use raw float arithmetic on cell values for keys; do not round
  unless instructed (rounding can manufacture or destroy ties). Keep exactly
  the declared separator geometry (e.g., one blank row between blocks) and
  the declared total extent (block content + separators == answer range
  height in the anchor case; verify, don't assume).
- **Filter + compact**: select rows by predicate (value predicate, or style
  via `fill_key(cell)`); write selected rows contiguously from the region
  start; then pad the rest of the region with blank-row snapshots
  (`snapshot_row` of an originally blank row), not bare `None`, so no stale
  values **or stale styles** survive inside the region (observed: compacting
  fill-marked rows leaves orphaned fills behind if you only clear values).
- **Header-aligned append**: read the destination header row, map each
  source column by exact header text (not position), append at the first
  fully blank row below the destination table.
- **Reconcile by ID**: build `{id_value: row_snapshot}` from the sparse
  table; iterate the ordered ID list in its own order; write matches, and
  follow the instruction for missing IDs (leave blank vs skip).
- **Extract rows**: collect matching records in original order unless a key
  order is given; write to the destination sheet/range starting at its
  anchor cell; create the sheet if the instruction names a new one.
- **Transpose**: build the full transposed value grid in memory, then write
  cell-by-cell, copying each source cell's style to its target; merged
  ranges must be unmerged/re-merged explicitly (openpyxl does not transpose
  them).

## Step 4 — Preservation rules

- openpyxl load→save round-trips: cell values, styles, number formats,
  column widths, row heights, merged ranges, freeze panes, auto-filters,
  sheet order. It **drops**: charts, images, pivot caches, VBA (unless
  `keep_vba=True`), and cached results of formulas you leave in place
  (formulas survive; their cached values do not). If the probe finds such
  artifacts in scope, prefer surgical XML editing inside the xlsx zip over a
  full openpyxl round-trip.
- Only the declared answer range/sheet may change. Never "clean up" stray
  values elsewhere; never restyle.
- Style-travel rule: when reordering/compacting records, decide whether
  styles are a property of the **record** (move with it — safe default;
  snapshot value+style together) or of the **position** (leave in place).
  If styles are uniform per column it makes no difference; style-marked
  selection (fill color as the predicate) implies record-level styles.
- Clearing cells: for cells being emptied **inside** the answer region
  (compaction leftovers, separators), write blank-row snapshots so stale
  styles go too; for anything **outside** the transformation, touch nothing
  — neither value nor style.
- Write evaluated results as real numbers (`float`), not strings. Do not
  leave any `'='`-prefixed content — formula or text — in the answer range.
  Booleans/None/dates: copy through unchanged unless the rule says evaluate.

## Step 5 — Self-verification protocol (mandatory before finishing)

Adapt this template (parameters: paths, sheet, region, key rule) instead of
hand-rolling verification — an observed iteration-2 run failed its first
verification attempt on a trivial `NameError` in the hand-written checker:

```python
import sys; sys.path.insert(0, '/skill/scripts')
import openpyxl
from xlsx_structural import *
wb_i, wb_iv = load_pair('/app/input.xlsx')       # pristine, from disk
wb_o = openpyxl.load_workbook('/app/output.xlsx')
wi, wiv, wo = wb_i[SHEET], wb_iv[SHEET], wb_o[SHEET]
errs = []
# (1) oracle: rebuild expected record order/content from the pristine input
#     (e.g. stable sort on cached values wiv, or re-run the predicate) and
#     diff every column of every record against wo.
# (2) no '='-prefixed strings anywhere in the answer range.
# (3) geometry: block/table extents, single-blank separators, region size.
# (4) tie groups: relative order identical to input.
# (5) preservation: diff_region on untouched cells; style_signature on a
#     sample; column widths, row heights, merges, panes, filters, sheets.
# (6) contract: output path exists, workbook opens.
print('ERRORS:', len(errs), errs[:10])
```

Checklist the template implements — reload both output and the pristine
input from disk, then check:

1. **Semantics oracle**: recompute the expected result independently —
   e.g., re-derive order using cached `data_only` values, or re-run the
   predicate from the reloaded input — and diff against the output
   **record by record, all columns, not just keys**. `num_eq` with ~1e-9
   tolerance for floats, exact for text. (Iteration 1 passed its checks
   without this step; it is cheap and is the only check that catches
   wrong-record-placement and evaluation bugs reliably — do not skip it.)
2. **No unevaluated content**: scan the answer range for strings starting
   with `'='` and for unexpected text in numeric columns.
3. **Geometry**: block/table sizes, exactly-one-blank separators, first and
   last used rows, total extent equals the declared range, destination sheet
   exists with the exact required name.
4. **Stability**: for every tie group in the key, relative order equals the
   input's.
5. **Preservation diff**: values outside the answer range identical
   (`diff_region`); style signatures, column widths, row heights, merged
   ranges, freeze panes, auto-filter, and sheet list unchanged; other
   sheets' values identical.
6. **Contract**: file exists at the exact output path; workbook opens
   cleanly with openpyxl.

Observed grader shape (from the anchor run): hidden pytest splits into
answer-value groups plus preservation contracts (`..._sheets_and_unrequested_
values...`, `..._structure_and_styles...`) — both families must pass, so a
perfect transformation with a preservation slip still fails.

Fix and re-verify until every check passes; do not hand-wave a failure.

## Pitfalls (observed or directly implied by the family)

- Reading a worksheet after partially writing it (both during evaluation
  and during "input vs output" comparison) — the #1 observed bug class.
- Assuming fixed block sizes/row counts instead of detecting boundaries.
- Sorting text instead of evaluated numbers; unstable tie handling;
  rounding keys so near-ties collapse.
- Leaving formula cells or `'='` text in the answer range; writing numbers
  as strings.
- Off-by-one in separators (double blanks, missing trailing blank, region
  height drift) and in append start row.
- Header/ID matching by position or by fuzzy text instead of exact
  identity; mismatched whitespace/case — match exactly unless told.
- Numeric-looking text (`'112.5'`) compared as text; convert via the
  evaluator when the rule is numeric.
- Forgetting that `data_only=True` returns `None` when no cached value
  exists — always have your own evaluator as primary.
- Mutating shared style objects instead of assigning `copy(cell._style)`;
  rebuilding styles from scratch and losing number formats.
- Using the host-workspace path of skill resources inside the container
  (they live at `/skill/` there); weak regexes that mangle function names
  like `LOG10` into cell refs — the shipped evaluator guards both.
- Silent fallbacks: an evaluator that returns 0 for an unknown function
  instead of raising makes wrong answers look right. Fail loud, then extend.
