#!/bin/bash

set -euo pipefail

python3 - <<'PY'
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

html_path = Path('/app/quarterly-bridge.html')
output_path = Path('/app/value.txt')

row_pattern = re.compile(
    r'<tr><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>'
)
number_pattern = re.compile(r'-?\d+(?:\.\d+)?')


def parse_decimal(text: str) -> Decimal:
    match = number_pattern.search(text.replace(',', ''))
    if not match:
        raise ValueError(f'No numeric value found in {text!r}')
    return Decimal(match.group(0))


lines = html_path.read_text().splitlines()

for idx, line in enumerate(lines, start=1):
    match = row_pattern.search(line)
    if not match:
        continue

    _metric, current_text, prior_text, reported_text = match.groups()
    current = parse_decimal(current_text)
    prior = parse_decimal(prior_text)
    reported = parse_decimal(reported_text)

    if prior == 0:
        continue

    actual = ((current - prior) / prior * Decimal('100')).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP
    )
    if actual != reported:
        output_path.write_text(f'{idx},{reported}')
        break
else:
    raise SystemExit('No inconsistent YoY percentage found')
PY
