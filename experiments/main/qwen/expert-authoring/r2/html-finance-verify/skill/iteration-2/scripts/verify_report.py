#!/usr/bin/env python3
"""
HTML financial report verifier -- stdlib only.
Usage: python3 verify.py <html_file> <output_file>

Skill resource: read with `read` tool, write to /tmp/verify.py, then execute.
Not directly runnable from task_shell.
"""
import sys, re, os
from html.parser import HTMLParser
from collections import OrderedDict, Counter

# -- HTML table extraction -------------------------------------------------
class TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._t = None; self._r = None; self._c = None; self._cl = None
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table": self._t = []
        elif t == "tr" and self._t is not None: self._r = []
        elif t in ("td","th") and self._r is not None:
            self._c = ""; self._cl = self.getpos()[0]
    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td","th") and self._c is not None:
            self._r.append((self._c.strip(), self._cl)); self._c = None
        elif t == "tr" and self._r is not None:
            if self._t is not None: self._t.append(self._r)
            self._r = None
        elif t == "table" and self._t is not None:
            self.tables.append(self._t); self._t = None
    def handle_data(self, data):
        if self._c is not None: self._c += data

def load_tables(path):
    with open(path, "r", encoding="utf-8") as f: html = f.read()
    p = TableExtractor(); p.feed(html); return p.tables

# -- Value parsers ---------------------------------------------------------
def parse_dollar(s):
    s = s.strip().replace(",","").replace(" ","").replace("\xa0","")
    m = re.match(r"^-?\$?\(?([\d.]+)\)?$", s)
    if not m: return None
    v = float(m.group(1))
    if "(" in s or s.startswith("-"): v = -v
    return v

def parse_pct(s):
    s = s.strip().replace(" ","").replace("\xa0","")
    m = re.match(r"^(-?[\d.]+)\s*%?$", s)
    return float(m.group(1)) if m else None

def parse_int(s):
    s = s.strip()
    return int(s) if re.match(r"^\d+$", s) else None

# -- Metric extraction -----------------------------------------------------
def extract_metrics(tables):
    metrics = OrderedDict()
    for tbl in tables:
        for row in tbl:
            if len(row) < 2: continue
            texts = [c[0] for c in row]
            line_no = ln_idx = None
            for i, txt in enumerate(texts):
                n = parse_int(txt)
                if n is not None and 10 <= n <= 99999:
                    line_no = n; ln_idx = i; break
            if line_no is None: continue
            rest = [(t,l) for j,(t,l) in enumerate(row) if j != ln_idx]
            if not rest: continue
            name = rest[0][0] if len(rest) >= 2 else ""
            raw  = rest[-1][0]
            d = parse_dollar(raw); p = parse_pct(raw)
            if d is not None or p is not None:
                metrics[line_no] = dict(name=name.strip(), dollar=d, percent=p, raw=raw.strip())
    return metrics

# -- Lookup helpers --------------------------------------------------------
def build_lk(metrics):
    d = {}
    for ln, m in metrics.items(): d[m["name"].lower()] = (ln, m)
    return d

def fd(lk, pats):
    for pat in pats:
        for k,(ln,m) in lk.items():
            if pat in k and m["dollar"] is not None: return ln, m["dollar"]
    return None, None

def fp(lk, pats):
    for pat in pats:
        for k,(ln,m) in lk.items():
            if pat in k and m["percent"] is not None: return ln, m["percent"]
    return None, None

def _is_component(key):
    k = key
    kws = ["research","development","r&d","rd","sales","marketing","s&m",
           "selling","general","administrative","admin","sg&a","sga","g&a",
           "depreciation","amortization","d&a","dep","amort",
           "compensation","rent","utilities","other operating"]
    for kw in kws:
        if kw in k or k in kw: return True
    return False

# -- Relationship checks ---------------------------------------------------
DT = 0.15; PT = 0.15

def run_checks(metrics):
    """Return list of check result dicts: inv, bad, ok, desc."""
    lk = build_lk(metrics); results = []
    def R(inv, bad, ok, desc):
        results.append(dict(inv=inv, bad=bad, ok=ok, desc=desc))

    ln_rev, rev = fd(lk, ["revenue","total revenue","net revenue","sales","net sales"])
    ln_cogs, cogs = fd(lk, ["cost of revenue","cost of goods","cogs","cost of sales"])
    ln_gp, gp = fd(lk, ["gross profit","gross income"])
    ln_opex, opex = fd(lk, ["total operating expenses","operating expenses","total opex","total operating expense"])
    ln_oi, oi = fd(lk, ["operating income","operating profit"])
    if ln_oi is None: ln_oi, oi = fd(lk, ["ebit"])
    ln_oth, oth = fd(lk, ["other income","other expense","interest income","interest expense","non-operating"])
    ln_ni, ni = fd(lk, ["net income","net earnings","net profit"])
    ln_tax, tax = fd(lk, ["income tax","tax expense","tax provision"])
    ln_pt, pt = fd(lk, ["income before tax","pretax","pre-tax"])

    # 1) Rev - COGS = GP
    if None not in (rev, cogs, gp):
        e = rev - cogs
        R({ln_rev,ln_cogs,ln_gp}, ln_gp, abs(e-gp)<=DT,
          "GP: Rev({})-COGS({})={}, got {}".format(rev,cogs,e,gp))

    # 2) Component OpEx sum = Total OpEx
    excl = {"total operating expenses","operating expenses","total opex","total operating expense"}
    comps = [(ln,m["dollar"]) for k,(ln,m) in lk.items()
             if m["dollar"] is not None and k not in excl and _is_component(k)]
    if comps and opex is not None:
        s = sum(v for _,v in comps)
        comp_lns = {ln for ln,_ in comps}
        R(comp_lns|{ln_opex}, ln_opex, abs(s-opex)<=DT,
          "OpEx: sum({})vs{}".format(s,opex))

    # 3) GP - OpEx = OI
    if None not in (gp, opex, oi):
        e = gp - opex
        R({ln_gp,ln_opex,ln_oi}, ln_oi, abs(e-oi)<=DT,
          "OI: GP({})-OpEx({})={}, got {}".format(gp,opex,e,oi))

    # 4) OI + Other (- Tax) = NI
    if None not in (oi, oth, ni):
        if pt is not None and tax is not None:
            ept = oi + oth
            R({ln_oi,ln_oth,ln_pt}, ln_pt, abs(ept-pt)<=DT,
              "Pretax: OI({})+Other({})={}, got {}".format(oi,oth,ept,pt))
            eni = pt - tax
            R({ln_pt,ln_tax,ln_ni}, ln_ni, abs(eni-ni)<=DT,
              "NI: Pretax({})-Tax({})={}, got {}".format(pt,tax,eni,ni))
        else:
            e = oi + oth
            R({ln_oi,ln_oth,ln_ni}, ln_ni, abs(e-ni)<=DT,
              "NI: OI({})+Other({})={}, got {}".format(oi,oth,e,ni))

    # -- Percentage KPIs (all relative to Revenue) --
    # Include upstream dollar-line deps in inv so cascading errors
    # are properly captured in the intersection logic.
    if rev and rev > 0:
        ln_gm, gm = fp(lk, ["gross margin"])
        if ln_gm is not None and gp is not None:
            e = round(gp/rev*100, 1)
            R({ln_gm,ln_gp,ln_rev}-{None}, ln_gm, abs(e-gm)<=PT,
              "Gross margin: {}/{}*100={}%, got {}%".format(gp,rev,e,gm))

        ln_om, om = fp(lk, ["operating margin","oper margin","op margin"])
        if ln_om is not None and oi is not None:
            e = round(oi/rev*100, 1)
            R({ln_om,ln_oi,ln_rev}-{None}, ln_om, abs(e-om)<=PT,
              "Op margin: {}/{}*100={}%, got {}%".format(oi,rev,e,om))

        ln_nm, nm = fp(lk, ["net margin","net profit margin"])
        if ln_nm is not None and ni is not None:
            e = round(ni/rev*100, 1)
            R({ln_nm,ln_ni,ln_rev}-{None}, ln_nm, abs(e-nm)<=PT,
              "Net margin: {}/{}*100={}%, got {}%".format(ni,rev,e,nm))

        ln_ebm, ebm = fp(lk, ["ebitda margin"])
        if ln_ebm is not None:
            ln_ebitda, ebitda = fd(lk, ["ebitda","adjusted ebitda"])
            if ebitda is not None:
                e = round(ebitda/rev*100, 1)
                R({ln_ebm,ln_ebitda,ln_rev}-{None}, ln_ebm, abs(e-ebm)<=PT,
                  "EBITDA margin: {}/{}*100={}%, got {}%".format(ebitda,rev,e,ebm))

        # Other "X margin" percentages
        skip = {"gross margin","operating margin","oper margin","op margin",
                "net margin","net profit margin","ebitda margin"}
        for k,(ln,m) in lk.items():
            if m["percent"] is not None and "margin" in k and k not in skip:
                dn = k.replace("margin","").strip()
                ln_d, dv = fd(lk, [dn] if dn else [])
                if dv is not None:
                    e = round(dv/rev*100, 1)
                    inv = ({ln, ln_d, ln_rev} if ln_d else {ln, ln_rev}) - {None}
                    R(inv, ln, abs(e-m["percent"])<=PT,
                      "{}: {}% vs {}%".format(m["name"],e,m["percent"]))

    # EPS
    ln_eps, eps = fd(lk, ["earnings per share","diluted eps","basic eps","eps"])
    ln_sh, sh = fd(lk, ["shares","share count","weighted average shares",
                         "diluted shares","shares outstanding"])
    if eps is not None and sh is not None and ni is not None and sh > 0:
        e = round(ni/sh, 2)
        R({ln_eps,ln_ni,ln_sh}-{None}, ln_eps, abs(e-eps)<=0.05,
          "EPS: NI({})/Shares({})={}, got {}".format(ni,sh,e,eps))

    # YoY / growth rates
    for k,(ln,m) in lk.items():
        if m["percent"] is not None and any(w in k for w in
                ["growth","yoy","year-over-year","change"]):
            base = k
            for sfx in [" growth"," yoy"," year-over-year"," change"]:
                base = base.replace(sfx,"")
            base = base.strip()
            ln_cur, cur = fd(lk, [base] if base else [])
            ln_prev, prev = fd(lk, ["prior "+base,"previous "+base,
                              base+" prior",base+" previous","last year"])
            if cur is not None and prev is not None and prev > 0:
                e = round((cur-prev)/prev*100, 1)
                inv = {ln, ln_cur, ln_prev} - {None}
                R(inv, ln, abs(e-m["percent"])<=PT,
                  "{}: {}% vs {}%".format(m["name"],e,m["percent"]))

    return results

# -- Isolate the single error ----------------------------------------------
def isolate(metrics, results):
    """
    Exactly one metric is wrong. Use all check results to identify it.

    1. Single failure -> return its bad_line.
    2. Multiple failures -> the wrong line appears in ALL failures'
       involved sets. Use intersection.
    3. If intersection is empty/ambiguous, prefer the candidate with
       FEWEST passing-check participations (least evidence of being
       correct). This handles cascading errors where a wrong upstream
       value makes downstream checks pass vacuously.
    """
    fails = [r for r in results if not r["ok"]]
    passes = [r for r in results if r["ok"]]
    if not fails: return None
    if len(fails) == 1: return fails[0]["bad"]

    # Count passing-check participation per line
    pass_cnt = Counter()
    for r in passes:
        for ln in r["inv"]: pass_cnt[ln] += 1

    # Collect all candidate lines from failing checks
    candidates = set()
    for r in fails: candidates |= r["inv"]

    # Intersection: lines appearing in ALL failures
    fail_cnt = Counter()
    for r in fails:
        for ln in r["inv"]: fail_cnt[ln] += 1
    total = len(fails)
    universal = [ln for ln, c in fail_cnt.items() if c == total]

    if len(universal) == 1:
        return universal[0]
    if universal:
        # Among universal candidates, pick the one with fewest passing
        # participations (least independent evidence of correctness)
        return min(universal, key=lambda ln: pass_cnt.get(ln, 0))

    # No universal candidate: pick line with fewest passing participations
    # among all failure-involved lines
    return min(candidates, key=lambda ln: (pass_cnt.get(ln, 0), -fail_cnt[ln]))

# -- Format answer ---------------------------------------------------------
def fmt(metrics, ln):
    m = metrics[ln]
    v = str(m["percent"]) if m["percent"] is not None else str(m["dollar"])
    if "." in v:
        v = v.rstrip("0").rstrip(".")
        if "." not in v: v += ".0"
    return "{},{}".format(ln, v)

# -- Main ------------------------------------------------------------------
def main():
    hf = sys.argv[1] if len(sys.argv) > 1 else "/app/q2_earnings_report.html"
    of = sys.argv[2] if len(sys.argv) > 2 else "/app/value.txt"
    if not os.path.exists(hf):
        htmls = [f for f in os.listdir("/app") if f.endswith(".html")]
        if htmls: hf = "/app/" + htmls[0]

    tables = load_tables(hf)
    metrics = extract_metrics(tables)
    print("Extracted {} metrics:".format(len(metrics)))
    for ln, m in metrics.items():
        v = "${}".format(m["dollar"]) if m["dollar"] is not None else "{}%".format(m["percent"])
        print("  Line {}: {} = {}  (raw: {})".format(ln, m["name"], v, m["raw"]))

    results = run_checks(metrics)
    fails = [r for r in results if not r["ok"]]
    passes = [r for r in results if r["ok"]]

    print("\n{} checks: {} passed, {} failed".format(
        len(results), len(passes), len(fails)))
    for r in results:
        tag = "PASS" if r["ok"] else "FAIL"
        print("  [{}] Line {}: {} (inv: {})".format(
            tag, r["bad"], r["desc"], sorted(r["inv"])))

    if not fails:
        print("\nAll checks passed - no error found!"); sys.exit(1)

    bad = isolate(metrics, results)
    ans = fmt(metrics, bad)
    print("\n>>> Answer: {}".format(ans))
    with open(of, "w") as f: f.write(ans + "\n")
    print("Written to {}".format(of))

if __name__ == "__main__": main()
