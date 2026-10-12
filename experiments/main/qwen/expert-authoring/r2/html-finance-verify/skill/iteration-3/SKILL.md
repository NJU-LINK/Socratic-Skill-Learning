---
name: html-finance-verify
description: >
  Verify an HTML financial earnings report by extracting line-numbered metrics,
  checking all internal arithmetic and ratio relationships, and identifying the
  single incorrect metric. Writes the result as line_number,value to the
  specified output file.
---

# HTML Financial Report Verification

## Task Summary

An HTML earnings report at `/app/*.html` contains line-numbered financial
metrics (dollar amounts and percentage KPIs). Exactly **one** metric is
arithmetically wrong. Find it and write `line_number,value` to the output file.

## Critical Tool Rules

| Tool | Can access | Cannot access |
|------|-----------|---------------|
| `read` | `task.yaml`, skill resources (`scripts/*`) | `/app/*` paths (WORKSPACE_BOUNDARY error) |
| `task_shell` | `/app/*` files, `/tmp/*` | Skill resources on host filesystem |

**Therefore**: use `task_shell` to read the HTML report and to run scripts.
Use `read` only for `task.yaml` and skill resource files.

## Execution Plan (3 steps)

### Step 1: Read task.yaml and the HTML report

```bash
# Read task config (use read tool for task.yaml)
# Then read HTML via task_shell:
cat /app/<report>.html
```

### Step 2: Write and run the inline verifier

Write this compact Python script directly into `task_shell` using a heredoc.
**Do NOT copy from `scripts/verify_report.py`** — that file is ~300 lines and
copying it wastes ~4500 output tokens. Use this ~80-line inline version instead:

```bash
python3 << 'EOF'
import re, os, glob
from collections import Counter

# Find HTML file
htmls = glob.glob("/app/*.html")
hf = htmls[0] if htmls else "/app/q2_earnings_report.html"
with open(hf) as f: html = f.read()

# Extract table rows: <td>LINE</td><td>NAME</td><td>VALUE</td>
rows = re.findall(
    r'<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
    html, re.DOTALL)

metrics = {}
for line_s, name_raw, val_raw in rows:
    ln = int(line_s)
    name = re.sub(r'<[^>]+>', '', name_raw).strip()
    raw = re.sub(r'<[^>]+>', '', val_raw).strip().replace(',','').replace('\xa0','')
    d = None; p = None
    dm = re.match(r'^-?\$?\(?([\d.]+)\)?$', raw)
    if dm:
        d = float(dm.group(1))
        if '(' in raw or raw.startswith('-'): d = -d
    pm = re.match(r'^(-?[\d.]+)\s*%?$', raw)
    if pm: p = float(pm.group(1))
    if d is not None or p is not None:
        metrics[ln] = (name, d, p, raw)

print(f"Extracted {len(metrics)} metrics:")
for ln in sorted(metrics):
    nm,d,p,_ = metrics[ln]
    print(f"  {ln}: {nm} = {'${}'.format(d) if d is not None else '{}%'.format(p)}")

# Name-indexed lookup
by_name = {}
for ln,(nm,d,p,raw) in metrics.items():
    by_name[nm.lower()] = (ln, d, p)

def fd(*pats):
    for pat in pats:
        for k,(ln,d,p) in by_name.items():
            if pat in k and d is not None: return ln, d
    return None, None

def fp(*pats):
    for pat in pats:
        for k,(ln,d,p) in by_name.items():
            if pat in k and p is not None: return ln, p
    return None, None

def is_opex_comp(key):
    kws = ["research","development","r&d","sales","marketing","s&m","general",
           "administrative","admin","sg&a","sga","depreciation","amortization","d&a"]
    excl = {"total operating expenses","operating expenses","total opex"}
    if key in excl: return False
    return any(kw in key or key in kw for kw in kws)

# Gather values
ln_rev, rev = fd("revenue","sales","net revenue")
ln_cogs, cogs = fd("cost of revenue","cost of goods","cogs")
ln_gp, gp = fd("gross profit","gross income")
ln_opex, opex = fd("total operating exp","operating exp","total opex")
ln_oi, oi = fd("operating income","operating profit")
if ln_oi is None: ln_oi, oi = fd("ebit")
ln_oth, oth = fd("other income","other exp","interest income","interest exp")
ln_ni, ni = fd("net income","net earnings","net profit")
ln_tax, tax = fd("income tax","tax exp")
ln_pt, pt = fd("income before tax","pretax","pre-tax")

TOL = 0.15; fails = []
def chk(ok, inv, bad, desc):
    if not ok: fails.append((set(inv), bad, desc))

# Dollar checks
if None not in (rev, cogs, gp):
    chk(abs(rev-cogs-gp)<=TOL, [ln_rev,ln_cogs,ln_gp], ln_gp,
        f"GP:{rev}-{cogs}={rev-cogs},got{gp}")
comps = [(ln,d) for k,(ln,d,p) in by_name.items() if d is not None and is_opex_comp(k)]
if comps and opex is not None:
    s = sum(d for _,d in comps)
    chk(abs(s-opex)<=TOL, [ln for ln,_ in comps]+[ln_opex], ln_opex,
        f"OpEx:{s},got{opex}")
if None not in (gp, opex, oi):
    chk(abs(gp-opex-oi)<=TOL, [ln_gp,ln_opex,ln_oi], ln_oi,
        f"OI:{gp}-{opex}={gp-opex},got{oi}")
if None not in (oi, oth, ni):
    if pt is not None and tax is not None:
        chk(abs(oi+oth-pt)<=TOL, [ln_oi,ln_oth,ln_pt], ln_pt,
            f"Pretax:{oi}+{oth}={oi+oth},got{pt}")
        chk(abs(pt-tax-ni)<=TOL, [ln_pt,ln_tax,ln_ni], ln_ni,
            f"NI:{pt}-{tax}={pt-tax},got{ni}")
    else:
        chk(abs(oi+oth-ni)<=TOL, [ln_oi,ln_oth,ln_ni], ln_ni,
            f"NI:{oi}+{oth}={oi+oth},got{ni}")

# Percentage checks (all / Revenue)
if rev and rev > 0:
    ln_gm, gm = fp("gross margin")
    if ln_gm is not None and gp is not None:
        chk(abs(round(gp/rev*100,1)-gm)<=TOL, [ln_gm,ln_gp,ln_rev], ln_gm,
            f"GM:{gp}/{rev}*100={round(gp/rev*100,1)}%,got{gm}%")
    ln_om, om = fp("operating margin","oper margin","op margin")
    if ln_om is not None and oi is not None:
        chk(abs(round(oi/rev*100,1)-om)<=TOL, [ln_om,ln_oi,ln_rev], ln_om,
            f"OM:{oi}/{rev}*100={round(oi/rev*100,1)}%,got{om}%")
    ln_nm, nm = fp("net margin","net profit margin")
    if ln_nm is not None and ni is not None:
        chk(abs(round(ni/rev*100,1)-nm)<=TOL, [ln_nm,ln_ni,ln_rev], ln_nm,
            f"NM:{ni}/{rev}*100={round(ni/rev*100,1)}%,got{nm}%")
    ln_ebm, ebm = fp("ebitda margin")
    if ln_ebm is not None:
        _, ebitda = fd("ebitda","adjusted ebitda")
        if ebitda is not None:
            chk(abs(round(ebitda/rev*100,1)-ebm)<=TOL, [ln_ebm], ln_ebm,
                f"EBITDA:{ebitda}/{rev}*100={round(ebitda/rev*100,1)}%,got{ebm}%")
    skip = {"gross margin","operating margin","oper margin","op margin",
            "net margin","net profit margin","ebitda margin"}
    for k,(ln,d,p) in by_name.items():
        if p is not None and "margin" in k and k not in skip:
            dn = k.replace("margin","").strip()
            _,dv = fd(dn) if dn else (None,None)
            if dv is not None:
                chk(abs(round(dv/rev*100,1)-p)<=TOL, [ln], ln,
                    f"{k}:{dv}/{rev}*100={round(dv/rev*100,1)}%,got{p}%")

# EPS
ln_eps, eps = fd("earnings per share","diluted eps","basic eps","eps")
ln_sh, sh = fd("shares","share count","weighted average","diluted shares")
if eps is not None and sh is not None and ni is not None and sh > 0:
    chk(abs(round(ni/sh,2)-eps)<=0.05, [ln_eps], ln_eps,
        f"EPS:{ni}/{sh}={round(ni/sh,2)},got{eps}")

# Report failures
print(f"\n{len(fails)} failure(s):")
for inv, bad, desc in fails:
    print(f"  Line {bad}: {desc}  (inv: {sorted(inv)})")

if not fails: print("No errors found!"); exit(1)

# Isolate: single failure -> direct; multiple -> intersection
if len(fails) == 1:
    bad_ln = fails[0][1]
else:
    common = fails[0][0]
    for inv,_,_ in fails[1:]: common = common & inv
    if len(common) == 1: bad_ln = common.pop()
    else:
        # Fewest passing-check participations
        fail_lines = set()
        for _,bad,_ in fails: fail_lines.add(bad)
        pass_cnt = Counter()
        all_inv = set()
        for inv,_,_ in fails: all_inv |= inv
        # Lines NOT in any failure are evidence of correctness
        for ln in metrics:
            if ln not in all_inv: pass_cnt[ln] += 1
        bad_ln = min(all_inv, key=lambda ln: (pass_cnt.get(ln,0),
                     -sum(1 for _,b,_ in fails if b==ln)))

m = metrics[bad_ln]
v = str(m[2]) if m[2] is not None else str(m[1])
if '.' in v:
    v = v.rstrip('0').rstrip('.')
    if '.' not in v: v += '.0'
ans = f"{bad_ln},{v}"
print(f"\n>>> Answer: {ans}")
with open("/app/value.txt", "w") as f: f.write(ans + "\n")
print(f"Written to /app/value.txt")
EOF
```

### Step 3: Verify the output

```bash
cat /app/value.txt
```

## Verification Relationships

| # | Check | Formula | Tolerance |
|---|-------|---------|-----------|
| 1 | Gross Profit | Revenue − COGS | ±0.15 |
| 2 | Total OpEx | Σ components (R&D, S&M, G&A, D&A…) | ±0.15 |
| 3 | Operating Income | Gross Profit − Total OpEx | ±0.15 |
| 4 | Net Income | OI + Other Income (− Tax) | ±0.15 |
| 5 | Gross margin | GP / Rev × 100 | ±0.15 pp |
| 6 | Operating margin | OI / Rev × 100 | ±0.15 pp |
| 7 | Net margin | NI / Rev × 100 | ±0.15 pp |
| 8 | EBITDA margin | EBITDA / Rev × 100 | ±0.15 pp |
| 9 | Other margins | X_dollar / Rev × 100 | ±0.15 pp |
| 10 | EPS | NI / Shares | ±0.05 |

## Error Isolation Logic

1. **One failure** → its line number is the answer.
2. **Multiple failures** → take the **intersection** of all involved-line
   sets. The wrong line appears in every failure's dependencies.
3. **Tie-break** → prefer the line with fewest independent passing checks.

## Output Format Rules

Read task.yaml for variant-specific details. General rules:

- **line_number**: the integer in the report's "Line" column (NOT HTML source line).
- **value**: the incorrect value as displayed:
  - Percentages → numeric only, **no `%` sign**
  - Dollars → numeric only, **no `$` sign**
  - Preserve shown precision; keep ≥1 decimal (e.g. `251.0`)
- **Target file**: default `/app/value.txt`; task.yaml may differ.

## Self-Verification Checklist

1. ✅ All dollar cross-checks tested (Rev−COGS=GP, GP−OpEx=OI, OI+Other=NI).
2. ✅ All displayed percentages recomputed from dollar values.
3. ✅ Exactly **one** discrepancy found.
4. ✅ Output value matches the report's display (raw, not corrected).
5. ✅ Output file exists at correct path with one `line_number,value` line.

## Fallback: Full Script for Complex Variants

For reports with YoY growth rates, complex multi-table layouts, or unusual
metric names, read `scripts/verify_report.py` with the `read` tool and write
it to `/tmp/verify.py` via heredoc, then execute:

```bash
python3 /tmp/verify.py /app/<report>.html /app/value.txt
```

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Parenthetical negatives `$(12.3)` | Parsed as −12.3 |
| Thousands separators `$1,234.5` | Commas stripped |
| Non-standard HTML filename | `glob.glob("/app/*.html")` auto-detects |
| Missing metrics | Skipped — only available checks run |
| Header rows | Skipped (no numeric line number) |
| Multiple tables/sections | Regex finds all matching rows |
| Dollar amount errors | Caught by cross-checks; downstream may pass vacuously |
| Component keyword matching | Bidirectional (e.g. "admin" ↔ "administrative") |
