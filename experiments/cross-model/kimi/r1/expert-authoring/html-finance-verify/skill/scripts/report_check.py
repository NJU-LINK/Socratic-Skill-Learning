#!/usr/bin/env python3
"""Parse a line-numbered HTML financial report and check internal-consistency relations.

Stdlib only (no bs4/lxml needed).

Usage:
  report_check.py parse  FILE [--json]
  report_check.py auto   FILE [--tol T | --decimals D]
  report_check.py check  FILE REL [REL ...] [--tol T | --decimals D]

auto mode infers standard relations (subtotal sums, gross-profit / operating-
income / net-income identities, name-matched margins, growth rows) straight from
the parsed tables and checks them - zero transcription, zero authoring. Audit the
inferred relations it prints, then confirm the culprit with explicit `check`
relations before writing the answer.

REL syntax (each relation is one quoted argument, LHS and RHS split by '='):
  "@170 = @140 + @150 + @160"              subtotal / sum relations
  "@210 = round(@130 / @110 * 100, 1)"     ratio relations (margin, YoY, tax rate)
  "@310 = round((@110#0 - @110#1) / @110#1 * 100, 1)"   multi-column (YoY) tables

  @N    numeric value of the row whose DISPLAYED line label is N (first value column)
  @N#k  value column k (0-based) of that row, for tables with several period columns

Tolerance: a check passes when |LHS - RHS| <= tol. Default tol is half a unit of
the smallest displayed decimal place among referenced values (rounding tolerance),
plus a float epsilon. Override with --decimals D (tol = 0.5 * 10^-D) or --tol T.

check mode prints each relation's residual and a culprit summary: with exactly one
wrong value, the line(s) shared by ALL failing relations point at the bad metric.
"""
import json
import re
import sys
from html.parser import HTMLParser

NUM_RE = re.compile(r"^\(?\s*[+\-–−]?\s*[$€£¥]?\s*\d[\d,]*(?:\.\d+)?\s*%?\s*\)?$")
LINE_RE = re.compile(r"^[A-Za-z]?\d{1,6}$")
MISSING = {"", "-", "--", "—", "–", "−", "n/a", "N/A", "na", "NA"}


def parse_number(raw):
    """Normalize a displayed number: strip $/commas/%/whitespace, (x) and unicode minus -> negative."""
    s = raw.strip()
    if s in MISSING:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = (s.replace(",", "").replace("$", "").replace("€", "").replace("£", "")
          .replace("¥", "").replace("%", "").replace("\u00a0", "").strip())
    s = s.replace("−", "-").replace("–", "-")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def decimals_of(raw):
    s = re.sub(r"[^\d.]", "", raw)
    return len(s.split(".")[1]) if "." in s else 0


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []      # list of tables; each a list of {"header": bool, "cells": [str]}
        self.notes = []       # visible text outside tables (units, rounding notes, titles)
        self._depth = 0
        self._rows = None
        self._cells = None
        self._text = None
        self._row_all_th = False
        self._row_saw_th = False
        self._in_thead = 0
        self._skip = 0          # inside <style>/<script>

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
            return
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        if tag == "thead" and self._depth == 1:
            self._in_thead += 1
        elif self._depth == 1:
            if tag == "tr":
                self._cells, self._row_all_th, self._row_saw_th = [], True, False
            elif tag in ("td", "th"):
                self._text = []
                if tag == "th":
                    self._row_saw_th = True
                else:
                    self._row_all_th = False

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skip:
            self._skip -= 1
            return
        if tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None
        elif tag == "thead" and self._in_thead:
            self._in_thead -= 1
        elif self._depth == 1:
            if tag in ("td", "th") and self._text is not None and self._cells is not None:
                self._cells.append(" ".join("".join(self._text).split()))
                self._text = None
            elif tag == "tr" and self._cells is not None:
                if any(self._cells):
                    is_header = self._in_thead > 0 or (self._row_all_th and self._row_saw_th)
                    self._rows.append({"header": is_header, "cells": self._cells})
                self._cells = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._text is not None:
            self._text.append(data)
        elif self._depth == 0:
            t = " ".join(data.split())
            if len(t) > 2:
                self.notes.append(t)


def extract_records(path):
    p = TableParser()
    with open(path, encoding="utf-8", errors="replace") as fh:
        p.feed(fh.read())
    records = []
    for ti, rows in enumerate(p.tables):
        headers = None
        for ri, row in enumerate(rows):
            cells = row["cells"]
            if row["header"]:
                headers = cells
                continue
            line = next((c for c in cells if LINE_RE.match(c)), None)
            texts = [c for c in cells if c != line and parse_number(c) is None and c.strip()]
            metric = max(texts, key=len) if texts else ""
            values = []
            for ci, c in enumerate(cells):
                if c == line or c in texts:
                    continue
                v = parse_number(c)
                if v is not None and NUM_RE.match(c.strip()):
                    hdr = headers[ci] if headers and ci < len(headers) else ""
                    values.append({"col": ci, "header": hdr, "raw": c, "num": v})
            if line is not None or values:
                records.append({"table": ti, "line": line, "metric": metric, "values": values})
    return records, p.notes


def cmd_parse(path, as_json=False):
    records, notes = extract_records(path)
    if as_json:
        print(json.dumps({"records": records, "notes": notes}, indent=1))
        return 0
    print("== NOTES / NON-TABLE TEXT (units, rounding hints) ==")
    for n in dict.fromkeys(notes):
        print("  " + n)
    print("== ROWS ==")
    for r in records:
        vals = "  ".join(
            "v{idx}{hdr}={raw}".format(idx=v["col"], hdr="[%s]" % v["header"] if v["header"] else "", raw=v["raw"])
            for v in r["values"])
        print("t{t}  line={line!s:6} metric={metric:35.35} {vals}".format(
            t=r["table"], line=r["line"], metric=r["metric"], vals=vals))
    return 0


def build_vals(records):
    vals = {}   # (line, col_index among its value cells) -> (num, decimals)
    for r in records:
        if r["line"] is None:
            continue
        for k, v in enumerate(r["values"]):
            key = (r["line"], k)
            if key in vals:
                print("WARNING: duplicate line label %r; keeping first" % r["line"])
                continue
            vals[key] = (v["num"], decimals_of(v["raw"]))
    return vals


def evaluate(records, rels, tol=None, dec=None):
    vals = build_vals(records)
    tok = re.compile(r"@([A-Za-z]?\d+)(?:#(\d+))?")
    results = []
    for rel in rels:
        if "=" not in rel:
            print("ERROR (no '=' in relation): %s" % rel)
            results.append((rel, None, set(), False))
            continue
        lhs_s, rhs_s = rel.split("=", 1)
        involved, dmin, err = set(), None, None

        def sub(m):
            nonlocal dmin, err
            lab, k = m.group(1), int(m.group(2) or 0)
            if (lab, k) not in vals:
                err = "unknown value @%s#%d" % (lab, k)
                return "0.0"
            num, d = vals[(lab, k)]
            involved.add(lab)
            dmin = d if dmin is None else min(dmin, d)
            return repr(num)

        try:
            lhs_e = tok.sub(sub, lhs_s)
            rhs_e = tok.sub(sub, rhs_s)
            if err:
                raise ValueError(err)
            env = {"round": round, "abs": abs, "min": min, "max": max, "__builtins__": {}}
            lhs, rhs = eval(lhs_e, env), eval(rhs_e, env)  # noqa: S307 - sandboxed env
        except Exception as e:  # report and continue
            print("ERROR %s  (%s)" % (rel, e))
            results.append((rel, None, involved, False))
            continue
        t = tol if tol is not None else 0.5 * 10 ** (-(dec if dec is not None else (dmin or 0))) + 1e-9
        res = lhs - rhs
        ok = abs(res) <= t
        results.append((rel, involved, involved, ok))
        print("%s %-55s lhs=%.6g rhs=%.6g residual=%+.6g tol=%.3g" %
              ("PASS" if ok else "FAIL", rel, lhs, rhs, res, t))

    failing = [(rel, inv) for rel, inv, _, ok in results if inv and not ok]
    print("== SUMMARY ==")
    print("%d/%d relations failed" % (len(failing), len(rels)))
    if failing:
        common = set.intersection(*[inv for _, inv in failing]) if all(failing) else set()
        print("line(s) involved in EVERY failing relation: %s" % (sorted(common) or "(none)"))
        score = {}
        for rel, inv, _, ok in results:
            for lab in inv or ():
                score.setdefault(lab, [0, 0])[0 if not ok else 1] += 1
        for lab, (f, p) in sorted(score.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
            if f:
                print("  line %-6s in %d FAIL / %d PASS relations" % (lab, f, p))
        print("Hint: with exactly one wrong value, the culprit is the line that is in all")
        print("failing relations and whose co-members pass their OTHER relations.")
    return 1 if failing else 0


def cmd_check(path, rels, tol=None, dec=None):
    records, _ = extract_records(path)
    return evaluate(records, rels, tol, dec)


TOTAL_RE = re.compile(r"\b(total|subtotal)\b", re.I)
DERIVED_RE = re.compile(r"\b(gross profit|operating (income|loss|profit)|ebitda|ebit|"
                        r"pre-?tax|income before tax|net (income|loss|earnings)|"
                        r"comprehensive income)\b", re.I)
REV_RE = re.compile(r"^(total\s+|net\s+)?(revenue|sales)\b", re.I)
COST_RE = re.compile(r"\b(cost of|cogs|cost of goods|cost of sales|cost of revenue)\b", re.I)
MARGIN_RE = re.compile(r"\bmargin\b", re.I)
GROWTH_RE = re.compile(r"\b(growth|yoy|y/y|qoq|q/q|change|increase|decrease)\b", re.I)


def infer_relations(records):
    """Infer standard financial relations from metric names / table structure.

    Returns list of (relation_string, how_inferred). Conservative on purpose:
    every emitted relation is printed so the agent can audit it, and ambiguous
    cases are simply skipped (left for explicit `check`).
    """
    rels = []
    by_table = {}
    for r in records:
        by_table.setdefault(r["table"], []).append(r)

    def lab(r):
        return r["line"]

    def ref(r, k=0):
        return "@%s%s" % (lab(r), "" if k == 0 else "#%d" % k)

    # 1) Structural subtotals: a *Total/Subtotal* row = sum of the item rows since
    #    the previous derived/total row (or table start), per value column.
    for rows in by_table.values():
        acc = []
        for r in rows:
            if not r["values"] or lab(r) is None:
                continue
            m = r["metric"]
            if TOTAL_RE.search(m):
                if len(acc) >= 2:
                    for k in range(len(r["values"])):
                        terms = [a for a in acc if len(a["values"]) > k]
                        if len(terms) >= 2:
                            rels.append(("%s = %s" % (ref(r, k), " + ".join(ref(a, k) for a in terms)),
                                         "subtotal '%s' = sum of rows above" % m))
                acc = []
            elif DERIVED_RE.search(m):
                acc = []
            else:
                acc.append(r)

    # 2) Name-matched income-statement identities (across all tables).
    def find(pat):
        rx = pat if hasattr(pat, "search") else re.compile(pat, re.I)
        return next((r for r in records if r["values"] and lab(r) and rx.search(r["metric"])), None)

    rev = find(REV_RE)
    gp = find(r"\bgross profit\b")
    cost = find(COST_RE)
    opex = find(r"\btotal operating (expenses|costs)\b")
    op = find(r"\boperating (income|loss|profit)\b|^\s*ebit\b")
    ni = find(r"\bnet (income|loss|earnings)\b")
    pretax = find(r"\b(pre-?tax|income before tax|income before income taxes)\b")
    tax = find(r"\b(income )?tax (expense|provision|benefit)\b|\bprovision for.*tax")
    other = find(r"\bother (income|expense)")
    if gp and rev and cost:
        rels.append(("%s = %s - %s" % (ref(gp), ref(rev), ref(cost)),
                     "gross profit = revenue - cost"))
    if op and gp and opex:
        rels.append(("%s = %s - %s" % (ref(op), ref(gp), ref(opex)),
                     "operating income = gross profit - total opex"))
    if ni and pretax and tax:
        rels.append(("%s = %s - %s" % (ref(ni), ref(pretax), ref(tax)),
                     "net income = pretax - tax"))
    elif ni and op and other:
        rels.append(("%s = %s + %s" % (ref(ni), ref(op), ref(other)),
                     "net income = operating income + other income"))

    # 3) Margins: "X margin" = name-matched profit / revenue * 100, rounded to the
    #    decimals shown in the margin cell.
    if rev:
        for r in records:
            if not r["values"] or lab(r) is None or not MARGIN_RE.search(r["metric"]):
                continue
            low = r["metric"].lower()
            num = gp if "gross" in low else op if "operating" in low else ni if "net" in low else None
            d = decimals_of(r["values"][0]["raw"])
            if num:
                rels.append(("%s = round(%s / %s * 100, %d)" % (ref(r), ref(num), ref(rev), d),
                             "margin '%s' = profit / revenue" % r["metric"]))
            elif "gross" in low and cost:
                rels.append(("%s = round((%s - %s) / %s * 100, %d)" % (ref(r), ref(rev), ref(cost), ref(rev), d),
                             "margin '%s' = (revenue - cost) / revenue" % r["metric"]))

    # 4) Growth / YoY / change rows: (current - prior) / prior * 100 against the
    #    same-table row with the strongest name overlap. TENTATIVE - audit by eye.
    stop = {"growth", "yoy", "y/y", "qoq", "q/q", "change", "increase", "decrease", "%", "rate"}
    for rows in by_table.values():
        for r in rows:
            if (not lab(r) or not r["values"] or not GROWTH_RE.search(r["metric"])):
                continue
            words = set(re.findall(r"[a-z]+", r["metric"].lower())) - stop
            best, best_ov = None, 0
            for cand in rows:
                if cand is r or len(cand["values"]) < 2 or not lab(cand):
                    continue
                ov = len(words & set(re.findall(r"[a-z]+", cand["metric"].lower())))
                if ov > best_ov:
                    best, best_ov = cand, ov
            if best:
                d = decimals_of(r["values"][0]["raw"])
                rels.append(("%s = round((%s - %s) / %s * 100, %d)" %
                             (ref(r), ref(best, 0), ref(best, 1), ref(best, 1), d),
                             "TENTATIVE growth '%s' vs '%s'" % (r["metric"], best["metric"])))
    return rels


def cmd_auto(path, tol=None, dec=None):
    records, _ = extract_records(path)
    rels = infer_relations(records)
    if not rels:
        print("auto: no standard relations inferred from metric names/structure.")
        print("Enumerate relations explicitly per SKILL.md Step 3 and use `check`.")
        return 2
    print("== INFERRED RELATIONS (audit each before trusting) ==")
    for rel, why in rels:
        print("  %-58s  <- %s" % (rel, why))
    print()
    rc = evaluate(records, [rel for rel, _ in rels], tol, dec)
    print()
    print("auto is a first pass only: if 0 relations failed, the error lives in a")
    print("relation auto does not infer (per-share, unit conversion, cross-table);")
    print("if several lines tie, add explicit `check` relations until the vote is unique.")
    return rc


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    mode, path = argv[1], argv[2]
    if mode == "parse":
        return cmd_parse(path, "--json" in argv[3:])
    if mode in ("check", "auto"):
        tol, dec, rels = None, None, []
        it = iter(argv[3:])
        for a in it:
            if a == "--tol":
                tol = float(next(it))
            elif a == "--decimals":
                dec = int(next(it))
            else:
                rels.append(a)
        if mode == "auto":
            return cmd_auto(path, tol, dec)
        return cmd_check(path, rels, tol, dec)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
