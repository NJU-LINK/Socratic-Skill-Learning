#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pillow==11.3.0",
#   "reportlab==4.4.3",
# ]
# ///

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


OUTPUT_DIR = Path("/tmp/original_documents")


def write_pdf(filename: str, title: str, lines: list[str]) -> None:
    path = OUTPUT_DIR / filename
    doc = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 54

    doc.setFont("Helvetica-Bold", 20)
    doc.drawString(54, y, title)
    y -= 32

    doc.setFont("Helvetica", 11)
    for line in lines:
        if line == "":
            y -= 12
            continue
        doc.drawString(54, y, line)
        y -= 16
    doc.save()


def write_image(filename: str, title: str, lines: list[str]) -> None:
    path = OUTPUT_DIR / filename
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=46)
    body_font = ImageFont.load_default(size=28)

    y = 70
    draw.text((85, y), title, fill="black", font=title_font)
    y += 90
    for line in lines:
        if line == "":
            y += 18
            continue
        draw.text((85, y), line, fill="black", font=body_font)
        y += 45
    image.save(path, quality=95)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    write_pdf(
        "northwind_billing_statement.pdf",
        "Billing Statement",
        [
            "Supplier: Northwind Industrial Supply",
            "Customer: Greenfield Dental Clinic",
            "Statement No: BS-2048",
            "Issue Date: 2025-03-15",
            "",
            "Item                       Qty      Unit Price      Line Total",
            "Filter cartridges           8        110.00          880.00",
            "Service call                1        200.45          200.45",
            "",
            "Subtotal: 1080.45",
            "VAT 10%: 108.05",
            "Balance Due: 1188.50",
            "Payment terms: Net 15",
        ],
    )

    write_image(
        "maple_tax_receipt.jpg",
        "Tax Receipt",
        [
            "Issuer: Maple Street Office Interiors",
            "Bill To: Harbor Analytics Ltd.",
            "Receipt Ref: TR-7714",
            "",
            "Description                 Qty      Unit        Amount",
            "Desk pedestal                2       180.00       360.00",
            "Cable tray kit               3        42.00       126.00",
            "Delivery                     1        54.00        54.00",
            "",
            "Net Amount: 540.00",
            "GST: 43.20",
            "Gross Amount: 583.20",
            "",
            "Please reference the receipt ref when paying.",
        ],
    )

    write_pdf(
        "orbit_settlement_record.pdf",
        "Settlement Record",
        [
            "Provider: Orbit Lab Systems",
            "Customer: Pinecrest Veterinary Group",
            "Account Ref: SR-3301",
            "Prepared On: 2025-04-02",
            "",
            "Service Plan Renewal        1        1450.00        1450.00",
            "Calibration Visit           2         275.00         550.00",
            "Priority Support            1         125.00         125.00",
            "",
            "Settlement Total: 2125.00",
            "Collection method: bank transfer",
        ],
    )

    write_image(
        "blueharbor_client_statement.jpg",
        "Client Billing Statement",
        [
            "Issuer: Blue Harbor Creative",
            "Customer: Alder Ridge Homes",
            "Statement ID: CB-1190",
            "",
            "Campaign concept package     1        760.00       760.00",
            "Print proof revisions        2         95.00       190.00",
            "",
            "Tax: 76.00",
            "Settlement Total: 1026.00",
            "Please remit within 10 days.",
        ],
    )

    write_pdf(
        "q3_budget_overview.pdf",
        "Q3 Budget Overview",
        [
            "Department: Field Operations",
            "Prepared by: Amelia Shaw",
            "",
            "Projected travel total: 4200.00",
            "Equipment due this quarter: 1800.00",
            "Total planned spend: 7600.00",
            "Variance target: 3%",
            "",
            "This planning sheet is for budgeting only and is not a bill.",
        ],
    )

    write_image(
        "harbor_payment_reminder.jpg",
        "Payment Reminder",
        [
            "Account: Harbor View Storage",
            "Customer: Lena Walters",
            "Reminder Date: 2025-04-11",
            "",
            "Previous balance due: 245.00",
            "Late fee if unpaid by Friday: 15.00",
            "Reminder total shown for reference: 260.00",
            "",
            "This notice summarizes an overdue account and is not a tax invoice.",
        ],
    )

    write_pdf(
        "jetstream_purchase_order.pdf",
        "Purchase Order",
        [
            "Buyer: Jetstream Fabrication",
            "Vendor: Granite Tool House",
            "PO Number: PO-8802",
            "",
            "Cutting wheels               20        14.50         290.00",
            "Safety gloves               12         9.75         117.00",
            "",
            "Order Total: 407.00",
            "Requested ship date: 2025-04-20",
            "This document authorizes a purchase and is not an invoice.",
        ],
    )

    write_image(
        "team_expense_summary.jpg",
        "Team Expense Summary",
        [
            "Team: Customer Success",
            "Reporting Month: March 2025",
            "",
            "Meals total: 182.40",
            "Mileage due for reimbursement: 96.00",
            "Hotel total: 410.00",
            "",
            "Grand summary amount: 688.40",
            "Internal reimbursement worksheet only.",
        ],
    )


if __name__ == "__main__":
    main()
