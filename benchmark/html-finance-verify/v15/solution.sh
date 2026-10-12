#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

python3 - <<'PY'
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import os
import re


app_dir = Path(os.environ.get("APP_DIR", "/app"))
HTML_PATH = app_dir / "cashflow_review.html"
OUTPUT_PATH = app_dir / "answer.txt"


def parse_decimal(raw: str) -> Decimal:
    cleaned = raw.strip().replace(",", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    return Decimal(cleaned)


lines = HTML_PATH.read_text(encoding="utf-8").splitlines()
metric_pattern = re.compile(r"<tr><td>(.*?)</td><td class=\"num\">(.*?)</td></tr>")

metrics: dict[str, tuple[str, int]] = {}
for line_number, line in enumerate(lines, start=1):
    match = metric_pattern.search(line)
    if match:
        metrics[match.group(1)] = (match.group(2), line_number)

operating_cash_flow = parse_decimal(metrics["Net cash provided by operating activities"][0])
capital_expenditures = parse_decimal(metrics["Capital expenditures"][0])
acquisitions = parse_decimal(metrics["Acquisitions, net of cash acquired"][0])
asset_disposals = parse_decimal(metrics["Proceeds from asset disposals"][0])
investing_total = parse_decimal(metrics["Net cash used in investing activities"][0])
repurchases = parse_decimal(metrics["Repurchases of common stock"][0])
dividends = parse_decimal(metrics["Cash dividends paid"][0])
net_borrowings = parse_decimal(metrics["Net borrowings"][0])
financing_total = parse_decimal(metrics["Net cash used in financing activities"][0])
free_cash_flow = parse_decimal(metrics["Free cash flow"][0])
shares = parse_decimal(metrics["Weighted-average diluted shares outstanding (millions)"][0])
free_cash_flow_per_share = parse_decimal(metrics["Free cash flow per diluted share"][0])
capex_percent = parse_decimal(metrics["Capital expenditures as a percentage of operating cash flow"][0])

checks = []

expected_investing_total = capital_expenditures + acquisitions - asset_disposals
checks.append((
    metrics["Net cash used in investing activities"][1],
    metrics["Net cash used in investing activities"][0],
    expected_investing_total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    investing_total,
))

expected_financing_total = repurchases + dividends - net_borrowings
checks.append((
    metrics["Net cash used in financing activities"][1],
    metrics["Net cash used in financing activities"][0],
    expected_financing_total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    financing_total,
))

expected_free_cash_flow = operating_cash_flow - capital_expenditures
checks.append((
    metrics["Free cash flow"][1],
    metrics["Free cash flow"][0],
    expected_free_cash_flow.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    free_cash_flow,
))

expected_fcf_per_share = (free_cash_flow / shares).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
checks.append((
    metrics["Free cash flow per diluted share"][1],
    metrics["Free cash flow per diluted share"][0],
    expected_fcf_per_share,
    free_cash_flow_per_share,
))

expected_capex_percent = ((capital_expenditures / operating_cash_flow) * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
checks.append((
    metrics["Capital expenditures as a percentage of operating cash flow"][1],
    metrics["Capital expenditures as a percentage of operating cash flow"][0],
    expected_capex_percent,
    capex_percent,
))

incorrect = [check for check in checks if check[2] != check[3]]
if len(incorrect) != 1:
    raise SystemExit(f"Expected exactly one incorrect metric, found {len(incorrect)}")

line_number, shown_value, _, _ = incorrect[0]
OUTPUT_PATH.write_text(f"{line_number},{shown_value}\n", encoding="utf-8")
PY
