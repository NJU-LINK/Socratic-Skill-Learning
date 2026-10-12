#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re

html_path = Path('/app/segment_report.html')
output_path = Path('/app/value.txt')
text = html_path.read_text()
lines = text.splitlines()


def parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(',', '').replace('%', '')
    return Decimal(cleaned)


segment_pattern = re.compile(
    r'<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*</tr>',
    re.S,
)
snapshot_pattern = re.compile(
    r'<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*</tr>',
    re.S,
)

segment_rows = []
in_segment_section = False
for line in lines:
    if 'Section A: Segment performance' in line:
        in_segment_section = True
        continue
    if 'Section B: Consolidated snapshot' in line:
        in_segment_section = False
    if in_segment_section:
        segment_rows.append(line)

segment_text = '\n'.join(segment_rows)
segment_revenue_total = Decimal('0')
segment_income_total = Decimal('0')
for _segment, revenue, income in segment_pattern.findall(segment_text):
    segment_revenue_total += parse_decimal(revenue)
    segment_income_total += parse_decimal(income)

snapshot_rows = []
in_snapshot_section = False
for line in lines:
    if 'Section B: Consolidated snapshot' in line:
        in_snapshot_section = True
        continue
    if in_snapshot_section:
        snapshot_rows.append(line)

snapshot_text = '\n'.join(snapshot_rows)
reported = {}
for metric, value in snapshot_pattern.findall(snapshot_text):
    reported[metric.strip()] = value.strip()

expected_margin = (
    (segment_income_total / segment_revenue_total) * Decimal('100')
).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

checks = []
checks.append(
    (
        'Consolidated revenue',
        parse_decimal(reported['Consolidated revenue']) == segment_revenue_total,
        reported['Consolidated revenue'],
    )
)
checks.append(
    (
        'Adjusted operating income',
        parse_decimal(reported['Adjusted operating income']) == segment_income_total,
        reported['Adjusted operating income'],
    )
)
checks.append(
    (
        'Operating margin',
        parse_decimal(reported['Operating margin']) == expected_margin,
        reported['Operating margin'],
    )
)

bad_metrics = [item for item in checks if not item[1]]
if len(bad_metrics) != 1:
    raise SystemExit(f'Expected exactly one inconsistent metric, found {len(bad_metrics)}')

bad_metric_name, _ok, bad_metric_value = bad_metrics[0]
bad_line_number = None
for idx, line in enumerate(lines, start=1):
    if bad_metric_name in line:
        for follow_idx in range(idx + 1, min(idx + 5, len(lines) + 1)):
            if bad_metric_value in lines[follow_idx - 1]:
                bad_line_number = follow_idx
                break
    if bad_line_number is not None:
        break

if bad_line_number is None:
    raise SystemExit('Could not locate incorrect metric line number')

numeric_value = bad_metric_value.replace(',', '').replace('%', '').strip()
output_path.write_text(f'{bad_line_number},{numeric_value}\n')
PY
