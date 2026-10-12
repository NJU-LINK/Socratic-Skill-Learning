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


def write_pdf(filename: str, lines: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUTPUT_DIR / filename
    doc = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter
    y = height - 54

    for line in lines:
        if y < 54:
            doc.showPage()
            y = height - 54
        doc.setFont("Helvetica", 12)
        doc.drawString(54, y, line)
        y -= 18

    doc.save()


def write_jpg(filename: str, lines: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1500, 1900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    y = 60

    for line in lines:
        draw.text((60, y), line, fill="black", font=font)
        y += 38

    image.save(OUTPUT_DIR / filename, quality=95)


def build_documents() -> None:
    documents = [
        (
            "north_harbor_service_record.pdf",
            [
                "North Harbor Facility Services",
                "Service Charge Record",
                "Client: Alder Manufacturing",
                "Reference: NH-4821",
                "Service Period: April 2025",
                "Remit To: 88 Bay Street, Portland",
                "Payment Terms: Net 21",
                "Description                Qty     Rate      Line Total",
                "Dock equipment tune-up      1    1,840.00    1,840.00",
                "Safety inspection           1      265.00      265.00",
                "Parts replenishment         1      145.00      145.00",
                "Subtotal                                      2,250.00",
                "VAT 10%                                         225.00",
                "Final Payable                                 2,475.00",
                "Please reference NH-4821 with remittance.",
            ],
            "pdf",
        ),
        (
            "lattice_cloud_billing_note.jpg",
            [
                "Lattice Cloud Ops",
                "Monthly Service Charges",
                "Bill To: Copper State Labs",
                "Service Window: 01 May - 31 May 2025",
                "Customer Ref: LC-9017",
                "Remittance Contact: billing@lattice.example",
                "Terms: Pay within 15 days",
                "Compute reservation                   620.00",
                "Archive storage                        85.00",
                "Support add-on                        145.00",
                "Net charges                           850.00",
                "Sales Tax 8%                           68.00",
                "Balance to Pay                        918.00",
                "Thank you for your business.",
            ],
            "jpg",
        ),
        (
            "elm_street_maintenance_sheet.pdf",
            [
                "Elm Street Building Care",
                "Maintenance Billing Summary",
                "For: Rayburn Legal Group",
                "Service Ref: ES-1172",
                "Work Completed: Lobby lighting and HVAC filters",
                "Terms: Due on receipt",
                "Labor                                      540.00",
                "Materials                                  120.00",
                "Travel                                      40.00",
                "Total                                      700.00",
                "Amount Due                                 715.00",
                "Tax                                         70.00",
                "Remit payment to Elm Street Building Care.",
            ],
            "pdf",
        ),
        (
            "solstice_design_fee_notice.jpg",
            [
                "Solstice Design Studio",
                "Project Fee Notice",
                "Prepared For: Meadow Retail Interiors",
                "Engagement: Storefront mockups",
                "Reference: SDS-44-05",
                "Payment Terms: Net 30",
                "Concept package                         1,100.00",
                "Revision cycle                            180.00",
                "Subtotal                                1,280.00",
                "VAT                                     128.00",
                "Amount Due                             1,408.00",
                "Questions: accounts@solstice.example",
            ],
            "jpg",
        ),
        (
            "atlas_budget_projection.pdf",
            [
                "Atlas Expansion Program",
                "Quarterly Budget Projection",
                "Prepared for Executive Review",
                "Category              Q3 Estimate   Tax Impact   Total",
                "Office furniture        8,400.00      672.00    9,072.00",
                "Travel                  2,200.00      176.00    2,376.00",
                "Recruiting              4,500.00      360.00    4,860.00",
                "Notes: planning worksheet only; no payment should be issued.",
                "Approval status: pending finance sign-off.",
            ],
            "pdf",
        ),
        (
            "greenline_purchase_request.jpg",
            [
                "Greenline Transit",
                "Purchase Request",
                "Requestor: Depot Operations",
                "Items Requested",
                "Brake kits x12                         1,920.00",
                "Lubricant drums x4                       340.00",
                "Estimated tax                            180.80",
                "Estimated total                        2,440.80",
                "This request is not a bill and should not be paid.",
                "Awaiting procurement approval.",
            ],
            "jpg",
        ),
        (
            "cedar_account_memo.pdf",
            [
                "Cedar Advisory Partners",
                "Account Memo",
                "Subject: Reserve adjustment for June",
                "Opening reserve                         5,000.00",
                "Tax accrual increase                      125.00",
                "Closing reserve                         5,125.00",
                "This memo documents an internal adjustment only.",
                "No customer payment is expected from this record.",
            ],
            "pdf",
        ),
        (
            "riverside_team_expense_sheet.jpg",
            [
                "Riverside Field Team",
                "Expense Summary",
                "Hotel                                 410.00",
                "Mileage                               186.40",
                "Meals tax                              22.35",
                "Reimbursement total                   618.75",
                "Submitted for manager approval.",
                "This is a reimbursement summary, not a customer charge.",
            ],
            "jpg",
        ),
    ]

    for filename, lines, kind in documents:
        if kind == "pdf":
            write_pdf(filename, lines)
        else:
            write_jpg(filename, lines)


if __name__ == "__main__":
    build_documents()
