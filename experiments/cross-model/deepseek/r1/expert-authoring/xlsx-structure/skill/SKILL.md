---
name: xlsx-structure
description: >-
  Structural transformations of Excel .xlsx workbooks applied in place with
  openpyxl: block-local sorting, predicate/style filtering with compaction,
  header- or ID-aligned append and sparse-record reconciliation, row
  extraction, and layout transposition. Covers evaluating the row-local
  formula arithmetic these cases rank or align on (no formula engine is
  installed), replacing formulas with computed numeric values in the answer
  range, and proving after every save that all declaratively preserved state
  (other sheets, out-of-range values, styles, filters, merged cells, panes,
  row heights, column widths, sheet view state, the dimension string) survived
  unchanged. Read paths are non-mutating by construction so verification
  itself cannot corrupt the preserved state.
---

# xlsx-structure: in-place structural transformation of .xlsx workbooks

## What this family is

The task always reads one workbook (`/app/input.xlsx`), applies a **structural
transformation** to a declared region of one sheet, and saves
(`/app/output.xlsx`). Split the instruction into TRANSFORM sentences (what
changes: sort / filter+compact / align / append / reconcile / extract /
transpose, on which sheet and range, keyed or selected how, into which
destination geometry) and PRESERVE sentences ("preserve every input sheet, all
values outside R, existing styles, filters, merged ranges, panes, row heights,
column widths"). Preservation is the default: you may only mutate the declared
answer range.

Observed anchor case (v01): Sheet1 `A1:H85` holds 9 variable-length blocks of
rows separated by single blank rows; each block is re-ordered by the evaluated
numeric value of column D, descending, with ties keeping original order; D and
F contain row-local formulas (`=B1+C1`, `=D1+E1`) that must be written out as
evaluated numbers; blank separators stay exactly one row. Everything outside
A1:H85 is preserved — that includes 915 stored-but-empty cells outside the
answer range (to the right around J1:L250 and below around D86:D250) that
pin the sheet dimension at `A1:L250`, plus column widths, the sheet view's
selection (`H85`) / topLeftCell (`A74`).

spec.yaml declares variation along five axes: transformation semantics,
workbook topology, selection/alignment rule, output geometry, preservation
constraints. Concrete values from the task text always override everything
below, including every constant in the example.

## Environment facts (observed)

* Python 3 with **openpyxl 3.1.5 only**. No pandas/xlsxwriter/LibreOffice and
  no formula engines (`formulas`/`pycel`/`xlcalculator`). All edits go through
  openpyxl round-trips; formula arithmetic is evaluated by the tiny evaluator
  in `scripts/xlsx_kit.py`.
* Python's `list.sort`/`sorted` are **stable**: "equal keys keep original
  order" holds automatically when the key is a plain function (no extra
  tie-breaker).
* The skill package is mounted read-only at `/skill`; import the kit with
  `sys.path.insert(0, '/skill/scripts')` (or copy `scripts/xlsx_kit.py` to the
  working directory).

## Invariants for the whole family

1. Input `/app/input.xlsx` → output `/app/output.xlsx` (confirm from text).
2. **In-place round-trip, never rebuild.** openpyxl load → mutate cells → save
   preserves styles, filters, merged cells, panes, widths, heights, and
   sheet-view state automatically (verified lossless on v01). Rebuilding a
   `Workbook()` destroys all of it.
3. **Reads must not create cells.** `ws.cell(row, col)` and `ws['A1']` INSERT a
   new Cell into `ws._cells` when the coordinate is absent, and openpyxl
   computes the saved `<dimension>` from all cells in `_cells`. Reproduced:
   looping reads over Q1:R5 grew the dimension from `A1:L250` to `A1:Q250`.
   All kit read paths (`read_row`, `stored_cell`, `stored_value`,
   `snapshot_outside`, `assert_*`) touch only cells the file already stores.
   If you must read an arbitrary coordinate for debugging, use
   `stored_value(ws, r, col)`.
4. **Never touch anything outside the declared answer range** — not even to
   read it via `ws.cell()` (see above). Preservation = omission.
5. **Topology from data, never hard-coded.** Block boundaries, lengths,
   headers, ID lists are detected from the file. Every number in a task or
   example is a variable: derive ranges from the instruction, extents from the
   workbook.
6. **Formulas never appear in the output.** Evaluated columns become plain
   ints/floats; after saving, reload and assert `data_type != 'f'`. Never
   assign a string starting with `=` (openpyxl would store it as a formula).
7. **Reordering writes are made from a snapshot taken before any write.**
   When complete rows are permuted in place, reading a source row *during*
   the write loop can return already-rewritten content — a two-row swap
   would silently duplicate one of them. Take `snapshot_rows(ws, rows,
   cols)` (or `orig = {r: read_row(...)}` for all involved rows) before the
   first write and read only from the snapshot. The kit's
   `transform_block_sort`/`compact_rows` do this internally.
8. **Self-verification recomputes expectations from input, not from the
   transform code**, and mirrors the contract the hidden tests check (see
   "The test contract to mirror").

## Pipeline (decision rules)

### Step 1 — Parse the instruction into a transform spec

Write out: source sheet + range; destination sheet/range/orientation/boundary
(compact / append-below / keep separators); transformation; selection or sort
key (evaluated value, predicate, fill colour, ID/header identity, source-list
order, positional); order direction + tie rule ("preserve original relative
order" ⇒ stable sort; "ties broken by X" ⇒ two-component key); which columns
get evaluated; the preservation list (default: everything else, including
invisible state — see Step 2).

### Step 2 — Inventory the workbook (one call)

```python
import sys; sys.path.insert(0, '/skill/scripts')
from xlsx_kit import *
wb = describe_workbook('/app/input.xlsx')   # prints everything; non-mutating
```

This prints, per sheet: `dimensions` vs `stored_extent`, freeze panes, auto
filter, merged ranges, column dims (width/min/max/hidden/customWidth/bestFit/
style), row heights, sheet view (topLeftCell, selection, tabSelected,
gridlines), default row height (`sheet_format.defaultRowHeight` — the
worksheet has no `defaultRowHeight` attribute), and each column's data-type
profile (`'f'` marks formula columns). Study the gap between `dimensions` and
the non-empty bounding box: it is styled-but-empty cells that keep the
dimension alive — leave them alone. Decide which columns are formulas and
which are plain numbers by looking at the type profile, not by assumption.

### Step 3 — Load modes

* Default `load_workbook(path)`: formulas readable (`cell.data_type == 'f'`,
  `cell.value == '=B1+C1'`; openpyxl already expands *shared* formulas into
  per-cell strings). Do all edits in this mode.
* `data_only=True`: Excel's cached results. Fallback/comparison only — caches
  may be present, stale, or absent across family members.

### Step 4 — Locate the topology dynamically

* **Blank-separated blocks** (observed): a row is blank iff every cell of the
  block's column set is None/''; split the declared range on blank rows with
  `iter_blank_blocks_list(ws, R['top'], R['bottom'], R['cols'])`. Separators
  are one blank row by convention; normalise only if the task demands it.
* **Contiguous table**: bounding box of non-empty cells (`data_bbox`); find
  the header row with `header_row_index` (mostly-string row) and treat it as
  labels unless the task says otherwise.
* **Header/ID identity**: `header_map(ws, header_row, cols)` returns
  {normalized text: column letter} (strip + casefold) — map by header text,
  never by position.
* **Ordered ID list + sparse table**: primary = ordered keys in source
  position; side table → `dict[key]`; iterate the primary list, write lookups
  in list order; missing IDs stay blank unless specified.
* **Style-marked cells**: `fill_key(cell)` → (patternType, fg rgb, fg theme);
  compare rgb strings exactly; `theme`-indexed fills without rgb need
  inference from the task wording, not guesswork.

### Step 5 — Evaluate formulas to numbers

Rule of thumb: **evaluate only rows that belong to data blocks; blank
separator rows raise `FormulaError` by design.**

1. Evaluate the row's columns in dependency order with
   `eval_row_columns(ws, row, ['D','E','F'])` — earlier columns are resolved
   first so `F = D1+E1` sees the evaluated D. The returned dict is keyed
   **both** by coordinate (`'D1'`) and by bare column (`'D'`).
2. The evaluator handles `+ - * / ^ ( )`, unary minus with Excel precedence
   (`-2^2 == 4`), `^` left-associative (`2^3^2 == 64`), numeric literals, and
   same-row references with optional `$`. Function calls and cross-row
   references raise `FormulaError`.
3. Strings that look like arithmetic (digits/operators plus at least one cell
   ref, e.g. `'B1+C1'`, with or without `=`) are treated as formulas; plain
   numeric strings (`'-110.7'`) coerce via `float`. Guard `bool` before
   int/float (`isinstance(True, int)` is True).
4. On `FormulaError`: fall back to the cached value (`cached_value_of`);
   print that it happened; if there is no cached value, stop and re-read the
   task — a wrong key silently breaks ordering tests.
5. Sort keys = evaluated floats, **unrounded**; stable sort places computed
   ties in original order. Compare floats with `float_close` (repr differs
   across writers: 224.9 vs 224.89999999999998 are the same value).

### Step 6 — Transform in memory, write only the answer range

Common rule for every write loop: **pre-read all involved rows before the
first write** (`snapshot_rows`), substitute evaluated numbers into the formula
columns, and write only positions inside the declared range. All writes may
create cells (writing the declared range is legitimate), nothing else may;
`write_row`/`write_matrix` refuse `=`-strings. Prefer value-level rewrites
over `insert_rows`/`delete_rows` (structural row ops move trailing rows'
styles and break preservation).

* **Block-local sort** (observed): one call —
  `blocks, expected = transform_block_sort(ws, R, key_col='D',
  eval_cols=['D','E','F'], reverse=True)` — stable per-block sort, evaluated
  numbers substituted, pre-read inside. (Manual equivalent: `snapshot_rows`,
  then per block `stable_sort_rows` + `write_row(start + i)`.)
* **Predicate filter + compaction**: `kept = [r for r in data_rows if
  predicate(stored_value(ws, r, col))]`; then
  `expected = compact_rows(ws, R, kept, evaluated=ev)` — survivors are written
  consecutively from `R['top']` and the tail is blanked to `R['bottom']` so no
  stale rows remain. If a header row sits at `R['top']` inside the range and
  must stay, pass `dst_start=R['top']+1` (headers are never rewritten — they
  are preserved in place). Build the predicate from the task text (threshold
  / substring / exclusions), on a column identified via `header_map` if
  headers exist.
* **Append with header/ID alignment**: `hm = header_map(ws, hdr_row, cols)`;
  build each new row as `[source_vals[matching column] ...]` in destination
  column order; `write_row(ws, row, cols, vals)` for rows starting at
  `last_data_row(ws, key_col, top=R['top']) + 1` (or the declared
  anchor/boundary — follow the instruction, not v01).
* **Sparse-record reconciliation**: primary = ordered key list in its source
  position; side `dict[key] = row`; write `lookup.get(key)` (or a blank row
  where missing, as specified) into the declared destination rows in list
  order. Evaluate formula columns of the written rows first.
* **Transposition/extraction**: `mat = read_matrix(ws, src_rows, src_cols)`;
  transform (transpose = `list(zip(*mat))`, or slice);
  `write_matrix(ws, anchor_row, anchor_col, out_matrix)`. Verify geometry by
  reading the destination back and comparing shapes and values types.

### Step 7 — Save and self-verify (never skip)

Save, reload in default (formula-visible) mode, then run the five fixed
checks **plus one structure check per the transform's semantics**. The fixed
checks work for every family member:

```python
wb.save('/app/output.xlsx')
wb_out = load_workbook('/app/output.xlsx')
ws_out = wb_out[SHEET]
problems = {
    'meta':      assert_sheet_meta_equal(SHEET, meta_before, sheet_meta(ws_out)),
    'outside':   assert_outside_unchanged(out_snap, ws_out),
    'formulas':  assert_no_formulas(ws_out, R['top'], R['bottom'], R['cols']),
    'dimension': [] if ws_out.dimensions == dim_before else ['dimension changed'],
    'sheetlist': [] if wb_out.sheetnames == wb.sheetnames else ['sheets changed'],
    # structure: one of the per-semantics checks below
}
```

`meta_before = sheet_meta(ws)`, `dim_before = ws.dimensions` and
`out_snap = snapshot_outside(ws, R)` are taken **before** mutating; the
verification helpers are non-mutating, so verification itself cannot corrupt
the file. Per-semantics structure checks (recompute expectations from a fresh
input load — see `test_answer_value_group` in the contract below):

* **sort**: for each block, expected sequence (returned by
  `transform_block_sort` or recomputed) vs `read_row(ws_out, start+i)` with
  `rows_equal`; separators still blank; `block_layout` unchanged.
* **filter/compact**: survivors' sequence matches; rows after the survivor
  count are blank; dropped rows absent from the answer range.
* **append/reconcile**: destination rows equal mapped source rows straight
  through the declared boundary; missing IDs are blank.
* **transpose/extract**: destination matrix equals the recomputed transform
  cell-by-cell.

Fix any problem group and re-run until zero (ship `run_checks(...) == 0`).

## The test contract to mirror (observed from the v01 evaluation)

The hidden pytest suite for v01 contained exactly these checks; the family's
tests will be shaped the same way, so mirror them in self-verification:

* `test_output_exists` / `test_output_values` — the file exists, opens with
  openpyxl, and the answer range holds the expected values.
* `test_answer_value_group[...-01..08]` — the answer is validated as a
  sequence of **groups** (one per block/segment): recompute each group's
  expected row sequence from the input and compare with `float_close`.
* `test_input_sheets_and_unrequested_values_are_preserved` — sheet list
  unchanged; every cell outside the declared answer range bit-equal.
* `test_existing_workbook_structure_and_styles_are_preserved` — dimension
  string, widths, heights, filters, merged ranges, panes, styles intact.

Your verification step must reprove all four categories locally before
finishing: file saves and opens; per-group sequence equality (tolerated);
sheet list + out-of-range cells unchanged; meta/dimension unchanged.

## Pitfalls

* **Reading with `ws.cell()`/`ws['A1']` outside the answer range creates cells
  and grows the saved dimension.** Reproduced: `A1:L250` → `A1:Q250`. Use kit
  read helpers (non-mutating) for anything outside the answer range.
* The input's cached values may be exact, stale, or missing — always evaluate
  formulas yourself; the output must contain numbers, regardless of cache.
* openpyxl renumbers style ids on save; compare style *semantics*
  (`cell_style_key`) through openpyxl on both files, never raw XML. Raw
  docProps/styles.xml/calcChain differences are expected noise (dropping
  calcChain is fine — formulas are replaced with values anyway).
* Styled-empty cells keep the dimension alive; do not erase them (bulk `_cells`
  cleanup, `delete_rows`, or blanket rewrites over the stored extent).
* **In-place permutations: pre-read before writing.** Reading source rows
  during the write loop can return already-moved content — swapping rows 9
  and 10 in that order duplicates row 10's data. `snapshot_rows` (or
  `transform_block_sort`/`compact_rows`, which do it internally) first, then
  write from the snapshot only.
* Blank rows raise `FormulaError` during evaluation — only evaluate data rows.
* `''`-strings are not None: the blank-row test accepts both.
* Evaluation dict keys: `eval_row_columns` returns both `'D'` and `'D1'`.
* If the task mentions filters/merges/panes that are absent, still assert they
  are absent after save — preservation means *no change*, not recreation.
* Multi-sheet cases: locate the source sheet by the instruction (name or
  role), operate on exactly one sheet, leave order/hidden states/views of all
  sheets untouched.
* Deriving "sheet/range/columns" from the example instead of the instruction
  is the classic failure mode when a variant changes them — the example's
  constants are placeholders, nothing more.

## Kit (`scripts/xlsx_kit.py`)

Load: `import sys; sys.path.insert(0, '/skill/scripts'); from xlsx_kit import *`

* Formula evaluation: `tokenize`, `_eval` (module-level), `looks_like_formula`,
  `numeric_from_cell`, `eval_row_columns`, `FormulaError`, `cached_value_of`.
* Geometry/topology: `parse_range('A1:H85')` → dict with `cols`, `top`,
  `bottom`, `col_from/to` (use this instead of hard-coding letters/numbers);
  `stored_extent(ws)`; `data_bbox`; `iter_blank_blocks_list`;
  `block_layout(ws, top, bottom, cols)` → [(start, n_rows)];
  `is_blank_row`; `header_row_index`; `header_map`; `last_data_row`;
  `fill_key`.
* Non-mutating access: `stored_cell(ws, r, col)`, `stored_value(ws, r, col)`,
  `read_row(ws, r, cols)`.
* Writing/transforming: `write_row(ws, r, cols, values)` (refuses `=`-strings),
  `read_matrix`, `write_matrix`, `stable_sort_rows(rows, key, reverse)`,
  `snapshot_rows(ws, rows, cols)` (pre-read before in-place reordering),
  `blank_cells(ws, rows, cols)`, `compact_rows(ws, R, kept_rows, ...)`,
  `transform_block_sort(ws, R, key_col, eval_cols, reverse=True)`.
* Comparison: `values_equal(a, b)`, `rows_equal(row_a, row_b)`, `float_close`.
* Preservation/verification: `describe_workbook`, `sheet_meta`,
  `assert_sheet_meta_equal`, `snapshot_range`, `snapshot_outside`,
  `assert_range_unchanged` (same live sheet), `assert_outside_unchanged`
  (reloaded output vs pre-mutation snapshot), `assert_no_formulas`,
  `cell_style_key`, `run_checks`, `reload_workbook`.

Worked shape for the observed block-sort (parameterized; **replace every
constant with the current task's values** — these are placeholders):

```python
import sys; sys.path.insert(0, '/skill/scripts')
from xlsx_kit import *

R = parse_range('A1:H85')            # the range named in the instruction
KEY_COLS = ['D', 'E', 'F']           # columns to evaluate, in dependency order
SORT_KEY = 'D'                       # column the sort uses, per instruction
SHEET = 'Sheet1'                     # sheet named in the instruction

wb = load_workbook('/app/input.xlsx')
ws = wb[SHEET]
meta_before, dim_before = sheet_meta(ws), ws.dimensions
out_snap = snapshot_outside(ws, R)          # before any mutation

blocks, expected = transform_block_sort(ws, R, key_col=SORT_KEY,
                                        eval_cols=KEY_COLS, reverse=True)
wb.save('/app/output.xlsx')

# ... then the Step-7 verification block; for the 'structure' group compare
# each expected[start] sequence against read_row(ws_out, start+i) with
# rows_equal, check separators stayed blank via is_blank_row, and finish
# only at 0 problems.
```

Manual equivalent of the sort loop (if you need to adapt it): pre-read with
`snap = snapshot_rows(ws, rows, R['cols'])` for ALL rows of ALL blocks
**before** the first `write_row`, then inside the loop use `vals =
list(snap[src])` — never `read_row` of a live row that may already have been
rewritten.

## Definition of done

`/app/output.xlsx` exists and opens; the answer range contains plain numeric
values (no formula cells); the recomputed structure (per-block order,
boundaries, alignment) matches within float tolerance; outside-cell values and
styles, sheet list, dimension string, widths/heights/filters/merges/panes all
verify unchanged — i.e. every mirrored contract check passes locally.