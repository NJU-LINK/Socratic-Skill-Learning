#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from __future__ import annotations

import csv
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path


DOCUMENTS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")

MONEY = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)")
FINAL_LABELS = (
    "amount payable",
    "balance due",
    "total due now",
    "total due",
    "amount due",
    "final charges",
    "invoice total",
    "grand total",
    "total payable",
)
TAX_LABELS = ("service tax", "sales tax", "vat", "gst", "tax")
NEGATIVE_MARKERS = (
    "not an invoice",
    "not a bill",
    "no payment due",
    "no remittance required",
    "does not request payment",
    "not a request for payment",
    "for records only",
)


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        command = ["pdftotext", str(path), "-"]
    else:
        command = ["tesseract", str(path), "stdout", "--psm", "6"]
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def normalized_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip().lower()
        for line in text.splitlines()
        if line.strip()
    ]


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_invoice(lines: list[str]) -> bool:
    text = compact("\n".join(lines))
    if any(compact(marker) in text for marker in NEGATIVE_MARKERS):
        return False
    has_identity = "invoice" in text or "billto" in text
    has_payment_request = any(compact(label) in text for label in FINAL_LABELS)
    return has_identity and has_payment_request


def amount_for(lines: list[str], labels: tuple[str, ...]) -> Decimal:
    for label in labels:
        for line in lines:
            if compact(label) not in compact(line):
                continue
            matches = MONEY.findall(line)
            if matches:
                token = matches[-1].replace(",", "")
                if "." in token:
                    return Decimal(token)
                return Decimal(token) / Decimal("100")
    raise ValueError(f"no amount found for labels {labels}")


def main() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, Decimal, Decimal]] = []
    for source in sorted(path for path in DOCUMENTS_DIR.iterdir() if path.is_file()):
        lines = normalized_lines(extract_text(source))
        if not is_invoice(lines):
            shutil.move(str(source), OTHER_DIR / source.name)
            continue

        total = amount_for(lines, FINAL_LABELS)
        tax = amount_for(lines, TAX_LABELS)
        shutil.move(str(source), INVOICES_DIR / source.name)
        rows.append((source.name, total, tax))

    with (INVOICES_DIR / "summary.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for filename, total, tax in rows:
            writer.writerow([filename, f"{total:.2f}", f"{tax:.2f}"])
        writer.writerow(
            [
                "total",
                f"{sum((row[1] for row in rows), Decimal('0')):.2f}",
                f"{sum((row[2] for row in rows), Decimal('0')):.2f}",
            ]
        )


main()
PY
