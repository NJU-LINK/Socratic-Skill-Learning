#!/usr/bin/env python3
"""
Generic HTML financial report verifier.

Parses an HTML earnings report containing line-numbered financial metrics,
checks all internal arithmetic and ratio relationships, and identifies
the single incorrect metric.

Usage:
    python3 verify_report.py [html_file] [output_file]

Defaults: html_file = /app/q2_earnings_report.html
          output_file = /app/value.txt
"""

import sys
import re
import os
from html.parser import HTMLParser
from collections import OrderedDict


# ── HTML Parsing ──────────────────────────────────────────────────────────

class TableExtractor(HTMLParser):
    """Extract all <table> elements, capturing cell text and source line."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._cell_line = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._table = []
        elif t == "tr" and self._table is not None:
            self._row = []
        elif t in ("td", "th") and self._row is not None:
            self._cell = ""
            self._cell_line = self.getpos()[0]

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._cell is not None:
            self._row.append((self._cell.strip(), self._cell_line))
            self._cell = None
        elif t == "tr" and self._row is not None:
            if self._table is not None:
                self._table.append(self._row)
            self._row = None
        elif t == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data


def load_tables(path):
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    p = TableExtractor()
    p.feed(html)
    return p.tables


# ── Value Parsers ─────────────────────────────────────────────────────────

def parse_dollar(s):
    """'$842.0' / '$(12.3)' / '-$5.0' / '842.0' -> float | None"""
    s = s.strip().replace(",", "").replace(" ", "").replace("\xa0", "")
    m = re.match(r"^-?\$?\(?([\d.]+)\)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    if "(" in s or s.startswith("-"):
        v = -v
    return v


def parse_percent(s):
    """'60.8%' / '28.5' -> float | None"""
    s = s.strip().replace(" ", "").replace("\xa0", "")
    m = re.match(r"^([\d.]+)\s*%?$", s)
    return float(m.group(1)) if m else None


def parse_int(s):
    s = s.strip()
    return int(s) if re.match(r"^\d+$", s) else None


# ── Metric Extraction ─────────────────────────────────────────────────────

def extract_metrics(tables):
    """
    Return OrderedDict  line_no -> dict(name, dollar, percent, raw).
    Expects each data row to have >= 3 cells where one cell is an integer
    line number.
    """
    metrics = OrderedDict()
    for tbl in tables:
        for row in tbl:
            if len(row) < 2:
                continue
            texts = [c[0] for c in row]
            # find line-number cell
            line_no = None
            ln_idx = None
            for i, txt in enumerate(texts):
                n = parse_int(txt)
                if n is not None and 50 <= n <= 9999:
                    line_no = n
                    ln_idx = i
                    break
            if line_no is None:
                continue
            # remaining cells in order (skip the line-number cell)
            rest = [c for j, c in enumerate(row) if j != ln_idx]
            if not rest:
                continue
            name = rest[0][0] if len(rest) >= 2 else ""
            raw = rest[-1][0]
            dollar = parse_dollar(raw)
            pct = parse_percent(raw)
            if dollar is not None or pct is not None:
                metrics[line_no] = dict(
                    name=name.strip(),
                    dollar=dollar,
                    percent=pct,
                    raw=raw.strip(),
                )
    return metrics


# ── Name-Based Lookup Helpers ─────────────────────────────────────────────

def _build_lookup(metrics):
    """name_lower -> (line_no, metric_dict)"""
    d = {}
    for ln, m in metrics.items():
        d[m["name"].lower()] = (ln, m)
    return d


def _find_dollar(lookup, patterns):
    for pat in patterns:
        for key, (ln, m) in lookup.items():
            if pat in key and m["dollar"] is not None:
                return ln, m["dollar"]
    return None, None


def _find_pct(lookup, patterns):
    for pat in patterns:
        for key, (ln, m) in lookup.items():
            if pat in key and m["percent"] is not None:
                return ln, m["percent"]
    return None, None


# ── Relationship Checks ──────────────────────────────────────────────────

TOL = 0.15          # tolerance for dollar rounding (millions)
PTOL = 0.15         # tolerance for percentage points


def check(metrics):
    """
    Return list of dicts:
      { 'involved': set(line_nos), 'bad_line': line_no,
        'reported': val, 'expected': val, 'desc': str }
    """
    lk = _build_lookup(metrics)
    errs = []

    def gd(pats):
        return _find_dollar(lk, pats)

    def gpct(pats):
        return _find_pct(lk, pats)

    # -- dollar amounts --
    ln_rev, rev       = gd(["revenue", "total revenue", "net revenue", "sales"])
    ln_cogs, cogs     = gd(["cost of revenue", "cost of goods", "cogs",
                             "cost of sales"])
    ln_gp, gp         = gd(["gross profit", "gross income"])
    ln_opex, opex     = gd(["total operating expenses", "operating expenses",
                             "total opex"])
    ln_oi, oi         = gd(["operating income", "operating profit"])
    # EBIT fallback
    if ln_oi is None:
        ln_oi, oi = gd(["ebit"])
    ln_oth, oth       = gd(["other income", "other expense", "interest income",
                             "interest expense", "non-operating"])
    ln_ni, ni         = gd(["net income", "net earnings", "net profit"])
    ln_tax, tax       = gd(["income tax", "tax expense", "tax provision"])
    ln_pt, pt         = gd(["income before tax", "pretax", "pre-tax"])

    def err(involved, bad, reported, expected, desc):
        errs.append(dict(involved=involved, bad_line=bad,
                         reported=reported, expected=expected, desc=desc))

    # 1) Revenue - COGS = Gross Profit
    if None not in (rev, cogs, gp):
        exp = rev - cogs
        if abs(exp - gp) > TOL:
            err({ln_rev, ln_cogs, ln_gp}, ln_gp, gp, exp,
                "GP: Rev({}) - COGS({}) = {}, got {}".format(
                    rev, cogs, exp, gp))

    # 2) Sum of component OpEx items = Total OpEx
    comp_keywords = ["research", "development", "r&d",
                     "sales", "marketing", "s&m",
                     "general", "administrative", "sg&a", "sga",
                     "depreciation", "amortization", "d&a"]
    comp_excl = {"total operating expenses", "operating expenses",
                 "total opex", "total operating expense"}
    components = []
    for key, (ln, m) in lk.items():
        if m["dollar"] is not None and key not in comp_excl:
            if any(kw in key for kw in comp_keywords):
                components.append((ln, m["dollar"]))
    if components and opex is not None:
        s = sum(v for _, v in components)
        if abs(s - opex) > TOL:
            comp_lines = {ln for ln, _ in components}
            err(comp_lines | {ln_opex}, ln_opex, opex, s,
                "Total OpEx: sum({}) != {}".format(s, opex))

    # 3) Gross Profit - OpEx = Operating Income
    if None not in (gp, opex, oi):
        exp = gp - opex
        if abs(exp - oi) > TOL:
            err({ln_gp, ln_opex, ln_oi}, ln_oi, oi, exp,
                "OI: GP({}) - OpEx({}) = {}, got {}".format(
                    gp, opex, exp, oi))

    # 4) Operating Income + Other Income (- Tax) = Net Income
    if None not in (oi, oth, ni):
        if pt is not None and tax is not None:
            exp_pt = oi + oth
            if abs(exp_pt - pt) > TOL:
                err({ln_oi, ln_oth, ln_pt}, ln_pt, pt, exp_pt,
                    "Pre-tax: OI({}) + Other({}) = {}, got {}".format(
                        oi, oth, exp_pt, pt))
            exp_ni = pt - tax
            if abs(exp_ni - ni) > TOL:
                err({ln_pt, ln_tax, ln_ni}, ln_ni, ni, exp_ni,
                    "NI: Pretax({}) - Tax({}) = {}, got {}".format(
                        pt, tax, exp_ni, ni))
        else:
            exp = oi + oth
            if abs(exp - ni) > TOL:
                err({ln_oi, ln_oth, ln_ni}, ln_ni, ni, exp,
                    "NI: OI({}) + Other({}) = {}, got {}".format(
                        oi, oth, exp, ni))

    # -- percentage KPIs --
    if rev and rev > 0:
        # 5) Gross margin = GP / Rev * 100
        ln_gm, gm = gpct(["gross margin"])
        if ln_gm is not None and gp is not None:
            exp = round(gp / rev * 100, 1)
            if abs(exp - gm) > PTOL:
                err({ln_gm}, ln_gm, gm, exp,
                    "Gross margin: {}/{}*100 = {}%, got {}%".format(
                        gp, rev, exp, gm))

        # 6) Operating margin = OI / Rev * 100
        ln_om, om = gpct(["operating margin", "oper margin", "op margin"])
        if ln_om is not None and oi is not None:
            exp = round(oi / rev * 100, 1)
            if abs(exp - om) > PTOL:
                err({ln_om}, ln_om, om, exp,
                    "Operating margin: {}/{}*100 = {}%, got {}%".format(
                        oi, rev, exp, om))

        # 7) Net margin = NI / Rev * 100
        ln_nm, nm = gpct(["net margin", "net profit margin"])
        if ln_nm is not None and ni is not None:
            exp = round(ni / rev * 100, 1)
            if abs(exp - nm) > PTOL:
                err({ln_nm}, ln_nm, nm, exp,
                    "Net margin: {}/{}*100 = {}%, got {}%".format(
                        ni, rev, exp, nm))

        # 8) EBITDA margin
        ln_ebm, ebm = gpct(["ebitda margin"])
        if ln_ebm is not None:
            ln_ebitda, ebitda = gd(["ebitda", "adjusted ebitda"])
            if ebitda is not None:
                exp = round(ebitda / rev * 100, 1)
                if abs(exp - ebm) > PTOL:
                    err({ln_ebm}, ln_ebm, ebm, exp,
                        "EBITDA margin: {}/{}*100 = {}%, got {}%".format(
                            ebitda, rev, exp, ebm))

        # 9) Any other "X margin" percentage (generic: X_dollar / Rev)
        for key, (ln, m) in lk.items():
            if m["percent"] is not None and "margin" in key:
                already = ["gross margin", "operating margin", "oper margin",
                           "op margin", "net margin", "net profit margin",
                           "ebitda margin"]
                if any(skip in key for skip in already):
                    continue
                dollar_name = key.replace("margin", "").strip()
                ln_d, d_val = gd([dollar_name] if dollar_name else [])
                if d_val is not None:
                    exp = round(d_val / rev * 100, 1)
                    if abs(exp - m["percent"]) > PTOL:
                        err({ln}, ln, m["percent"], exp,
                            "{}: {}/{}*100 = {}%, got {}%".format(
                                m["name"], d_val, rev, exp, m["percent"]))

    # 10) EPS check
    ln_eps, eps = _find_dollar(lk, ["earnings per share", "diluted eps",
                                     "basic eps", "eps"])
    ln_sh, shares = _find_dollar(lk, ["shares", "share count",
                                       "weighted average shares",
                                       "diluted shares"])
    if eps is not None and shares is not None and ni is not None and shares > 0:
        exp = round(ni / shares, 2)
        if abs(exp - eps) > 0.05:
            err({ln_eps}, ln_eps, eps, exp,
                "EPS: NI({})/Shares({}) = {}, got {}".format(
                    ni, shares, exp, eps))

    # 11) YoY growth rates
    for key, (ln, m) in lk.items():
        if m["percent"] is not None and ("growth" in key or "yoy" in key
                                          or "year-over-year" in key
                                          or "change" in key):
            base = key
            for suffix in [" growth", " yoy", " year-over-year", " change"]:
                base = base.replace(suffix, "")
            base = base.strip()
            ln_cur, cur = gd([base] if base else [])
            ln_prev, prev = _find_dollar(lk, ["prior " + base,
                                               "previous " + base,
                                               base + " prior",
                                               base + " previous",
                                               "last year"])
            if cur is not None and prev is not None and prev > 0:
                exp = round((cur - prev) / prev * 100, 1)
                if abs(exp - m["percent"]) > PTOL:
                    err({ln}, ln, m["percent"], exp,
                        "{}: ({}/{}/{}*100 = {}%, got {}%".format(
                            m["name"], cur, prev, prev, exp, m["percent"]))

    return errs


# ── Error Isolation ───────────────────────────────────────────────────────

def isolate(metrics, errs):
    """
    Exactly one metric is wrong.  Find the line number that, if corrected,
    would resolve every failing relationship.
    """
    if not errs:
        return None

    # Single failure -> direct answer
    if len(errs) == 1:
        return errs[0]["bad_line"]

    # Multiple failures -> the wrong metric is in the intersection of all
    # involved-sets (the only line that touches every failing check).
    common = errs[0]["involved"].copy()
    for e in errs[1:]:
        common &= e["involved"]

    if len(common) == 1:
        return common.pop()

    # If intersection is empty or >1, prefer the bad_line that appears most
    from collections import Counter
    cnt = Counter()
    for e in errs:
        cnt[e["bad_line"]] += 1
    return cnt.most_common(1)[0][0]


# ── Output Formatting ─────────────────────────────────────────────────────

def format_answer(metrics, line_no):
    m = metrics[line_no]
    if m["percent"] is not None:
        v = str(m["percent"])
    else:
        v = str(m["dollar"])
    # normalise trailing zeros but keep >= 1 decimal
    if "." in v:
        v = v.rstrip("0").rstrip(".")
        if "." not in v:
            v += ".0"
    return "{},{}".format(line_no, v)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    html_file = sys.argv[1] if len(sys.argv) > 1 else "/app/q2_earnings_report.html"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/app/value.txt"

    if not os.path.exists(html_file):
        print("ERROR: not found: {}".format(html_file), file=sys.stderr)
        sys.exit(1)

    tables = load_tables(html_file)
    if not tables:
        print("ERROR: no <table> elements found", file=sys.stderr)
        sys.exit(1)

    metrics = extract_metrics(tables)
    if not metrics:
        print("ERROR: no line-numbered metrics found", file=sys.stderr)
        sys.exit(1)

    print("Extracted {} metrics:".format(len(metrics)))
    for ln, m in metrics.items():
        v = "${}".format(m["dollar"]) if m["dollar"] is not None else "{}%".format(m["percent"])
        print("  Line {}: {} = {}   (raw: {})".format(ln, m["name"], v, m["raw"]))

    errs = check(metrics)

    if not errs:
        print("\nAll relationships hold - no error detected.")
        sys.exit(1)

    print("\n{} relationship failure(s):".format(len(errs)))
    for e in errs:
        print("  Line {}: {}".format(e["bad_line"], e["desc"]))

    bad = isolate(metrics, errs)
    answer = format_answer(metrics, bad)
    print("\n>>> Answer: {}".format(answer))

    with open(output_file, "w") as fh:
        fh.write(answer + "\n")
    print("Written to {}".format(output_file))


if __name__ == "__main__":
    main()
