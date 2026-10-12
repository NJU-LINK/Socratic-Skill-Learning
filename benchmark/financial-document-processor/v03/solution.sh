#!/bin/bash

set -euo pipefail

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources

apt-get update >/tmp/financial-doc-apt-update.log
DEBIAN_FRONTEND=noninteractive apt-get install -y tesseract-ocr poppler-utils imagemagick >/tmp/financial-doc-apt-install.log

python3 - <<'PY'
import csv
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path


DOCUMENTS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"


def run(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)


def canonical(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def preprocess_to_png(source: Path, destination: Path) -> None:
    if source.suffix.lower() == ".pdf":
        base = destination.with_suffix("")
        subprocess.check_call(
            ["pdftoppm", "-r", "300", "-png", "-singlefile", str(source), str(base)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pdf_png = base.with_suffix(".png")
        subprocess.check_call(
            ["convert", str(pdf_png), "-colorspace", "Gray", "-resize", "200%", str(destination)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.check_call(
            ["convert", str(source), "-colorspace", "Gray", "-resize", "200%", str(destination)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def ocr_lines(source: Path) -> list[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        prepared = Path(temp_dir) / "prepared.png"
        preprocess_to_png(source, prepared)
        text = run(["tesseract", str(prepared), "stdout", "--psm", "6"])
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_amount_token(token: str) -> Decimal | None:
    cleaned = token.replace(",", "")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if not cleaned or cleaned == ".":
        return None
    if cleaned.count(".") > 1:
        first, *rest = cleaned.split(".")
        cleaned = first + "." + "".join(rest)
    if "." in cleaned:
        left, right = cleaned.split(".", 1)
        left = left or "0"
        if not left.isdigit() or not right.isdigit():
            return None
        if len(right) == 0:
            right = "00"
        elif len(right) == 1:
            right = right + "0"
        elif len(right) > 2:
            right = right[:2]
        return Decimal(f"{int(left)}.{right}")
    if not cleaned.isdigit():
        return None
    if len(cleaned) >= 3:
        return Decimal(f"{cleaned[:-2]}.{cleaned[-2:]}")
    return Decimal(cleaned)


def parse_amount_from_line(line: str) -> Decimal | None:
    matches = re.findall(r"[0-9][0-9.,]*", line)
    for token in reversed(matches):
        amount = parse_amount_token(token)
        if amount is not None:
            return amount
    return None


def total_label_rank(key: str) -> int | None:
    if "grandtotal" in key:
        return 0
    if "total" in key and not any(
        excluded in key
        for excluded in ["subtotal", "gsttotal", "vattotal", "taxtotal", "goodstotal", "totalvat", "totaltax"]
    ):
        return 1
    if "amountpayable" in key:
        return 2
    if "topay" in key:
        return 3
    if "netpay" in key:
        return 4
    if "amountdue" in key:
        return 5
    return None


def classify(lines: list[str]) -> bool:
    joined = "\n".join(lines)
    text = canonical(joined)
    normalized_lines = [(line, canonical(line)) for line in lines]
    has_total_cue = any(total_label_rank(key) is not None for _, key in normalized_lines)
    has_plain_total_cue = any(total_label_rank(key) in [0, 1] for _, key in normalized_lines)

    positive = 0
    negative = 0

    for cue in [
        "taxreceipt",
        "taxslip",
        "businessreceipt",
        "commercialreceipt",
        "receipt",
        "grandtotal",
        "amountdue",
        "amountpayable",
        "topay",
        "netpay",
        "billto",
        "account",
        "client",
        "buyer",
        "subtotal",
        "goodstotal",
    ]:
        if cue in text:
            positive += 1

    if has_plain_total_cue:
        positive += 1

    for cue in [
        "paymentconfirmation",
        "refundnotice",
        "shiftsalesreport",
        "salesreport",
        "settlementadvice",
        "endofdaysummary",
        "paymentreceived",
        "noamountdue",
        "refund",
        "cardsettled",
        "grosssales",
    ]:
        if cue in text:
            negative += 2

    if ("gstreg" in text or "vatid" in text or "vatreg" in text) and any(
        cue in text for cue in ["grandtotal", "total", "amountdue", "amountpayable", "topay", "netpay"]
    ):
        positive += 2

    return positive > negative and has_total_cue


def extract_amounts(lines: list[str]) -> tuple[Decimal, Decimal]:
    total_amount = None
    vat_amount = None
    normalized_lines = [(line, canonical(line)) for line in lines]

    for rank in range(6):
        for line, key in normalized_lines:
            if total_label_rank(key) != rank:
                continue
            amount = parse_amount_from_line(line)
            if amount is not None:
                total_amount = amount
                break
        if total_amount is not None:
            break

    for line, key in normalized_lines:
        if any(label in key for label in ["gstreg", "gstno", "vatid", "vatreg", "gsttotal"]):
            continue
        if "gst" in key or key.startswith("vat") or "vat" in key:
            amount = parse_amount_from_line(line)
            if amount is not None:
                vat_amount = amount
                break

    if total_amount is None:
        raise RuntimeError(f"Could not extract total amount from OCR lines: {lines}")
    if vat_amount is None:
        vat_amount = Decimal("0.00")

    return total_amount.quantize(Decimal("0.01")), vat_amount.quantize(Decimal("0.01"))


def main() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, Decimal, Decimal]] = []

    for source in sorted(DOCUMENTS_DIR.iterdir()):
        if not source.is_file():
            continue
        lines = ocr_lines(source)
        if classify(lines):
            total_amount, vat_amount = extract_amounts(lines)
            destination = INVOICES_DIR / source.name
            rows.append((source.name, total_amount, vat_amount))
        else:
            destination = OTHER_DIR / source.name
        shutil.move(str(source), str(destination))

    total_total = sum((row[1] for row in rows), Decimal("0.00"))
    total_vat = sum((row[2] for row in rows), Decimal("0.00"))

    with SUMMARY_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for filename, total_amount, vat_amount in sorted(rows):
            writer.writerow([filename, f"{total_amount:.2f}", f"{vat_amount:.2f}"])
        writer.writerow(["total", f"{total_total:.2f}", f"{total_vat:.2f}"])

    if any(DOCUMENTS_DIR.iterdir()):
        raise RuntimeError("/app/documents is not empty after processing")


if __name__ == "__main__":
    main()
PY
