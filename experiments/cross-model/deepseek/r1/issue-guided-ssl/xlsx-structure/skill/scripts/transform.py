#!/usr/bin/env python3
"""
xlsx-structure transform pipeline (anchor v01: block-local stable sort by evaluated column D).

Usage:
  python3 transform.py input.xlsx output.xlsx [--span A1:H85] [--sort-col D]
                      [--eval-cols D:F] [--desc] [--cached-fallback] [--check]

The pipeline is deliberately parameterized so the same mechanisms serve the whole
family; the flags are the variant hooks (see SKILL.md). Defaults match v01.

Steps (in order):
  1. Load the workbook ONCE with data_only=False (formula view). Never save a
     data_only copy: it destroys formulas and openpyxl never evaluates anyway.
  2. Detect blocks from the workbook itself: consecutive non-blank rows inside the
     span, where a row is blank iff every cell in the span's used columns is empty.
  3. Evaluate the eval columns (D-F in v01) row-locally with a recursive, memoized
     arithmetic evaluator over the *formula text* (works for real formulas and for
     "text that represents formulas"). Dependencies are resolved recursively
     (F = D + E needs evaluated D). Results are raw IEEE floats - never rounded.
  4. Stable-sort each block's complete rows by evaluated sort column descending
     (key (-d, original_index) == stable reverse sort). Register every written
     coordinate as TOUCHED.
  5. Write payload values back into the SAME coordinates the block occupied
     (value-only rewrites; styles/dimensions/other cells untouched by construction).
  6. Save, then run the zip-level exact-float patch: openpyxl's own serializer
     truncates numeric values to 16 significant digits ('%.16g'), so raw IEEE
     doubles like 228.10000000000002 would silently become 228.1; the patch
     rewrites every numeric <v> with repr() of the exact in-memory value.
  7. restore_untouched_cells: splice the value payloads (<f>, <v>, <is>) of
     every NON-touched cell from the input zip into the output zip, keeping the
     output's style indices - preserves by construction what openpyxl round-trips
     destroy (cached formula results, rich-text runs).
  8. --check runs the discriminating verification suite: formulas gone, D-F
     numeric, block geometry, sortedness + tie stability, blank separators,
     preservation diff, untouched value diff (formula AND cached views),
     reference reconstruction, raw <dimension> comparison.
"""
import argparse
import ast
import re
import shutil
import sys
import zipfile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

__all__ = ["parse_span", "used_columns", "detect_blocks", "expected_row_order",
           "cell_value", "calc", "eval_col_indices", "span_cols", "values_equal",
           "style_signature", "dimension_refs", "patch_xml_part", "exact_float_patch",
           "restore_untouched_cells", "transform_workbook", "run_check"]

_API_DOC = """\
Reusable module API - import via:  import sys; sys.path.insert(0, '/skill/scripts'); from transform import ...
  parse_span('A1:H85') -> (min_col, min_row, max_col, max_row)          # 1-based
  used_columns(ws, min_col, min_row, max_col, max_row) -> set of 1-based col indices with values
  detect_blocks(ws, min_col, min_row, max_col, max_row)                 # four ints, OR
  detect_blocks(ws, 'A1:H85')                                          # a span string
      -> (blocks, used_cols);  blocks = [(start_row, end_row), ...], inclusive
  cell_value(ws, row, colnum, memo) -> evaluated number
      row-local formula-text evaluator (dependencies resolved recursively; memo is a dict)
  expected_row_order(ws, blocks, sort_col, desc=True) -> list of lists:
      per block, the INPUT row indices in the stable expected output order
  eval_col_indices('D:F') -> set of 1-based col indices
  span_cols(min_col, max_col) -> list of 1-based col indices
  values_equal(a, b) -> typed equality (numeric cross-type, exact floats, rich text normalized)
  style_signature(cell) -> comparable tuple (font/fill/number format/alignment/border)
  dimension_refs(path) -> {sheet part: raw <dimension> ref}
  patch_xml_part(path, part, pattern, replacement)  /  exact_float_patch(path, wb)
  restore_untouched_cells(output_path, input_path, touched_parts) -> int restored
  transform_workbook(wb, span, sort_col, eval_spec, desc=True, cached_wb=None, sheet=None)
      -> (blocks, touched)   touched = {(row, col), ...} written coordinates
"""

# ---------------------------------------------------------------------------
# Row-local formula evaluation
# ---------------------------------------------------------------------------

# Cell-ref matcher: optional $ anchors, 1-2 letters, digits. The lookbehind
# prevents tokens like "1E5" or "B2" inside identifiers from being seen as refs.
_REF = re.compile(r"(?<![A-Za-z0-9_.$])(\$?)([A-Z]{1,2})(\$?)(\d+)")
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
            ast.USub, ast.UAdd)


def calc(expr):
    """Evaluate a pure-arithmetic expression string (numbers/operators only)."""
    tree = ast.parse(expr, mode="eval")
    if not all(isinstance(n, _ALLOWED) for n in ast.walk(tree)):
        raise ValueError("unsupported formula: %r" % expr)
    return eval(compile(tree, "<f>", "eval"), {"__builtins__": {}}, {})


def cell_value(ws, row, colnum, memo):
    """
    Row-local cell resolution: any cell reference in the formula text is resolved
    against the FORMULA'S OWN ROW (row digits are stripped and replaced by `row`).
    Recursive + memoized so F = D + E works when D is itself a formula.
    Passes through plain numbers; raises on empty operands / unsupported content.
    """
    key = (row, colnum)
    if key in memo:
        return memo[key]
    v = ws.cell(row=row, column=colnum).value
    if isinstance(v, str):
        v = v.strip()
    if v is None or v == "":
        raise ValueError("empty operand row %d col %d" % (row, colnum))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        memo[key] = v
        return v
    if v.startswith("="):
        expr = _REF.sub(
            lambda m: repr(cell_value(ws, row, column_index_from_string(m.group(2).upper()), memo)),
            v[1:])
        memo[key] = calc(expr)
        return memo[key]
    raise ValueError("unexpected content %r at row %d col %d" % (v, row, colnum))


# ---------------------------------------------------------------------------
# Topology: blank-row-derived block detection
# ---------------------------------------------------------------------------

def parse_span(span):
    """'A1:H85' -> (min_col, min_row, max_col, max_row), 1-based."""
    m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", span)
    if not m:
        raise ValueError("bad span %r" % span)
    return (column_index_from_string(m.group(1)), int(m.group(2)),
            column_index_from_string(m.group(3)), int(m.group(4)))


def used_columns(ws, min_col, min_row, max_col, max_row):
    """Columns inside the span that contain at least one non-empty value."""
    used = set()
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None and v != "":
                used.add(c)
    return used


def detect_blocks(ws, min_col=None, min_row=None, max_col=None, max_row=None, span=None):
    """
    Maximal runs of non-blank rows inside the span. A row is blank iff all used
    columns of the span are empty. Call with four ints
    detect_blocks(ws, min_col, min_row, max_col, max_row) or with a span string
    detect_blocks(ws, 'A1:H85'). Returns (blocks, used_cols) with
    blocks = list of (start_row, end_row) inclusive.
    """
    if span is None and isinstance(min_col, str):
        span = min_col
    if span is not None:
        min_col, min_row, max_col, max_row = parse_span(span)
    if None in (min_col, min_row, max_col, max_row):
        raise TypeError("detect_blocks needs four ints or a span string: "
                        "detect_blocks(ws, 'A1:H85')")
    used = used_columns(ws, min_col, min_row, max_col, max_row)
    if not used:
        return [], used

    def blank(r):
        return all(ws.cell(row=r, column=c).value in (None, "") for c in used)

    blocks, start = [], None
    for r in range(min_row, max_row + 1):
        if blank(r):
            if start is not None:
                blocks.append((start, r - 1))
                start = None
        else:
            if start is None:
                start = r
    if start is not None:
        blocks.append((start, max_row))
    return blocks, used


def expected_row_order(ws, blocks, sort_col, desc=True):
    """
    Shared-path rederivation: per block, the INPUT row indices in the stable
    expected output order, keyed by evaluated sort column (ties keep original
    order). Use it for cross-checks; it is deliberately NOT independent of the
    pipeline (the hand-built oracles in scripts/family_probe.py are), so label
    it as such when you rely on it.
    """
    sign = -1 if desc else 1
    sort_idx = column_index_from_string(sort_col)
    order = []
    for (s, e) in blocks:
        rows = list(range(s, e + 1))
        memo = {}
        evals = {r: cell_value(ws, r, sort_idx, memo) for r in rows}
        order.append(sorted(rows, key=lambda r: (sign * evals[r], r)))
    return order


# ---------------------------------------------------------------------------
# Transform: evaluate -> stable sort -> value-only rewrite
# ---------------------------------------------------------------------------

def column_letters(a, b):
    return [column_index_from_string(l) for l in
            (chr(x) for x in range(ord(a), ord(b) + 1))]


def span_cols(min_col, max_col):
    return list(range(min_col, max_col + 1))


def eval_col_indices(eval_spec):
    """'D:F' or 'D' -> set of 1-based column indices."""
    out = set()
    for part in eval_spec.split(","):
        part = part.strip()
        if ":" in part:
            a, b = part.split(":")
            out.update(column_letters(a.strip(), b.strip()))
        else:
            out.add(column_index_from_string(part))
    return out


def transform_workbook(wb, span, sort_col, eval_spec, desc=True, cached_wb=None, sheet=None):
    # sign: -1 for descending (sort by -d), +1 for ascending (sort by +d)
    sign = -1 if desc else 1
    min_col, min_row, max_col, max_row = parse_span(span)
    sort_idx_col = column_index_from_string(sort_col)
    evcols = eval_col_indices(eval_spec)
    ws = wb[sheet] if sheet else wb.active
    blocks, _ = detect_blocks(ws, min_col, min_row, max_col, max_row)
    cols = span_cols(min_col, max_col)
    touched = set()  # (row, col) coordinates this transform actually wrote

    for start, end in blocks:
        memo = {}
        rows = []
        for r in range(start, end + 1):
            payload = []
            for c in cols:
                v = ws.cell(row=r, column=c).value
                if isinstance(v, str):
                    v = v.strip()
                if c in evcols:
                    try:
                        if v is None or v == "":
                            raise ValueError("empty eval cell")
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            payload.append(v)
                        elif v.startswith("="):
                            payload.append(cell_value(ws, r, c, memo))
                        else:
                            raise ValueError("unexpected content %r" % v)
                    except ValueError as exc:
                        if cached_wb is not None:
                            payload.append(cached_wb[sheet if sheet else cached_wb.active.title]
                                          .cell(row=r, column=c).value)
                        else:
                            raise ValueError(
                                "cannot evaluate %s row %d: %s (add --cached-fallback if the "
                                "file carries cached values and the text is not parseable)"
                                % (get_column_letter(c), r, exc))
                else:
                    payload.append(v)
            rows.append((r, payload))
        # Stable sort: ties keep original row order (key includes original index).
        key_col = cols.index(sort_idx_col)
        rows.sort(key=lambda item: (sign * item[1][key_col], item[0]))
        for offset, (_, payload) in enumerate(rows):
            for i, c in enumerate(cols):
                ws.cell(row=start + offset, column=c).value = payload[i]
                touched.add((start + offset, c))

    return blocks, touched


# ---------------------------------------------------------------------------
# Verification suite (--check)
# ---------------------------------------------------------------------------

def style_signature(cell):
    f, fill, al, b = cell.font, cell.fill, cell.alignment, cell.border
    return (
        f.name, f.size, f.bold, f.italic, f.underline,
        str(f.color.rgb) if f.color is not None else None,
        fill.fill_type,
        str(fill.fgColor.rgb) if fill.patternType else None,
        str(fill.bgColor.rgb) if fill.patternType else None,
        cell.number_format,
        al.horizontal, al.vertical,
        b.left.style, b.right.style, b.top.style, b.bottom.style,
    )


def dimension_refs(path):
    """{sheet part: raw <dimension> ref} for EVERY worksheet part in the zip.
    Multi-sheet variants need all parts compared, not just the first."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if re.match(r"xl/worksheets/sheet\d+\.xml$", n):
                m = re.search(rb'<dimension\s+ref="([^"]*)"', z.read(n))
                out[n] = m.group(1).decode() if m else None
    return out


def patch_xml_part(path, part, pattern, replacement):
    """Rewrite one XML part inside the xlsx zip (zipfile surgery - no unzip binary)."""
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == part:
                data = re.sub(pattern, replacement, data)
            z.writestr(item, data)
    shutil.move(tmp, path)


def _num_to_str(v):
    """Serialize a number the way Excel-style generators do: integral doubles as
    integers ('230', not '230.0'), everything else as the shortest exact repr."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v)


def exact_float_patch(path, wb):
    """
    openpyxl's own serializer formats every numeric cell with '%.16g'
    (safe_string in openpyxl.compat.strings), silently truncating IEEE doubles
    (228.10000000000002 -> 228.1). The in-memory workbook keeps exact values,
    so after wb.save() rewrite each numeric <v> with the exact in-memory value
    (integral doubles as ints, mirroring the input generator's convention).
    This is the mechanism that makes the "raw IEEE, never round" invariant
    true despite openpyxl's save path.
    """
    with zipfile.ZipFile(path) as zin:
        infos = zin.infolist()
        items = {it.filename: zin.read(it.filename) for it in infos}
    for idx, ws in enumerate(wb.worksheets, start=1):
        part = "xl/worksheets/sheet%d.xml" % idx
        if part not in items:
            continue
        data = items[part]

        def repl(m):
            coord = m.group(1).decode()
            v = ws[coord].value
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return m.group(0)[:m.group(0).rfind(m.group(2))] + _num_to_str(v).encode() + b"</v>"
            return m.group(0)

        items[part] = re.sub(rb'<c r="([A-Z]+\d+)"[^>]*?>\s*<v>([^<]*)</v>', repl, data)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for it in infos:
            z.writestr(it, items[it.filename])
    shutil.move(tmp, path)


# Coordinate-scoped restoration: openpyxl round-trips are provably lossy for
# untouched cells (it strips cached <v> results from formulas and collapses
# rich-text runs), so untouched cells are restored by construction: splice the
# input zip's value payload (<f>, <v>, <is>) into the output zip, keeping the
# output's own r= and s= attributes (style indices belong to the OUTPUT's
# re-serialized stylesheet, never the input's). The open tag must NOT end in
# '/': self-closing cells (<c r="J1" s="7" t="n" />) have no </c>, and a
# naive non-greedy match would swallow everything up to the NEXT cell's </c>
# (crossing row boundaries and pulling in the input's row attributes).
_CELL = re.compile(rb'(<c\s+r="([A-Z]{1,2}\d+)"[^>]*[^/]>)(.*?)(</c>)', re.S)


def _coord_key(raw):
    """bytes coordinate 'D2' -> (row, col) int tuple (the touched-set key type)."""
    m = re.match(rb'([A-Z]{1,2})(\d+)$', raw)
    return (int(m.group(2)), column_index_from_string(m.group(1).decode()))


def _cell_type(open_tag):
    m = re.search(rb'\bt="([^"]+)"', open_tag)
    return m.group(1) if m else None


def restore_untouched_cells(output_path, input_path, touched_parts):
    """
    For every cell whose coordinate the transform did not write, replace the
    value payload in the output sheet XML with the input's verbatim payload,
    preserving the output's own open-tag attributes (r=, s= style pointer).
    t= is synced from the input when the payload is an inline string or a
    'str' (string-formula) cell, because the type attribute is part of the
    value semantics. Cells whose input or output payload is a shared-string
    (t="s") are SKIPPED: their <v> is an index into the sharedStrings table,
    which openpyxl renumbers on save; their textual value already round-trips
    through openpyxl (only rich runs inside shared strings are lost - that
    case needs sharedStrings.xml surgery, see SKILL.md).
    Returns the number of restored cells.
    """
    with zipfile.ZipFile(input_path) as zi:
        z_in = {n: zi.read(n) for n in zi.namelist()}
    with zipfile.ZipFile(output_path) as zo:
        infos = zo.infolist()
        parts = {n: zo.read(n) for n in zo.namelist()}
    restored = 0
    for part in [n for n in parts if re.match(r'^xl/worksheets/sheet\d+\.xml$', n)]:
        if part not in z_in:
            continue
        data = parts[part]
        in_cells = {m.group(2): m for m in _CELL.finditer(z_in[part])}
        touched = touched_parts.get(part, set())
        pieces, pos = [], 0
        for m in _CELL.finditer(data):
            coord = m.group(2)
            inp = in_cells.get(coord)
            if _coord_key(coord) in touched or inp is None:
                continue
            in_open, in_payload = inp.group(1), inp.group(3)
            out_open, out_payload = m.group(1), m.group(3)
            in_t, out_t = _cell_type(in_open), _cell_type(out_open)
            if in_t == b"s" or out_t == b"s":
                continue  # shared-string index; keep openpyxl's serialization
            if in_payload == out_payload and in_t == out_t:
                continue  # already identical
            # sync t= (part of value semantics for inline/inlineStr/str payloads)
            if in_t in (b"inlineStr", b"str") or in_payload.startswith(b"<is>"):
                if out_t is None:
                    out_open = out_open[:-1] + b' t="' + in_t + b'">'
                elif out_t != in_t:
                    out_open = out_open[:out_t.start()] + b't="' + in_t + b'"' + out_open[out_t.end():]
            pieces.append(data[pos:m.start(1)])
            pieces.append(out_open)
            pieces.append(in_payload)
            pieces.append(m.group(4))
            pos = m.end(4)
            restored += 1
        pieces.append(data[pos:])
        parts[part] = b"".join(pieces)
    tmp = output_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for it in infos:
            z.writestr(it, parts[it.filename])
    shutil.move(tmp, output_path)
    return restored


def rich_text_key(v):
    """Normalize openpyxl rich text (CellRichText) to a comparable tuple."""
    if hasattr(v, "__iter__") and not isinstance(v, (str, bytes)):
        return ("rt", tuple(p.text if hasattr(p, "text") else p for p in v))
    return v


def values_equal(a, b):
    """
    Typed equality for verification: numeric cross-type equality on exact
    IEEE doubles (230 == 230.0), strict type+value for strings/None, rich text
    normalized to its runs.
    """
    a, b = rich_text_key(a), rich_text_key(b)
    if a is None or b is None:
        return a is b
    if (isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)):
        return a == b
    return type(a) is type(b) and a == b


def run_check(input_path, output_path, span, sort_col, eval_spec, desc=True,
              touched_parts=None, sheet=None):
    """Discriminating verification suite. touched_parts: {sheet_part: set((row,col))}
    as registered by the transform; everything else is "untouched" by declaration
    and must be value-identical to the input."""
    problems = []
    touched_parts = touched_parts or {}
    ib = load_workbook(input_path, data_only=False)
    ob = load_workbook(output_path, data_only=False)
    ibd = load_workbook(input_path, data_only=True)   # cached-value view for (7)
    obd = load_workbook(output_path, data_only=True)
    iws, ows = ib[sheet] if sheet else ib.active, ob[sheet] if sheet else ob.active
    min_col, min_row, max_col, max_row = parse_span(span)
    sort_idx_col = column_index_from_string(sort_col)
    evcols = eval_col_indices(eval_spec)
    cols = span_cols(min_col, max_col)

    # (1) No '='-prefixed strings anywhere in the span; eval columns all numeric.
    for r in range(min_row, max_row + 1):
        for c in cols:
            v = ows.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip().startswith("="):
                problems.append("formula text left in span: %s" %
                                ows.cell(row=r, column=c).coordinate)
            if c in evcols and v is not None:
                if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    problems.append("non-numeric eval cell %s: %r" %
                                    (ows.cell(row=r, column=c).coordinate, v))

    # (2) Block geometry identical (boundaries derived from the workbook itself).
    b_in, _ = detect_blocks(iws, min_col, min_row, max_col, max_row)
    b_out, _ = detect_blocks(ows, min_col, min_row, max_col, max_row)
    if b_in != b_out:
        problems.append("block geometry changed: %s -> %s" % (b_in, b_out))
    else:
        # (3) Each block sorted by evaluated sort column, ties stable.
        for start, end in b_out:
            vals = []
            for r in range(start, end + 1):
                v = ows.cell(row=r, column=sort_idx_col).value
                vals.append((r, v))
            kv = [v for _, v in vals]
            bad = None
            if desc:
                bad = any(kv[i] < kv[i + 1] for i in range(len(kv) - 1))
            else:
                bad = any(kv[i] > kv[i + 1] for i in range(len(kv) - 1))
            if bad:
                problems.append("block rows %d-%d not %s" % (start, end, "descending" if desc else "ascending"))
            # tie stability: rows with equal evaluated D must keep input relative order.
            # Identity of a moved row = its payload tuple with eval columns normalized to
            # evaluated numbers (input stores formulas there, output stores numbers).
            def payload(ws_, r, memo):
                vals = []
                for c in cols:
                    v = ws_.cell(row=r, column=c).value
                    if isinstance(v, str):
                        v = v.strip()
                    if c in evcols and isinstance(v, str) and v.startswith("="):
                        v = cell_value(ws_, r, c, memo)
                    vals.append(v)
                return tuple(vals)
            in_ident = {payload(iws, r, {}): r for r in range(start, end + 1)}
            groups, dorder = {}, []
            for r in range(start, end + 1):
                dv = ows.cell(row=r, column=sort_idx_col).value
                if dv not in groups:
                    groups[dv] = []
                    dorder.append(dv)
                groups[dv].append(r)
            for dv in dorder:
                rows_out = groups[dv]
                if len(rows_out) > 1:
                    seq = [in_ident.get(payload(ows, r, {})) for r in rows_out]
                    if any(a is None or b is None or a >= b for a, b in zip(seq, seq[1:])):
                        problems.append(
                            "tie instability for D=%r in block %d-%d: input-order "
                            "sequence of tied rows %s" % (dv, start, end, seq))

    # (4) Blank separator rows: blankness pattern identical over the whole span.
    ui = used_columns(iws, min_col, min_row, max_col, max_row)
    uo = used_columns(ows, min_col, min_row, max_col, max_row)
    for r in range(min_row, max_row + 1):
        bi = all(iws.cell(row=r, column=c).value in (None, "") for c in ui)
        bo = all(ows.cell(row=r, column=c).value in (None, "") for c in uo)
        if bi != bo:
            problems.append("blankness differs at row %d" % r)

    # (5) Preservation diff: merged ranges, panes, filter, widths, heights, styles.
    if sorted(str(x) for x in iws.merged_cells.ranges) != sorted(str(x) for x in ows.merged_cells.ranges):
        problems.append("merged ranges differ")
    if (iws.freeze_panes, iws.auto_filter.ref) != (ows.freeze_panes, ows.auto_filter.ref):
        problems.append("freeze_panes/auto_filter differ: %r/%r vs %r/%r" %
                        (iws.freeze_panes, iws.auto_filter.ref, ows.freeze_panes, ows.auto_filter.ref))
    w_in = {k: (v.width, v.hidden) for k, v in iws.column_dimensions.items()
            if v.width is not None or v.hidden}
    w_out = {k: (v.width, v.hidden) for k, v in ows.column_dimensions.items()
             if v.width is not None or v.hidden}
    if w_in != w_out:
        problems.append("column widths differ: %s" % (w_in, w_out))
    h_in = {k: (v.height, v.hidden) for k, v in iws.row_dimensions.items()
            if v.height is not None or v.hidden}
    h_out = {k: (v.height, v.hidden) for k, v in ows.row_dimensions.items()
             if v.height is not None or v.hidden}
    if h_in != h_out:
        problems.append("row heights differ: %s" % (h_in, h_out))
    coords = set(iws._cells) | set(ows._cells)
    for key in sorted(coords):
        ci, co = iws._cells.get(key), ows._cells.get(key)
        # value-bearing presence: a present-but-empty cell equals an absent cell
        vi = ci.value if ci is not None else None
        vo = co.value if co is not None else None
        if (vi is not None) != (vo is not None):
            problems.append("cell value presence differs at %s" % (key,))
        elif ci is not None and co is not None and style_signature(ci) != style_signature(co):
            problems.append("style differs at %s:\n  in  %s\n  out %s" %
                            (ci.coordinate, style_signature(ci), style_signature(co)))

    # (6) Raw <dimension> tag comparison per sheet part (the preservation axis
    # names dimensions; multi-sheet variants need every part compared).
    d_in, d_out = dimension_refs(input_path), dimension_refs(output_path)
    if d_in != d_out:
        problems.append("dimension tags differ: input %r vs output %r "
                        "(fix: patch_xml_part(output, part, regex, ref))" % (d_in, d_out))

    # (7) Untouched-value diff: for EVERY cell the transform did not write, the
    # value must be typed-identical to the input - in the formula view AND in
    # the cached (data_only) view (openpyxl would silently strip cached <v>
    # results and collapse rich runs; restoration makes this pass).
    i_by_name = {ws.title: ws for ws in ib.worksheets}
    o_by_name = {ws.title: ws for ws in ob.worksheets}
    id_by_name = {ws.title: ws for ws in ibd.worksheets}
    od_by_name = {ws.title: ws for ws in obd.worksheets}
    untouched_checked = 0
    for name, iw in i_by_name.items():
        if name not in o_by_name:
            continue
        ow = o_by_name[name]
        part = "xl/worksheets/sheet%d.xml" % (ib.sheetnames.index(name) + 1)
        touched = touched_parts.get(part, set())
        for key in sorted(set(iw._cells) | set(ow._cells)):
            if key in touched:
                continue
            ci, co = iw._cells.get(key), ow._cells.get(key)
            if (ci is None) != (co is None):
                problems.append("untouched cell presence differs at %s!%s" %
                                (name, key))
                continue
            if ci is None:
                continue
            untouched_checked += 1
            if not values_equal(ci.value, co.value):
                problems.append("untouched value changed at %s!%s: %r -> %r" %
                                (name, ci.coordinate, ci.value, co.value))
            if style_signature(ci) != style_signature(co):
                problems.append("style differs at %s!%s:" % (name, ci.coordinate))
            di = id_by_name[name]._cells.get(key)
            do_ = od_by_name[name]._cells.get(key)
            if di is not None and do_ is not None:
                if (di.value is not None or do_.value is not None) and not values_equal(di.value, do_.value):
                    problems.append("untouched cached value changed at %s!%s: %r -> %r" %
                                    (name, di.coordinate, di.value, do_.value))

    # (8) Reference reconstruction: independently re-derive the EXPECTED span
    # payloads from the input (detect blocks, evaluate sort keys from the
    # input's own formula text, stable-sort complete payloads) and compare
    # cell-by-cell against the output. Catches any writeback/column-mapping/
    # permutation bug that monotonicity proxies cannot.
    sign = -1 if desc else 1
    expected = {}
    source_row = {}  # (out_row, col) -> input row the expected value came from
    for start, end in b_in:
        memo = {}
        rows = []
        for r in range(start, end + 1):
            payload = []
            for c in cols:
                v = iws.cell(row=r, column=c).value
                if isinstance(v, str):
                    v = v.strip()
                if c in evcols and isinstance(v, str) and v.startswith("="):
                    v = cell_value(iws, r, c, memo)
                payload.append(v)
            rows.append((r, payload))
        rows.sort(key=lambda item: (sign * item[1][cols.index(sort_idx_col)], item[0]))
        for off, (src, payload) in enumerate(rows):
            for i, c in enumerate(cols):
                expected[(start + off, c)] = payload[i]
                source_row[(start + off, c)] = src
    ref_bad = 0
    for (r, c), e in sorted(expected.items()):
        o = ows.cell(row=r, column=c).value
        if not values_equal(e, o):
            ref_bad += 1
            if ref_bad <= 10:
                problems.append("reference mismatch at %s: expected %r got %r" %
                                (ows.cell(row=r, column=c).coordinate, e, o))
    if ref_bad:
        problems.append("reference reconstruction: %d span-cell mismatches" % ref_bad)
    # cross-check the reference key evaluation against the input's cached
    # arithmetic when caches exist (guards the evaluator itself). The cached
    # value must be read from the SOURCE row (sorted rows move).
    if ibd is not None:
        idw = ibd[sheet] if sheet else ibd.active
        for (r, c) in expected:
            cv = idw.cell(row=source_row[(r, c)], column=c).value
            if cv is not None and c in evcols and not values_equal(expected[(r, c)], cv):
                problems.append("evaluator/cache disagreement at %s: %r vs cached %r" %
                                (iws.cell(row=r, column=c).coordinate, expected[(r, c)], cv))
                break

    sheetnames_in = set(ib.sheetnames)
    sheetnames_out = set(ob.sheetnames)
    if sheetnames_in != sheetnames_out:
        problems.append("sheet set differs: %s vs %s" % (sheetnames_in, sheetnames_out))

    return problems, (d_in, d_out), untouched_checked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="input xlsx (omit with --api)")
    ap.add_argument("output", nargs="?", help="output xlsx (omit with --api)")
    ap.add_argument("--api", action="store_true",
                    help="print the reusable module API (names, signatures, return shapes) and exit")
    ap.add_argument("--span", default="A1:H85")
    ap.add_argument("--sort-col", default="D")
    ap.add_argument("--eval-cols", default="D:F")
    ap.add_argument("--asc", action="store_true",
                    help="sort ascending instead of descending")
    ap.add_argument("--cached-fallback", action="store_true",
                    help="use cached values from a data_only load when a formula text is not parseable")
    ap.add_argument("--no-exact-floats", action="store_true",
                    help="skip the zip-level exact-float patch (openpyxl save truncates "
                         "floats to 16 significant digits; patching restores raw IEEE)")
    ap.add_argument("--sheet", default=None,
                    help="worksheet to transform (default: active sheet)")
    ap.add_argument("--no-restore", action="store_true",
                    help="skip restoration of untouched cells from the input zip "
                         "(openpyxl strips cached formula results and rich runs; do not "
                         "disable in production - use for counterfactual probes)")
    ap.add_argument("--check", action="store_true", help="run the verification suite after saving")
    ap.add_argument("--patch-dimension", action="store_true",
                    help="if the saved <dimension> tag differs from the input, patch output.xml to match")
    args = ap.parse_args(argv)
    if args.api:
        print(_API_DOC)
        return 0
    if not args.input or not args.output:
        ap.error("input and output paths are required (or use --api)")

    wb = load_workbook(args.input, data_only=False)
    cached_wb = None
    if args.cached_fallback:
        cached_wb = load_workbook(args.input, data_only=True)

    blocks, touched = transform_workbook(wb, args.span, args.sort_col, args.eval_cols,
                                         desc=not args.asc, cached_wb=cached_wb,
                                         sheet=args.sheet)
    target = wb[args.sheet] if args.sheet else wb.active
    wb.save(args.output)
    if not args.no_exact_floats:
        exact_float_patch(args.output, wb)
    # part names follow openpyxl's sheet{i}.xml convention (worksheet order)
    part = "xl/worksheets/sheet%d.xml" % (wb.worksheets.index(target) + 1)
    touched_parts = {part: touched}
    restored = 0
    if not args.no_restore:
        restored = restore_untouched_cells(args.output, args.input, touched_parts)
    print("transformed %d blocks -> %s (restored %d untouched cells)"
          % (len(blocks), args.output, restored))

    if args.check:
        problems, (d_in, d_out), untouched = run_check(
            args.input, args.output, args.span, args.sort_col, args.eval_cols,
            desc=not args.asc, touched_parts=touched_parts, sheet=args.sheet)
        if d_in != d_out and args.patch_dimension:
            for part, ref in d_in.items():
                patch_xml_part(args.output, part,
                               rb'<dimension\s+ref="[^"]*"', b'<dimension ref="%s"' % ref.encode())
            print("patched %d dimension tags to match input" % len(d_in))
            problems, (d_in, d_out), untouched = run_check(
                args.input, args.output, args.span, args.sort_col, args.eval_cols,
                desc=not args.asc, touched_parts=touched_parts, sheet=args.sheet)
        if problems:
            print("\nCHECK FAILED (%d problems):" % len(problems))
            for p in problems:
                print(" -", p)
            return 1
        print("CHECK PASSED: formulas gone, D-F numeric, %d blocks sorted/stable, "
              "separators intact, preservation diff empty, %d untouched cells "
              "value-identical (incl. cached view), reference reconstruction clean, "
              "dimension %r==%r" % (len(blocks), untouched, d_in, d_out))
    return 0


if __name__ == "__main__":
    sys.exit(main())