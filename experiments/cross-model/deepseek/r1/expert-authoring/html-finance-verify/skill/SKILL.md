---
name: html-finance-verify
description: >
  Audit an HTML financial report with line-numbered metrics, re-derive every
  displayed value from internal cross-checks (sums, subtotals, margins, growth
  rates, per-share figures, unit conversions), isolate the single internally
  inconsistent metric, and write the required `line,value` answer file. The
  wrong value is always discoverable from the document itself, never from
  external knowledge.
---

# HTML Financial Verification

## Environment map (read first)

- Host `read`/`ls` tools can read `task.yaml` (relative path) and the skill
  package files; they **cannot** open `/app` (`WORKSPACE_BOUNDARY`).
- `task_shell` is the only gateway to `/app` (cwd is `/app`): use it to list/
  cat the report, run analysis, and write the answer file.
- The task container does not mount the host workspace: skill files are not
  runnable by their host path inside `task_shell`. Code goes in via heredoc.

## Family contract

One or more HTML financial reports; exactly **one displayed metric** contradicts
the rest of the document, locatable purely from internal consistency.

**Invariants:** every metric is a row with a displayed line number; the answer
file path and format come from the instruction and are graded deterministically;
the reported `value` is the **wrong value as displayed**, never the corrected
one. (v01's wrong value happened to be a digit transposition of the correct
value — report it verbatim, but do not assume variants are transpositions.)

**Expected to vary** (spec.yaml axes): table structure/section names/column
multiplicity, metric families, which relationship exposes the error and whether
it sits in a dollar amount or a percentage, line numbering density, output
path/format/precision (%, negatives, thousands separators, decimal commas).

## Procedure

### 1. Read the instruction, locate the report

From `task.yaml`: HTML path(s), answer file path/format, example output, and any
hint about the wrong metric class ("only one displayed KPI percentage" in v01).
Hints are load-bearing: verify the trusted classes fully first. In `task_shell`:
`ls /app` (and `find /app -name '*.html'` if no path is given); skim the report
for table count, unit note ("dollars in millions"), rounding note.

### 2. Fast path: run the reconciliation snippet — paste it verbatim

Paste the entire block below into `task_shell`; only change the `PATH` line to
the report path from the instruction (absolute works; the default runs from
`/app`). **Copy it as-is — do not rewrite a custom mini-script.** Evaluation
logs show that agents who write their own script hardcode the seed's metric
names (Revenue / Gross profit / Gross margin), which crashes or silently misses
other error types (growth, per-share, subtotals, renamed sections) on variants;
verbatim pasting is also fewer tokens than a reimplementation.

What the snippet does and prints:

- `ROWS` — every line-numbered row from all tables, with label and value(s).
  Every displayed metric must appear here with its line; multi-column rows show
  all cells (`a | b`).
- `ADD` — each Total/Subtotal must equal some contiguous run of neighboring
  leaf rows (or previous total + leaves). `FAIL` implicates the total row
  (weight 2) and its component leaves (weight 1 each).
- `CHAIN` — a profit/income/loss-labeled, non-percent row must equal `a±b` of
  two rows above it; only scheduled when such a pairing is plausibly close.
  `FAIL` implicates the row itself (weight 2) and its two operand rows (1 each).
- `RATIO` — a margin-style percentage must equal `component ÷ revenue × 100`
  at half-of-last-displayed-decimal tolerance. `FAIL` implicates the percent
  line (2) plus its numerator/denominator rows (1 each).
- `HINT`/`SKIP` — growth, per-share, unit-conversion rows are not automated;
  finish them by hand (step 3).
- `RESULT`/`line scores`/`ANSWER` — lines are scored by summing those weights
  over all failed identities; the unique top-scoring line is the answer, with
  the displayed (wrong) value normalized.

```bash
python3 - <<'EOF'
import re
from decimal import Decimal, ROUND_HALF_UP

PATH = 'q2_earnings_report.html'   # report path from the instruction

def text(c):
    t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c)).strip()
    for a, b in (('&nbsp;', ' '), ('&minus;', '-'), ('&#8211;', '-'), ('&ndash;', '-')):
        t = t.replace(a, b)
    return t

def val(c):
    t = c.strip()
    neg = t.startswith('(') and t.endswith(')')
    if neg:
        t = t[1:-1].strip()
    for s in '$€£¥%':
        t = t.replace(s, '')
    for s in '−–—':
        t = t.replace(s, '-')
    t = re.sub(r'[\u00a0\u202f ]', '', t)
    if re.search(r'[a-zA-Z]', t) or t in ('', '-'):
        return None
    m = re.fullmatch(r'(-?)(\d{1,3}(?:\.\d{3})+|\d+),(\d{1,2})', t)
    if m:
        t = m.group(1) + m.group(2).replace('.', '') + '.' + m.group(3)
    else:
        t = t.replace(',', '')
    try:
        return -Decimal(t) if neg else Decimal(t)
    except Exception:
        return None

def decd(v):
    e = v.as_tuple().exponent
    return 0 if e >= 0 else -e

def tol(*vs):
    d = max((decd(v) for v in vs if v is not None), default=0)
    return Decimal('0.5') * (Decimal(10) ** -d) + Decimal('1e-9')

html = open(PATH, encoding='utf-8').read()
secs, cur = [], 'document'
for ev in re.findall(r'<h[1-6]\b.*?</h[1-6]>|<table\b.*?</table>', html, re.S):
    if ev.lower().startswith('<table'):
        rows = []
        for tr in re.findall(r'<tr\b.*?</tr>', ev, re.S):
            cells = [c for c in (text(x) for x in re.findall(r'<t[dh]\b.*?</t[dh]>', tr, re.S)) if c]
            idx = next((i for i, x in enumerate(cells) if re.fullmatch(r'\d+', x)), None)
            if idx is None:
                continue
            vals = [x for x in cells[idx + 1:] if val(x) is not None]
            if not vals:
                continue
            label = next((x for x in cells if x != cells[idx] and val(x) is None), '')
            rows.append(dict(line=int(cells[idx]), label=label, raw=vals[-1], raws=vals, v=val(vals[-1])))
        if rows:
            secs.append((cur, rows))
    else:
        cur = text(ev)

allrows = [r for _, rs in secs for r in rs]
print('ROWS:')
for r in allrows:
    print('  line %-5s %-30s %-14s -> %s' % (r['line'], r['label'][:30], ' | '.join(r['raws']), r['v']))

fails = []
derived = re.compile(r'\b(profit|income|loss|earnings|ebitda|ebit)\b', re.I)
totre = re.compile(r'(^|\W)(total|subtotal)(\W|$)', re.I)
print('CHECKS:')
for title, rs in secs:
    pending, last_total = [], None
    for k, r in enumerate(rs):
        if r['v'] is not None and totre.search(r['label']):
            vals = [p['v'] for p in pending if p['v'] is not None]
            if vals or last_total is not None:
                cands = [sum(vals[i:j + 1], Decimal(0)) for i in range(len(vals)) for j in range(i, len(vals))]
                if last_total is not None:
                    cands.append(last_total + sum(vals, Decimal(0)))
                best = min((abs(c - r['v']) for c in cands), default=None)
                ok = best is not None and best <= tol(*(vals + [r['v'], last_total]))
                print('  ADD   line %-5s %-26s %s -> %s' % (r['line'], r['label'][:26], r['v'], 'OK' if ok else 'FAIL'))
                if not ok:
                    fails.append(('ADD', [(r['line'], 2)] + [(p['line'], 1) for p in pending]))
            last_total, pending = r['v'], []
        elif r['v'] is not None and derived.search(r['label']) and '%' not in r['raw']:
            prev = [p for p in rs[:k] if p['v'] is not None]
            if len(prev) >= 2:
                combos = [(a, b, a['v'] + b['v'], abs(a['v'] + b['v'] - r['v'])) for a in prev for b in prev if a is not b] \
                       + [(a, b, a['v'] - b['v'], abs(a['v'] - b['v'] - r['v'])) for a in prev for b in prev if a is not b]
                a, b, deriv, dist = min(combos, key=lambda t: t[3])
                floor = max(tol(r['v']), Decimal('0.05') * max(abs(r['v']), Decimal(1)))
                if dist <= floor:
                    ok = dist <= tol(r['v'], a['v'], b['v'])
                    print('  CHAIN line %-5s %-26s %s -> %s' % (r['line'], r['label'][:26], r['v'], 'OK' if ok else 'FAIL'))
                    if not ok:
                        fails.append(('CHAIN', [(r['line'], 2), (a['line'], 1), (b['line'], 1)]))
            pending = []
        else:
            pending.append(r)

num_map = [('gross', ['gross profit']), ('operating', ['operating income', 'operating profit']),
           ('ebitda', ['ebitda']), ('ebit', ['ebit']),
           ('pretax', ['income before', 'pretax']), ('net', ['net income', 'net profit'])]
growth_re = re.compile(r'growth|change|yoy|year.over.year|increase|decrease', re.I)
for r in allrows:
    if r['v'] is None or not ('%' in r['raw'] or re.search(r'margin|rate|ratio|yield', r['label'], re.I)):
        continue
    if growth_re.search(r['label']):
        print('  HINT  line %-5s %-26s growth/change: check (cur-prev)/|prev|*100 across period columns' % (r['line'], r['label'][:26]))
        continue
    num = None
    for kw, cands in num_map:
        if re.search(r'\b%s\b' % kw, r['label'], re.I):
            for cand in cands:
                p = r'\b' + r'\s+'.join(map(re.escape, cand.split())) + r'\b'
                hit = next((x for x in allrows if re.search(p, x['label'], re.I) and x['v'] is not None), None)
                if hit:
                    num = hit
                    break
        if num:
            break
    den = next((x for x in allrows if re.search(r'^(net |total )?(revenue|sales)$', x['label'], re.I) and x['v'] is not None), None)
    if num is None or den is None:
        print('  SKIP  line %-5s %-26s no component match - audit by hand' % (r['line'], r['label'][:26]))
        continue
    exp = (Decimal(100) * num['v'] / den['v']).quantize(Decimal(1).scaleb(-decd(r['v'])), rounding=ROUND_HALF_UP)
    ok = abs(r['v'] - exp) <= tol(r['v'])
    print('  RATIO line %-5s %-26s displayed %s%% vs %s/%s = %s%% -> %s' % (r['line'], r['label'][:26], r['v'], num['label'], den['label'], exp, 'OK' if ok else 'FAIL'))
    if not ok:
        fails.append(('RATIO', [(r['line'], 2), (num['line'], 1), (den['line'], 1)]))

def disp(c):
    t = c.strip()
    neg = t.startswith('(') and t.endswith(')')
    if neg:
        t = t[1:-1].strip()
    for s in '$€£¥%':
        t = t.replace(s, '')
    for s in '−–—':
        t = t.replace(s, '-')
    t = re.sub(r'[\u00a0\u202f ]', '', t)
    m = re.fullmatch(r'(-?)(\d{1,3}(?:\.\d{3})+|\d+),(\d{1,2})', t)
    t = m.group(1) + m.group(2).replace('.', '') + '.' + m.group(3) if m else t.replace(',', '')
    return ('-' + t if not t.startswith('-') else t) if neg else t

score = {}
for kind, members in fails:
    for line, w in members:
        score[line] = score.get(line, 0) + w
print('RESULT: failed identities:', [(k, [l for l, _ in m]) for k, m in fails])
print('line scores:', sorted(score.items(), key=lambda kv: -kv[1]))
if score:
    top = max(score.values())
    winners = [l for l, s in score.items() if s == top]
    if len(winners) == 1:
        row = next(r for r in allrows if r['line'] == winners[0])
        print('ANSWER: %s,%s' % (row['line'], disp(row['raw'])))
    else:
        print('ambiguous winners %s - audit manually per SKILL' % winners)
else:
    print('no violated identities - audit manually per SKILL')
EOF
```

Sanity checks on the printout before writing anything:

- `ROWS` count == number of numbered metrics visible in the HTML. A missing
  row means extraction ate it (nested tags, blank cells) — fix `text`/`val` to
  match the actual markup or fall back to `scripts/verify_finance.py`.
- Every `HINT` and `SKIP` is a to-do, not a pass — the one wrong metric may
  hide behind one of them (growth, per-share, unit conversions; see step 3).
- A `FAIL` does not automatically make that line the answer: cascades exist.
  A wrong component drags its totals/ratios into failing identities; the
  weighted `line scores` resolve this (derived members weigh 2, operands 1).
- If the instruction's hint narrows the class, the answer must satisfy it; if
  the snippet's winner contradicts the hint, audit both again.

### 3. Complete the identity sweep (hand checks)

The engine automates sums, chains and margin ratios. Before writing the answer,
finish these families by hand (they are the remaining spec axes):

1. **Growth / year-over-year** — `(current − prior) ÷ |prior| × 100`; find the
   two rows sharing a base label in different period columns/sections (the
   snippet's ROWS shows multi-column cells as `a | b`; confirm which column is
   current from the table headers). Keep displayed rounding.
2. **Per-share** — `total metric ÷ shares outstanding`; mind the unit note
   (dollars in millions ÷ shares in millions).
3. **Unit conversions** — same quantity in two units, applying the stated
   scale ("thousands" vs "millions").
4. **Chained statement lines** the chain check could not schedule — recompute
   `a±b` yourself for any profit/income/loss row that printed no CHAIN line.

Rounding/tolerance: re-derive with `ROUND_HALF_UP` to displayed decimals;
differences ≤ 0.5×10⁻ᵈ (+1e-9) are artifacts. Planted errors are typically far
larger; do not chase sub-unit noise.

### 4. Isolate the fault and gate the write

The scoring rule (mirror it by hand if you disagree with the winner): a derived
row (total/percentage/chain result) weighs 2, each operand row weighs 1; sum
over failed identities; the unique maximum is the answer. Ties or empty scores
→ audit: re-check extraction (row missed? unit scale? column order?) and
recompute suspicious values directly; if two candidate fixes restore full
consistency, prefer the fix on the derived (recomputed) metric — the planted
value always sits where the document's own arithmetic re-derives it.

Write only after a full pass: exactly one wrong displayed metric located, its
line number verbatim, and its value normalized per the instruction.

### 5. Write the answer and self-verify

Default format (v01): `line_number,value` — the instruction always governs.

- Token 1: the displayed line number next to the wrong metric, verbatim.
- Token 2: the **wrong value as displayed**, with %, currency, grouping
  separators removed; decimal commas become decimal points (`49,4%` → `49.4`).
  Keep digits, decimal point, minus sign. Do not "fix" the value.
- From `task_shell`: `printf '%s,%s\n' "$LINE" "$VALUE" > /app/value.txt`
  (use the instruction's exact path).

Checklist: file is one line matching `^[0-9]+,[0-9.,\-]+$` (adapt to the
instruction's format); the line number sits next to the metric you flagged;
the written value equals the displayed wrong value modulo removed symbols; the
failing identities fail and the neighbors hold; the answer is the wrong
displayed value, not the corrected one.

## Companion script (full-featured)

`scripts/verify_finance.py` implements the same rules with richer reporting and
a `--output` writer that refuses to write unless exactly one line fails.
Reachable only via host `read`; deploy by pasting its content into the
container:

```bash
cat > /app/vf.py <<'PY'
# ... content read from the skill package via the host read tool ...
PY
python3 /app/vf.py /app/q2_earnings_report.html          # audit printout
python3 /app/vf.py /app/q2_earnings_report.html --output /app/value.txt
```

Use it when the snippet prints many SKIPs or the markup is messy. Never execute
skill files by their host path inside `task_shell`.

## Common failure modes

- Rewriting your own mini-analyzer instead of pasting the snippet verbatim:
  observed agents hardcode the seed's labels and silently miss variant error
  classes (growth, per-share, subtotals, renamed metrics). If you must write
  code, keep it label-structure-driven (step 3 rules), not name-hardcoded.
- Assuming v01's "digit transposition" pattern repeats; verify each identity,
  do not pattern-match the seed.
- Using host `read`/`ls` on `/app` or running skill scripts by host path in
  `task_shell` — dead ends; `task_shell` for `/app`, heredocs for code.
- Writing the **corrected** value instead of the wrong displayed one.
- Flagging a component line instead of the derived metric line: distrust a
  winner that is an operand (weight 1) when its derived row also fails.
- Treating ≤0.5-last-unit rounding artifacts as errors, or missing unit-scale
  differences in conversion checks.
- Trusting "no violated identities" without checking every `HINT`/`SKIP` and
  the ROWS count.
- Assuming the wrong value is a percentage: variants may corrupt a dollar
  subtotal instead — the identity pass (not the seed's layout) decides.