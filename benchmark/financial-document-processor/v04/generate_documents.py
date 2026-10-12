#!/usr/bin/env python3
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parent / "documents"
FONT = ImageFont.load_default()
PAGE_SIZE = (1654, 2339)
MARGIN = 120
LINE_HEIGHT = 34


DOCUMENTS = [
    {
        "filename": "north_harbor_invoice_a.jpg",
        "kind": "invoice",
        "title": "INVOICE",
        "lines": [
            "North Harbor Supplies",
            "55 Quay Market Road, Seattle, WA 98104",
            "Bill To: Cedar Ridge Operations",
            "Invoice Number: NH-2048",
            "Invoice Date: 2026-03-04",
            "Payment Terms: Net 15",
            "Remit To: North Harbor Supplies Lockbox 5510",
            "Line Items",
            "Dock labels and archive folders ........ 1,120.00",
            "Storage crates ..........................   680.50",
            "Subtotal ............................... 1,800.50",
            "Tax ....................................   144.04",
            "Amount Due ............................. 1,944.54",
            "Total .................................. 1,944.54",
        ],
    },
    {
        "filename": "north_harbor_invoice_b.pdf",
        "kind": "invoice",
        "title": "INVOICE",
        "lines": [
            "North Harbor Supplies",
            "Accounts Receivable Desk",
            "Bill To: Oak Summit Food Group",
            "Invoice No: NH-2056",
            "Statement Date: 2026-03-18",
            "Payment Terms: Due on Receipt",
            "Remittance Address: PO Box 1881, Seattle, WA 98124",
            "Service summary",
            "Packaging review ........................ 2,350.00",
            "Compliance stickers ....................   420.00",
            "Subtotal ............................... 2,770.00",
            "VAT ....................................   221.60",
            "Grand Total ............................ 2,991.60",
        ],
    },
    {
        "filename": "bluefern_invoice_scan.jpg",
        "kind": "invoice",
        "title": "TAX INVOICE",
        "lines": [
            "Bluefern Ledger Services",
            "14 Willow Exchange, Portland, OR 97204",
            "Customer: Mesa Trail Retail",
            "Invoice Number: BL-7781",
            "Date of Issue: 2026-04-02",
            "Terms: Net 30",
            "Please remit payment to Bluefern Ledger Services",
            "Consulting retainer .................... 3,980.00",
            "Records normalization ..................   615.00",
            "Subtotal ............................... 4,595.00",
            "GST ....................................   367.60",
            "Total .................................. 4,962.60",
        ],
    },
    {
        "filename": "bluefern_invoice_letter.pdf",
        "kind": "invoice",
        "title": "INVOICE",
        "lines": [
            "Bluefern Ledger Services",
            "Bill To: Prairie Vale Kitchens",
            "Invoice Number: BL-7812",
            "Invoice Date: 2026-04-11",
            "Payment Terms: Net 10",
            "Remit To: Bluefern Ledger Services, ACH ID 449201",
            "Monthly reconciliation ................. 1,260.00",
            "Travel archive setup ...................   140.00",
            "Subtotal ............................... 1,400.00",
            "Tax ....................................   112.00",
            "Total .................................. 1,512.00",
        ],
    },
    {
        "filename": "copperleaf_invoice_packet.jpg",
        "kind": "invoice",
        "title": "INVOICE",
        "lines": [
            "Copperleaf Procurement Group",
            "Bill To: Harbor Point Catering",
            "Invoice No: CP-9904",
            "Issue Date: 2026-04-23",
            "Payment Terms: Net 21",
            "Remit Payment To: Copperleaf Procurement Group",
            "Warehouse coordination fee ............. 2,840.00",
            "Rush handling ..........................   460.00",
            "Subtotal ............................... 3,300.00",
            "VAT ....................................   264.00",
            "Amount Due ............................. 3,564.00",
            "Total .................................. 3,564.00",
        ],
    },
    {
        "filename": "copperleaf_invoice_copy.pdf",
        "kind": "invoice",
        "title": "INVOICE",
        "lines": [
            "Copperleaf Procurement Group",
            "Bill To: Aspen Terrace Lodging",
            "Invoice Number: CP-9927",
            "Invoice Date: 2026-05-02",
            "Payment Terms: Net 30",
            "Remit To: Copperleaf Procurement Group Treasury",
            "Supply coordination .................... 1,980.00",
            "Freight planning .......................   310.00",
            "Subtotal ............................... 2,290.00",
            "Tax ....................................   183.20",
            "Grand Total ............................ 2,473.20",
        ],
    },
    {
        "filename": "north_harbor_expense_claim.jpg",
        "kind": "other",
        "title": "EXPENSE CLAIM PACKET",
        "lines": [
            "North Harbor Supplies",
            "Employee reimbursement worksheet",
            "Department: Field Support",
            "Claim Reference: RC-2048",
            "Meals total ............................   186.20",
            "Taxi total .............................    44.00",
            "Tax included on receipts ...............    19.40",
            "Amount due back to employee ............   230.20",
            "Status: awaiting manager approval",
            "This document is not a bill for payment.",
        ],
    },
    {
        "filename": "north_harbor_purchase_summary.pdf",
        "kind": "other",
        "title": "PURCHASE SUMMARY",
        "lines": [
            "North Harbor Supplies",
            "Quarterly procurement summary",
            "Program: branch refresh",
            "Line items approved for stocking",
            "Cart total ............................. 4,118.00",
            "Estimated tax ..........................   329.44",
            "Projected amount due after rebate ...... 3,900.00",
            "Prepared for internal forecasting only",
            "No remittance requested on this summary",
        ],
    },
    {
        "filename": "bluefern_reimbursement_form.jpg",
        "kind": "other",
        "title": "REIMBURSEMENT FORM",
        "lines": [
            "Bluefern Ledger Services",
            "Traveler: Sonia Patel",
            "Report ID: BF-RM-7781",
            "Hotel amount ...........................   540.00",
            "Mileage amount .........................   132.50",
            "Tax on lodging .........................    48.60",
            "Total reimbursement requested ..........   721.10",
            "Approval terms: supervisor and finance",
            "Not an invoice. Internal staff form.",
        ],
    },
    {
        "filename": "bluefern_budget_statement.pdf",
        "kind": "other",
        "title": "QUARTERLY BUDGET STATEMENT",
        "lines": [
            "Bluefern Ledger Services",
            "Budget office statement for Q2",
            "Operating total ........................ 9,440.00",
            "Tax reserve ............................   755.20",
            "Amount due next quarter allocation ..... 2,000.00",
            "Variance line items reviewed internally",
            "For planning purposes only",
        ],
    },
    {
        "filename": "copperleaf_procurement_review.jpg",
        "kind": "other",
        "title": "PROCUREMENT REVIEW",
        "lines": [
            "Copperleaf Procurement Group",
            "Supplier comparison worksheet",
            "Review batch: CP-9904",
            "Line item total ....................... 2,610.00",
            "Tax exposure estimate .................   208.80",
            "Amount due if approved next month ..... 2,818.80",
            "Recommendation: hold pending legal review",
            "Internal summary only",
        ],
    },
    {
        "filename": "copperleaf_expense_rollup.pdf",
        "kind": "other",
        "title": "EXPENSE ROLLUP",
        "lines": [
            "Copperleaf Procurement Group",
            "Regional expense rollup",
            "Submitted totals from five teams",
            "Travel total ........................... 1,904.30",
            "Tax credited ...........................   102.11",
            "Amount due to clear balances ...........   418.00",
            "This packet consolidates prior receipts",
            "No customer billing information present",
        ],
    },
    {
        "filename": "summit_expense_packet.jpg",
        "kind": "other",
        "title": "EXPENSE REPORT",
        "lines": [
            "Oak Summit Food Group",
            "Expense packet for district chef summit",
            "Meals total ............................   688.40",
            "Venue tax ..............................    55.07",
            "Total requested reimbursement ..........   743.47",
            "Payable after approval, not before",
            "Employee and manager signatures required",
        ],
    },
    {
        "filename": "summit_rebate_statement.pdf",
        "kind": "other",
        "title": "REBATE STATEMENT",
        "lines": [
            "Oak Summit Food Group",
            "Vendor rebate reconciliation",
            "Gross purchases ........................ 7,880.00",
            "Tax posted .............................   630.40",
            "Amount due from vendor credits .........   990.00",
            "Statement for rebate tracking",
            "No invoice number assigned",
        ],
    },
    {
        "filename": "mesa_claim_sheet.jpg",
        "kind": "other",
        "title": "CLAIM SHEET",
        "lines": [
            "Mesa Trail Retail",
            "Store opening claim sheet",
            "Line items carried from receipts",
            "Fixtures total ......................... 1,115.00",
            "Tax total ..............................    89.20",
            "Amount due to store fund ...............   315.00",
            "Used for reimbursement accounting only",
        ],
    },
    {
        "filename": "mesa_quarterly_summary.pdf",
        "kind": "other",
        "title": "QUARTERLY PURCHASE SUMMARY",
        "lines": [
            "Mesa Trail Retail",
            "Category: front-end supplies",
            "Approved line item total ............... 5,420.00",
            "Tax reserve ............................   433.60",
            "Projected amount due on next order ..... 2,710.00",
            "This summary is not an invoice",
        ],
    },
    {
        "filename": "prairie_internal_packet.jpg",
        "kind": "other",
        "title": "INTERNAL PAYMENT REVIEW",
        "lines": [
            "Prairie Vale Kitchens",
            "Finance review packet",
            "Amount due under draft scenario ........ 1,480.00",
            "Tax under draft scenario ...............   118.40",
            "Total draft commitment ................. 1,598.40",
            "No external billing notice has been issued",
            "Internal approval packet only",
        ],
    },
    {
        "filename": "harborpoint_spend_report.pdf",
        "kind": "other",
        "title": "SPEND REPORT",
        "lines": [
            "Harbor Point Catering",
            "Monthly spend report",
            "Approved total ........................ 6,060.00",
            "Tax detail .............................   484.80",
            "Amount due if renewal approved ......... 1,212.00",
            "This report supports budgeting decisions",
            "Not a request for remittance",
        ],
    },
]


def wrap_lines(lines):
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=55) or [""])
    return wrapped


def render_page(title, lines):
    image = Image.new("RGB", PAGE_SIZE, color="white")
    draw = ImageDraw.Draw(image)
    y = MARGIN
    draw.text((MARGIN, y), title, fill="black", font=FONT)
    y += LINE_HEIGHT * 2
    for line in wrap_lines(lines):
        draw.text((MARGIN, y), line, fill="black", font=FONT)
        y += LINE_HEIGHT
    return image


def save_document(doc):
    image = render_page(doc["title"], doc["lines"])
    out_path = OUT_DIR / doc["filename"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".pdf":
        image.save(out_path, "PDF", resolution=150.0)
    else:
        image.save(out_path, quality=92)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUT_DIR.iterdir():
        if existing.is_file():
            existing.unlink()
    for doc in DOCUMENTS:
        save_document(doc)
    print(f"Generated {len(DOCUMENTS)} documents in {OUT_DIR}")


if __name__ == "__main__":
    main()
