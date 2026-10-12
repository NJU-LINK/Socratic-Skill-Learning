#!/usr/bin/env python3
"""
html-finance-verify / checker.py

Cross-check reconstruction for HTML financial verification tasks.

Family invariant (see SKILL.md): the document contains exactly ONE displayed
metric that violates an internal accounting relation; every other displayed
metric is recomputable (within display rounding) from base quantities named by
its label. Dollar-denominated base values are internally consistent.

This script:
  1. parses every (line token, metric label, shown value) triple from all
     <table> elements -- CSS-class and section-name independent,
  2. builds relation checks from LABEL SEMANTICS (margins, subtotals,
     income-statement identities, per-share, unit conversions, growth/
     difference, EPS),
  3. recomputes each derived metric in Decimal arithmetic, rounds to the
     displayed precision, and diffs against the shown value,
  4. asserts exactly one violated relation: directly when there is a single
     violation; otherwise via the root-cause resolver, which finds the unique
     base metric whose correction (override with its own derived value)
     zeroes a fan of violations,
  5. writes the answer "<line_token>,<shown_value_cleaned>" to the requested
     output file only when the diagnosis is unique and its base pairing is
     unambiguous (duplicate label matches refuse the write).

Usage:
  python3 checker.py REPORT.html [--out OUT.txt] [--tol-frac 0.5] [--expect L,V]

Exit codes:
  0  unique diagnosis; answer written (and matches --expect, if given)
  1  usage / parse error (fix the command; never diagnose data from exit 1)
  2  diagnosis refused: 0 or >1 violations, no unique root, or duplicate-base
     ambiguity -- nothing written, diagnostics on stdout/stderr
  3  REGRESSION MISMATCH: the --expect pin differs from the computed answer
     -- nothing written; re-run without --expect to write. --expect is a
     development regression pin for a value you derived yourself (see
     references/selftest.sh); never feed it the instruction's example output,
     which illustrates format, not the variant's answer.

Extension points (for unseen variants):
  * Multi-period columns: growth/difference checks activate automatically when a
    table has >= 2 numeric columns.
  * Unit conversions are label-anchored: a metric whose label declares a unit
    ('(in $000s)', 'in millions', '$M', ...) is checked against its plain
    partner with the same semantic label (expected = plain x factor).
  * Remaining boundaries (need a new builder or a copy-and-extend):
    subtitle-declared units ('Dollars in millions' outside the labels) and
    mixed-unit subtotals. Add a builder in build_checks() following the same
    pattern; the exactly-one-violation assertion protects against mis-pairing.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# HTML parsing -> rows of raw cell strings
# ---------------------------------------------------------------------------

class TableParser(HTMLParser):
    """Collect every <table> as a list of rows, each row a list of cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._cur_table: list[list[str]] | None = None
        self._cur_row: list[str] | None = None
        self._cur_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._cur_table = []
        elif tag == "tr" and self._cur_table is not None:
            self._cur_row = []
        elif tag in ("td", "th") and self._cur_row is not None:
            self._cur_cell = []

    def handle_data(self, data):
        if self._cur_cell is not None:
            self._cur_cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cur_cell is not None:
            self._cur_row.append("".join(self._cur_cell).strip())
            self._cur_cell = None
        elif tag == "tr" and self._cur_row is not None:
            if any(c for c in self._cur_row):
                self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif tag == "table" and self._cur_table is not None:
            self.tables.append(self._cur_table)
            self._cur_table = None


# ---------------------------------------------------------------------------
# Cell classification
# ---------------------------------------------------------------------------

VALUE_GRAMMAR = re.compile(
    r"^\s*(?P<cur>[$€£¥])?\s*(?P<open>\()?\s*(?P<sign>[+-]?)\s*"
    r"(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<close>\))?\s*(?P<pct>%)?\s*$"
)
PURE_INT = re.compile(r"^\d+$")
LINE_LIKE = re.compile(r"^\D*\d+\D*$")


def classify(cell: str):
    """Return ('value', Decimal, decimals, is_pct) | ('line', str) | ('label', str)."""
    s = cell.strip()
    if not s:
        return None
    m = VALUE_GRAMMAR.match(s)
    if m:
        is_pct = bool(m.group("pct"))
        has_cur = bool(m.group("cur"))
        num = Decimal(m.group("num").replace(",", ""))
        if m.group("sign") == "-" or m.group("open"):
            num = -num
        frac = m.group("num").split(".")[1] if "." in m.group("num") else ""
        decimals = len(frac)
        # A bare integer is ambiguous (line token vs whole-number value).
        # Classify bare ints as 'maybe_int'; the row/header context decides.
        if not is_pct and not has_cur and not m.group("open") and not m.group("sign") \
                and "," not in m.group("num") and "." not in m.group("num"):
            return ("maybe_int", s)
        return ("value", num, decimals, is_pct, s)
    if PURE_INT.match(s):
        return ("maybe_int", s)
    if LINE_LIKE.match(s):
        return ("line", s)
    return ("label", s)


def is_header_row(row: list[str]) -> bool:
    """A header row has >= 2 non-empty cells and no numeric-value cells.
    Accepts period tokens ('Q2 2025' -> label, 'FY 2024' -> line-like,
    '2025' -> maybe_int). Caption/note rows pass this test too, so
    extract_metrics additionally requires usable roles (see there)."""
    non_empty = [c for c in row if c.strip()]
    if len(non_empty) < 2:
        return False
    for c in non_empty:
        k = classify(c)
        if k is None or k[0] == "value":
            return False
    return True


def role_map_from_header(row: list[str]):
    """Map column index -> ('line'|'label'|('value', colname)).

    Period columns are recognized by a 4-digit year / Q1-4 / FY / H1-2 token.
    """
    roles = {}
    for idx, cell in enumerate(row):
        low = cell.strip().lower()
        if "line" in low or "ref" in low or "no" == low:
            roles[idx] = "line"
        elif "value" in low or "amount" in low or "figure" in low or "total" in low:
            roles[idx] = ("value", cell.strip())
        elif re.search(r"\b(19|20)\d{2}\b", low) or re.search(r"\bq[1-4]\b", low) \
                or re.search(r"\b(fy|h1|h2)\b", low) or "period" in low \
                or "prior" in low or "current" in low or "previous" in low:
            roles[idx] = ("value", cell.strip())
        else:  # metric / label / item / kpi / description ...
            roles[idx] = "label"
    return roles


# ---------------------------------------------------------------------------
# Extract metric triples from raw tables
# ---------------------------------------------------------------------------

def extract_metrics(tables) -> tuple[list[dict], dict[int, list[str]]]:
    """Return (metrics, table_cols) where table_cols[tid] lists value-column
    names in document order (needed for YoY/difference pairing)."""
    metrics = []
    table_cols: dict[int, list[str]] = {}
    order = 0
    for tid, rows in enumerate(tables):
        header_roles = None
        data_rows = rows
        if rows and is_header_row(rows[0]):
            candidate = role_map_from_header(rows[0])
            value_roles = [r for r in candidate.values() if isinstance(r, tuple)]
            has_line = "line" in candidate.values()
            # accept as a header only if it maps usable roles: at least one
            # value column and (a line column or >= 2 value columns); this
            # keeps caption rows (e.g. 'All figures in $M') out of header mode
            if value_roles and (has_line or len(value_roles) >= 2):
                header_roles = candidate
                data_rows = rows[1:]
        value_cols = []  # list of (col_index, colname) for this table
        if header_roles:
            value_cols = [(i, name) for i, name in header_roles.items()
                          if isinstance(name, tuple)]
        table_cols[tid] = [name[1] for _, name in value_cols]

        def emit(line, label, kind, colname, colpos, row_id):
            nonlocal order
            _, num, decimals, is_pct, shown = kind
            metrics.append(dict(order=order, table=tid, col=colname, colpos=colpos,
                                row=row_id, line=line, label=label or "",
                                shown=shown, num=num,
                                decimals=decimals, is_pct=is_pct))
            order += 1

        for rid, row in enumerate(data_rows):
            cells = [c.strip() for c in row]
            if header_roles is None:
                # positional fallback: first int-ish cell = line, first text = label,
                # remaining numeric cells = values
                line = None
                label = None
                values = []
                classified = [classify(c) for c in cells]
                for c, kind in zip(cells, classified):
                    if kind is None:
                        continue
                    if kind[0] in ("maybe_int", "line") and line is None and not values:
                        line = c
                    elif kind[0] in ("maybe_int", "value"):
                        # wrap bare ints as values exactly like header mode so
                        # sparse/odd rows cannot crash emit() with a 2-tuple
                        values.append(("value", Decimal(c), 0, False, c)
                                      if kind[0] == "maybe_int" else kind)
                    elif label is None:
                        label = c
                if not values:
                    continue
                if not table_cols[tid]:
                    table_cols[tid] = [f"Col{i}" for i in range(len(values))]
                for colpos, kind in enumerate(values):
                    colname = table_cols[tid][colpos] if colpos < len(table_cols[tid]) else f"Col{colpos}"
                    emit(line, label, kind, colname, colpos, rid)
            else:
                line_cell = None
                label_cell = None
                value_cells = []  # (colpos, colname, kind)
                for idx, c in enumerate(cells):
                    role = header_roles.get(idx)
                    if role == "line":
                        line_cell = c
                    elif role == "label" and label_cell is None:
                        label_cell = c
                    elif isinstance(role, tuple) and c:
                        kind = classify(c)
                        if kind and kind[0] == "value":
                            colpos = table_cols[tid].index(role[1]) if role[1] in table_cols[tid] else len(value_cells)
                            value_cells.append((colpos, role[1], kind))
                        elif kind and kind[0] == "maybe_int":
                            colpos = table_cols[tid].index(role[1]) if role[1] in table_cols[tid] else len(value_cells)
                            value_cells.append((colpos, role[1],
                                                ("value", Decimal(c), 0, False, c)))
                if not value_cells:
                    continue
                for colpos, colname, kind in value_cells:
                    emit(line_cell, label_cell, kind, colname, colpos, rid)
    return metrics, table_cols


# ---------------------------------------------------------------------------
# Label semantics helpers
# ---------------------------------------------------------------------------

def norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


REVENUE_EXACT = {"revenue", "net revenue", "total revenue", "sales", "net sales",
                 "total sales", "gross sales", "turnover", "net turnover",
                 "product revenue", "service revenue", "services revenue"}


def is_revenue(m: dict) -> bool:
    n = norm(m["label"])
    if not is_plain(m):
        return False
    if n in REVENUE_EXACT:
        return True
    if "revenue" in n or "turnover" in n or "sales" in n:
        for bad in ("cost", "expense", "marketing", "other"):
            if bad in n:
                return False
        return "sales" in n or "revenue" in n or "turnover" in n
    return False


def is_cost_of_revenue(m: dict) -> bool:
    n = norm(m["label"])
    return is_plain(m) and any(k in n for k in ("cost of revenue", "cost of sales",
                                                "cost of goods", "cogs", "cost of services"))


def is_gross_profit(m: dict) -> bool:
    return is_plain(m) and "gross profit" in norm(m["label"]) and not m["is_pct"]


def is_operating_income(m: dict) -> bool:
    n = norm(m["label"])
    return is_plain(m) and (("operating income" in n or "operating profit" in n or n == "ebit")
                            and not m["is_pct"])


def is_net_income(m: dict) -> bool:
    n = norm(m["label"])
    return is_plain(m) and any(k in n for k in ("net income", "net earnings", "net profit")) and not m["is_pct"]


MARGIN_KINDS = {
    "gross": ("gross profit",),
    "operating": ("operating income", "operating profit", "ebit"),
    "net": ("net income", "net earnings", "net profit"),
    "ebitda": ("ebitda",),
}


# Label-anchored unit scaling: a label that declares a unit (e.g.
# "Revenue (in $000s)", "(in millions)", "$M") defines its numeric value's
# scale. Ordered by magnitude so the first match wins.
UNIT_PATTERNS = [
    (re.compile(r"\$b\b|billions?|\bbn\b", re.I), Decimal("1e9")),
    (re.compile(r"\$m\b|millions?|\bmn\b|\bmm\b", re.I), Decimal("1e6")),
    (re.compile(r"\$k\b|thousands?|\b000'?s\b", re.I), Decimal("1e3")),
]


def unit_factor(label: str) -> Decimal:
    """Scale factor declared in the label; 1 when no unit token is present."""
    for pat, fac in UNIT_PATTERNS:
        if pat.search(label):
            return fac
    return Decimal(1)


def is_plain(m: dict) -> bool:
    """Scale-duplicate guard. A unit-annotated metric (label declares
    thousands/millions/billions, e.g. 'Revenue (in $000s)') is the *same
    quantity at another scale*; it participates only in the unit-conversion
    relation. All other base searches (margins, identities, EPS, growth)
    operate on the plain (unit-free) layer, so a conversion row can never
    count as a duplicate base candidate. A metric family that exists ONLY in
    annotated form (units declared in a subtitle) is the documented subtitle
    boundary: it stays unmatched -> found-0 abort rather than silent
    descaling."""
    return unit_factor(m["label"]) == 1


def find_shares(metrics):
    """Locate the per-share denominator: plain share-count metrics first;
    if none exist, fall back to unit-annotated ones (a report usually states
    'Shares (in millions)' while net income is plain dollars -- the EPS ratio
    is then scale-consistent). Returns (best, count); count > 1 among the
    selected pool still flags genuinely distinct share labels."""
    cands = [m for m in metrics
             if "share" in norm(m["label"])
             and "per share" not in norm(m["label"])
             and not m["is_pct"]]
    if not cands:
        return None, 0
    pool = [m for m in cands if is_plain(m)] or cands
    return min(pool, key=lambda m: m["order"]), len(pool)


def semantic_label(label: str) -> str:
    """Label with unit tokens and leftover parens stripped, normalized."""
    s = label
    for pat, _fac in UNIT_PATTERNS:
        s = pat.sub(" ", s)
    s = re.sub(r"\(\s*in\s*\$?\s*\)", " ", s)
    s = re.sub(r"\(\s*\)", " ", s)
    return norm(s)


def margin_kind(label: str):
    n = norm(label)
    if "margin" not in n:
        return None
    for kind in ("gross", "operating", "net", "ebitda"):
        if kind in n:
            return kind
    return None


def find_metric(metrics, pred, exclude=None):
    """Return (best_match, match_count). match_count > 1 means the base
    pairing was ambiguous (e.g. duplicated labels across tables) -- the write
    path must refuse to emit for checks that rely on such a base."""
    matches = [m for m in metrics
               if (exclude is None or m is not exclude) and pred(m)]
    if not matches:
        return None, 0
    return min(matches, key=lambda m: m["order"]), len(matches)


def period_key(colname: str):
    """Chronological sort key for a period column name, or None if not derivable."""
    low = colname.lower()
    m = re.search(r"\b(19|20)\d{2}\b", low)
    if not m:
        return None
    year = int(m.group(0))
    q = re.search(r"\bq([1-4])\b", low)
    qnum = int(q.group(1)) if q else 1
    return year * 4 + qnum


def ordered_columns(cols: list[str]) -> list[str]:
    """Chronological column order (oldest first) when all periods are derivable,
    otherwise document order."""
    keys = [period_key(c) for c in cols]
    if all(k is not None for k in keys):
        return [c for _, c in sorted(zip(keys, cols))]
    return list(cols)


# ---------------------------------------------------------------------------
# Check construction
# ---------------------------------------------------------------------------

def build_checks(metrics, table_cols) -> tuple[list[dict], list[str]]:
    checks = []
    unchecked = []
    touched = set()

    def add(metric, computed, formula, bases=(), ambiguous_orders=()):
        """Record one relation check. bases = metric dicts the computed value
        was derived from (needed by the root resolver); ambiguous_orders =
        orders of bases whose label matched multiple candidates."""
        checks.append(dict(metric=metric, computed=computed, formula=formula,
                           bases=list(bases),
                           ambiguous_orders=set(ambiguous_orders)))
        touched.add(id(metric))

    # --- margins / ratios (dollars may live in a different table) ----------
    for m in metrics:
        kind = margin_kind(m["label"])
        if not kind or not m["is_pct"]:
            continue
        num = None
        num_amb = ()
        for kw in MARGIN_KINDS[kind]:
            num, cnt = find_metric(metrics,
                                   lambda mm, kw=kw: kw in norm(mm["label"]) and not mm["is_pct"] and is_plain(mm))
            if num:
                num_amb = (num["order"],) if cnt > 1 else ()
                break
        den, den_cnt = find_metric(metrics, is_revenue) if num else (None, 0)
        if num and den and den["num"] != 0:
            amb = set(num_amb)
            if den_cnt > 1:
                amb.add(den["order"])
            add(m, Decimal(100) * num["num"] / den["num"],
                f"100*{num['label']}/{den['label']}",
                bases=[num, den], ambiguous_orders=amb)

    # --- subtotals: 'total ...' sums the contiguous block above, bounded by
    #     the nearest computed line (profit/income/margin/total/...) ---------
    for m in metrics:
        n = norm(m["label"])
        if "total" not in n or m["is_pct"] or is_revenue(m):
            continue
        prev_computed = None
        for other in metrics:
            if other["table"] != m["table"] or other["order"] >= m["order"]:
                continue
            on = norm(other["label"])
            if other is m:
                continue
            if any(k in on for k in ("profit", "income", "margin", "total",
                                     "earnings", "ebitda", "expenses")):
                prev_computed = other
        if prev_computed is None:
            children = [o for o in metrics
                        if o["table"] == m["table"] and o["order"] < m["order"]]
        else:
            children = [o for o in metrics
                        if o["table"] == m["table"]
                        and prev_computed["order"] < o["order"] < m["order"]]
        if children:
            add(m, sum((c["num"] for c in children), Decimal(0)),
                "+".join(c["label"] for c in children),
                bases=children)

    # --- income-statement identities (same table) --------------------------
    rev, rev_cnt = find_metric(metrics, is_revenue)
    cost, cost_cnt = find_metric(metrics, is_cost_of_revenue)
    for m in metrics:
        if is_gross_profit(m) and not m["is_pct"]:
            if rev and cost and rev["table"] == cost["table"] == m["table"]:
                amb = set()
                if rev_cnt > 1:
                    amb.add(rev["order"])
                if cost_cnt > 1:
                    amb.add(cost["order"])
                add(m, rev["num"] - cost["num"], f"{rev['label']}-{cost['label']}",
                    bases=[rev, cost], ambiguous_orders=amb)
        if is_operating_income(m) and not m["is_pct"]:
            gp, gp_cnt = find_metric(metrics, is_gross_profit)
            opex, opex_cnt = find_metric(metrics,
                                         lambda mm: "total operating" in norm(mm["label"])
                                         and not mm["is_pct"] and is_plain(mm))
            if gp and opex and gp["table"] == opex["table"] == m["table"]:
                amb = set()
                if gp_cnt > 1:
                    amb.add(gp["order"])
                if opex_cnt > 1:
                    amb.add(opex["order"])
                add(m, gp["num"] - opex["num"], f"{gp['label']}-{opex['label']}",
                    bases=[gp, opex], ambiguous_orders=amb)
        if is_net_income(m) and not m["is_pct"]:
            op, op_cnt = find_metric(metrics, is_operating_income)
            other, other_cnt = find_metric(metrics,
                                           lambda mm: ("other income" in norm(mm["label"])
                                                       or "other expense" in norm(mm["label"]))
                                           and is_plain(mm))
            if op and op["table"] == m["table"]:
                amb = set()
                if op_cnt > 1:
                    amb.add(op["order"])
                if other and other_cnt > 1:
                    amb.add(other["order"])
                if other and other["table"] == m["table"]:
                    sign = 1 if "income" in norm(other["label"]) else -1
                    add(m, op["num"] + sign * other["num"],
                        f"{op['label']}{'+' if sign > 0 else '-'}{other['label']}",
                        bases=[op, other], ambiguous_orders=amb)
                else:
                    add(m, op["num"], f"{op['label']}",
                        bases=[op], ambiguous_orders=amb)

    # --- per-share / EPS ----------------------------------------------------
    for m in metrics:
        n = norm(m["label"])
        if ("per share" in n or n == "eps" or n.startswith("eps ")
                or " eps" in n) and not m["is_pct"]:
            ni, ni_cnt = find_metric(metrics, is_net_income)
            sh, sh_cnt = find_shares(metrics)
            if ni and sh and sh["num"] != 0:
                amb = set()
                if ni_cnt > 1:
                    amb.add(ni["order"])
                if sh_cnt > 1:
                    amb.add(sh["order"])
                add(m, ni["num"] / sh["num"], f"{ni['label']}/{sh['label']}",
                    bases=[ni, sh], ambiguous_orders=amb)

    # --- unit conversion: same semantic label, different unit scales -------
    # Asymmetric by design: the plain (unit-free) metric is the base and the
    # unit-annotated metric is derived (expected = plain x factor). Anchoring
    # on labels only, not on subtitle notes; a report whose error sits on the
    # plain side (or whose unit is declared in a subtitle) is a documented
    # blind spot -- it surfaces as a found-0 abort with the annotated line
    # unchecked.
    for m in metrics:
        if m["is_pct"]:
            continue
        fac = unit_factor(m["label"])
        if fac == 1:
            continue
        sem = semantic_label(m["label"])
        partners = [p for p in metrics
                    if p["order"] != m["order"] and not p["is_pct"]
                    and unit_factor(p["label"]) == 1
                    and semantic_label(p["label"]) == sem]
        if len(partners) == 1:
            p = partners[0]
            add(m, p["num"] * fac,
                f"{m['label']} = {p['label']} x {int(fac)}",
                bases=[p])

    # --- growth / difference (>= 2 value columns in the table) -------------
    # Two pairing mechanisms:
    #   (a) label-based: a 'Revenue growth' row states a %, while the base lives
    #       in the 'Revenue' row's two period columns; the growth metric's own
    #       period column is matched against the chronologically previous one.
    #   (b) same-row fallback: the growth row itself carries cur and prev
    #       columns (adjacent-column difference).
    GROWTH_WORDS = ("growth", "yoy", "vs", "change", "increase", "decrease",
                    "decline", "trend", "difference", "delta")
    for m in metrics:
        n = norm(m["label"])
        if not any(w in n for w in GROWTH_WORDS):
            continue
        cols = table_cols.get(m["table"], [])
        if m["colpos"] is None or m["colpos"] >= len(cols):
            continue
        cur_col = cols[m["colpos"]]
        ordered = ordered_columns(cols)
        if cur_col not in ordered:
            continue
        idx = ordered.index(cur_col)
        if idx <= 0:
            continue
        prev_col = ordered[idx - 1]

        # (a) label-based: strip growth words -> base label
        base_n = n
        for w in ("year over year", "quarter over quarter", "prior year",
                  "growth", "yoy", "change", "increase", "decrease",
                  "decline", "trend", "difference", "delta", "vs"):
            base_n = base_n.replace(w, " ")
        base_n = re.sub(r"\s+", " ", base_n).strip()
        cur_base = prev_base = None
        for o in metrics:
            if o["table"] != m["table"] or o is m:
                continue
            on = norm(o["label"])
            match = (on == base_n) or (base_n == "revenue" and is_revenue(o)) \
                or (base_n == "net income" and is_net_income(o)) \
                or (base_n == "operating income" and is_operating_income(o)) \
                or (base_n == "gross profit" and is_gross_profit(o))
            if not match:
                continue
            if o["col"] == cur_col:
                cur_base = o
            elif o["col"] == prev_col:
                prev_base = o
        if cur_base is not None and prev_base is not None and prev_base["num"] != 0:
            if m["is_pct"]:
                add(m, Decimal(100) * (cur_base["num"] - prev_base["num"]) / prev_base["num"],
                    f"100*({cur_base['label']} {cur_col}-{prev_col})/{prev_col}:{prev_base['shown']}",
                    bases=[cur_base, prev_base])
            else:
                add(m, cur_base["num"] - prev_base["num"],
                    f"{cur_base['label']} {cur_col}-{prev_col}",
                    bases=[cur_base, prev_base])
            continue
        # (b) same-row fallback: sibling metric in the previous column
        sib = None
        for o in metrics:
            if o["table"] == m["table"] and o["row"] == m["row"] \
                    and o["col"] == prev_col and o is not m:
                sib = o
                break
        if sib is None or sib["num"] == 0:
            continue
        if m["is_pct"]:
            add(m, Decimal(100) * (m["num"] - sib["num"]) / sib["num"],
                f"100*({m['label']} {m['col']}-{sib['col']})/{sib['col']}:{sib['shown']}",
                bases=[sib])
        else:
            add(m, m["num"] - sib["num"],
                f"{m['label']} {m['col']}-{sib['col']}",
                bases=[sib])

    for m in metrics:
        if id(m) not in touched:
            unchecked.append(m)
    return checks, unchecked


# ---------------------------------------------------------------------------
# Main: recompute, diff, assert exactly one violation, write answer
# ---------------------------------------------------------------------------

def clean_value(shown: str) -> str:
    """Echo the displayed value verbatim minus forbidden tokens (% and currency)."""
    s = shown.strip()
    s = s.rstrip("%")
    s = re.sub(r"^[$€£¥]\s*", "", s)
    return s.strip()


def round_to_display(computed: Decimal, decimals: int) -> Decimal:
    exp = Decimal(1).scaleb(-decimals)
    return computed.quantize(exp, rounding=ROUND_HALF_UP)


def violation_of(chk: dict, tol_frac: Decimal):
    """Return (metric, chk, expected, diff) if the check violates display
    precision, else None. Same tolerance rule as the main path."""
    m = chk["metric"]
    expected = round_to_display(chk["computed"], m["decimals"])
    unit = Decimal(1).scaleb(-m["decimals"])
    tol = tol_frac * unit
    diff = abs(m["num"] - expected)
    if diff <= tol:
        return None
    return (m, chk, expected, diff)


def resolve_root(metrics, table_cols, checks, violations, tol_frac: Decimal):
    """Root-cause resolver for a fan of >= 2 violations.

    Family warrant: exactly ONE displayed value is wrong. In a fan, each
    violated check names its bases; the true root is the base metric whose
    correction (override num with its own derived value) makes every check
    consistent again -- except the root's own displayed mismatch, which is the
    answer we are looking for. Exactly one candidate can satisfy this; any
    other hypothesis leaves the true root's chain violated.

    Candidates are restricted to bases that are themselves derivable (they are
    the dependent metric of at least one check). Independent bases (Revenue,
    Other income, single expense lines) have no self-relation and are a
    documented blind spot: they stay aborts.

    Returns the list of zeroing roots (expect length 1 to emit).
    """
    candidates = {}
    for v in violations:
        chk = v[1]  # violations are (metric, check, expected, diff) tuples
        for b in chk["bases"]:
            if b["order"] == chk["metric"]["order"]:
                continue
            # derivable? appears as the dependent metric of at least one check
            if any(c["metric"]["order"] == b["order"] for c in checks):
                candidates[b["order"]] = b
    zeros = []
    for b in candidates.values():
        own = next(c for c in checks if c["metric"]["order"] == b["order"])
        fixed = copy.deepcopy(metrics)
        target = next(mm for mm in fixed if mm["order"] == b["order"])
        target["num"] = own["computed"]
        c2, _ = build_checks(fixed, table_cols)
        v2 = [c for c in c2 if c["metric"]["order"] != b["order"]
              and violation_of(c, tol_frac) is not None]
        if not v2:
            zeros.append(b)
    return zeros


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="path to the HTML financial report")
    ap.add_argument("--out", help="output file for 'line,value' answer")
    ap.add_argument("--tol-frac", type=float, default=0.5,
                    help="tolerance as fraction of one display unit (default 0.5)")
    ap.add_argument("--expect", help="optional 'line,value' regression check")
    args = ap.parse_args(argv)

    try:
        with open(args.report, encoding="utf-8") as fh:
            html = fh.read()
    except OSError as e:
        print(f"error: cannot read report: {e}", file=sys.stderr)
        return 1

    parser = TableParser()
    try:
        parser.feed(html)
    except Exception as e:  # pragma: no cover
        print(f"error: HTML parse failed: {e}", file=sys.stderr)
        return 1

    metrics, table_cols = extract_metrics(parser.tables)
    if not metrics:
        print("error: no metric rows parsed from report", file=sys.stderr)
        return 1

    checks, unchecked = build_checks(metrics, table_cols)
    tol_frac = Decimal(str(args.tol_frac))

    print(f"parsed {len(metrics)} metric triples across {len(parser.tables)} tables; "
          f"{len(checks)} relation checks")
    violations = []
    for chk in checks:
        v = violation_of(chk, tol_frac)
        status = "VIOLATION" if v else "OK"
        m = chk["metric"]
        expected = round_to_display(chk["computed"], m["decimals"])
        print(f"  [{status}] line={m['line']!r} {m['label']!r} "
              f"shown={m['shown']!r} computed={chk['computed']} "
              f"->{expected} ({chk['formula']})")
        if v:
            violations.append(v)

    if unchecked:
        print("  [note] metrics with no derivable relation (bases or unsupported):")
        for m in unchecked:
            print(f"         line={m['line']!r} {m['label']!r} shown={m['shown']!r} [{m['col']}]")

    def refuse(reason: str) -> int:
        print(f"REFUSE: {reason} No answer written.", file=sys.stderr)
        return 2

    # ------------------------------------------------------------------
    # Case 1: exactly one violation -> the shown metric is the planted    
    # error (a victim-only fan is impossible: a wrong derivable root also  
    # violates its own check, so roots always fan to >= 2; a wrong         
    # independent base can fan to exactly one victim check -- documented   
    # blind spot, see SKILL.md Step 4).                                    
    # ------------------------------------------------------------------
    if len(violations) == 1:
        m, chk, expected, _diff = violations[0]
        # duplicate-base pairing guard: refuse when the winning check used
        # an ambiguously located base (latent wrong-answer risk)
        if chk["ambiguous_orders"]:
            print("  [warn] duplicate base candidates for "
                  + ", ".join(str(x) for x in sorted(chk["ambiguous_orders"])))
            return refuse(f"the winning check (line {m['line']!r} {m['label']!r}) used "
                          "a base with duplicate label matches; cannot trust the pairing")
        answer = f"{m['line']},{clean_value(m['shown'])}"
        print(f"ANSWER: {answer}  (line={m['line']!r}, shown wrong value {m['shown']!r}, "
              f"recomputed {chk['computed']} -> {expected})")

    # ------------------------------------------------------------------
    # Case 2: violation fan -> root-cause resolver                        
    # ------------------------------------------------------------------
    elif len(violations) > 1:
        print(f"  [fan] {len(violations)} violations; running root-cause resolver...")
        roots = resolve_root(metrics, table_cols, checks, violations, tol_frac)
        if len(roots) == 1:
            b = roots[0]
            all_amb = set()
            for c in checks:
                all_amb |= set(c["ambiguous_orders"])
            own = next(c for c in checks if c["metric"]["order"] == b["order"])
            if b["order"] in all_amb or own["ambiguous_orders"]:
                return refuse(f"resolved root line={b['line']!r} {b['label']!r} but its "
                              "base pairing is ambiguous; cannot trust the derivation")
            answer = f"{b['line']},{clean_value(b['shown'])}"
            print(f"ANSWER: {answer}  (root line={b['line']!r} {b['label']!r}, "
                  f"shown wrong value {b['shown']!r}; overriding it to its derived "
                  f"value {own['computed']} zeroes the whole fan)")
        elif len(roots) == 0:
            return refuse("no unique root: no candidate base (with its own derivable "
                          "relation) zeroes the fan. Either the report contains two "
                          "independent errors, or the true root is an independent base "
                          "(Revenue, Other income, an expense line) with no self-relation "
                          "-- inspect the unchecked metrics and the fan above")
        else:
            return refuse(f"multiple roots ({len(roots)}) each zero the fan; "
                          "base pairing too ambiguous to emit")
    else:
        return refuse(f"expected exactly one violated relation, found 0. The relation "
                      "set missed the planted relation or all values are consistent; "
                      "extend the relation taxonomy and inspect the unchecked metrics")

    if args.expect:
        if answer != args.expect:
            print(f"REGRESSION MISMATCH: expected {args.expect!r}, got {answer!r} "
                  f"-- re-run without --expect to write the computed answer",
                  file=sys.stderr)
            return 3
        print(f"regression check passed: {answer}")

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(answer + "\n")
            print(f"wrote {args.out}")
        except OSError as e:
            print(f"error: cannot write {args.out}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())