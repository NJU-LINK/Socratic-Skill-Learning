# v01 workthrough — Ridgeway Robotics Q2 Earnings Snapshot

Regression anchor for skill `html-finance-verify`.
Expected answer: **`210,60.8`** written to `/app/value.txt`.

## Input

`/app/q2_earnings_report.html`: two tables — income statement (lines 110–200)
and KPI sidebar (lines 210–230). Instruction: exactly one displayed KPI
percentage is wrong; output `line_number,value` with the wrong value as shown,
no percent sign.

## Parsed metric triples (13)

| Line | Label | Shown | Value |
|---|---|---|---|
| 110 | Revenue | $842.0 | 842.0 |
| 120 | Cost of revenue | $321.6 | 321.6 |
| 130 | Gross profit | $520.4 | 520.4 |
| 140 | Research and development | $129.7 | 129.7 |
| 150 | Sales and marketing | $96.8 | 96.8 |
| 160 | General and administrative | $54.1 | 54.1 |
| 170 | Total operating expenses | $280.6 | 280.6 |
| 180 | Operating income | $239.8 | 239.8 |
| 190 | Other income, net | $11.2 | 11.2 |
| 200 | Net income | $251.0 | 251.0 |
| 210 | Gross margin | 60.8% | 60.8 |
| 220 | Operating margin | 28.5% | 28.5 |
| 230 | Net margin | 29.8% | 29.8 |

## Relations reconstructed (7 checks)

| Check | Formula | Recomputed | Rounded (1 dp) | Shown | Verdict |
|---|---|---|---|---|---|
| Gross margin (210) | 100 × 520.4 / 842.0 | 61.8052… | 61.8 | 60.8 | **VIOLATION** |
| Operating margin (220) | 100 × 239.8 / 842.0 | 28.4798… | 28.5 | 28.5 | OK |
| Net margin (230) | 100 × 251.0 / 842.0 | 29.8099… | 29.8 | 29.8 | OK |
| Total opex (170) | 129.7 + 96.8 + 54.1 | 280.6 | 280.6 | 280.6 | OK |
| Gross profit (130) | 842.0 − 321.6 | 520.4 | 520.4 | 520.4 | OK |
| Operating income (180) | 520.4 − 280.6 | 239.8 | 239.8 | 239.8 | OK |
| Net income (200) | 239.8 + 11.2 | 251.0 | 251.0 | 251.0 | OK |

Unchecked metrics (bases): Revenue, Cost of revenue, R&D, Sales & marketing,
G&A, Other income — all are base quantities with no derivable relation.

## Discriminating evidence

All dollar relations hold; two of three margins hold. Only line 210 (Gross
margin) violates: shown `60.8%` vs recomputed `61.8%` (61.805…) at one-decimal
display precision (tolerance 0.05). Exactly one violation ⇒ answer.

## Output

```
210,60.8
```

Wrong **displayed** value (60.8, not the corrected 61.8), no percent sign,
precision verbatim. Line token `210` is the report's own labeling, not a
source-file line count.

## Regression command

```bash
python3 checker.py /app/q2_earnings_report.html --out /app/value.txt --expect 210,60.8
# exit 0; /app/value.txt contains: 210,60.8
```

## Generalization notes (what this instance teaches the family)

- The error sits in a *cross-table* relation: sidebar percentages vs statement
  dollars. Do not restrict relation building to a single table.
- One-decimal percentages: a 0.1 display-step deviation from the recomputed
  rounded value is a violation; sub-0.05 noise is not.
- The wrong value is reported *as displayed* — the correct computation
  (61.8) must never be written; regression guard `--expect 210,60.8` exists
  precisely to catch that failure mode.