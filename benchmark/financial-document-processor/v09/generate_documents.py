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


def make_pdf(filename: str, lines: list[str]) -> None:
    path = OUTPUT_DIR / filename
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 72

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, y, lines[0])
    y -= 28

    pdf.setFont("Helvetica", 11)
    for line in lines[1:]:
        pdf.drawString(72, y, line)
        y -= 18

    pdf.save()


def make_jpg(filename: str, lines: list[str]) -> None:
    path = OUTPUT_DIR / filename
    image = Image.new("RGB", (1400, 1000), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=28)
    body_font = ImageFont.load_default(size=22)

    y = 60
    draw.text((70, y), lines[0], fill="black", font=title_font)
    y += 60
    for line in lines[1:]:
        draw.text((70, y), line, fill="black", font=body_font)
        y += 42

    image.save(path, quality=95)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    make_pdf(
        "harbor_billing_statement.pdf",
        [
            "Harbor Electrical Services",
            "Billing Statement",
            "Remit To: Harbor Electrical Services, 18 Fleet Street, Portland",
            "Bill To: Northwind Cafe, 25 River Avenue, Portland",
            "Statement Ref: HES-2048",
            "Service Date: 2026-02-11",
            "Payment Terms: Pay within 15 days",
            "Account Summary",
            "Inspection and rewiring labor   1,240.00",
            "Replacement parts                 210.00",
            "VAT 10%                           145.00",
            "Balance Due                     1,595.00",
        ],
    )

    make_pdf(
        "lighthouse_account_summary.pdf",
        [
            "Lighthouse Office Supply",
            "Account Summary",
            "Remit To: Lighthouse Office Supply, 9 Cedar Way, Albany",
            "Bill To: Green Dock Ventures, 41 Bay Road, Albany",
            "Reference: LOS-8831",
            "Payment Terms: Net 30",
            "Desk organizers and binders       780.00",
            "Shipping                            60.00",
            "Tax                                 67.20",
            "Total Due                          907.20",
        ],
    )

    make_pdf(
        "spruce_service_record.pdf",
        [
            "Spruce IT Support",
            "Service Record",
            "Remit To: Spruce IT Support, 77 Market Lane, Madison",
            "Bill To: Finch Legal Group, 120 King Street, Madison",
            "Work Order: SIT-5510",
            "Payment Terms: Due on receipt",
            "Server patching and backup review   450.00",
            "Device health check                  35.00",
            "Closing Amount                      485.00",
            "Tax not separately charged",
        ],
    )

    make_jpg(
        "autumn_quote_request.jpg",
        [
            "Autumn Renovations",
            "Quote Request",
            "Please prepare a pricing estimate for lobby paint, new trim, and two light fixtures.",
            "Budget target: 1,700.00 to 2,100.00",
            "This note is for planning only and is not a request for payment.",
            "Send options by Friday to hello@autumn.example",
        ],
    )

    make_jpg(
        "northshore_account_memo.jpg",
        [
            "Northshore Retail",
            "Account Memo",
            "The team reviewed shelf labels showing unit prices of 14.50, 22.00, and 39.95.",
            "These figures are for comparison during the quarterly stock meeting.",
            "No balance is due and no remittance should be sent for this memo.",
        ],
    )


if __name__ == "__main__":
    main()
