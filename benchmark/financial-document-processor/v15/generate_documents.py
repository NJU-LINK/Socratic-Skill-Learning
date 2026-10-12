#!/usr/bin/env python3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


OUT_DIR = Path("/tmp/original_documents")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def write_jpg(filename: str, title: str, lines: list[str]) -> None:
    image = Image.new("RGB", (1400, 1800), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(FONT_BOLD_PATH, 44)
    body_font = ImageFont.truetype(FONT_PATH, 32)

    y = 90
    draw.text((90, y), title, fill="black", font=title_font)
    y += 90
    for line in lines:
        draw.text((90, y), line, fill="black", font=body_font)
        y += 56

    image.save(OUT_DIR / filename, quality=95)


def write_pdf(filename: str, title: str, lines: list[str]) -> None:
    pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_PATH))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONT_BOLD_PATH))

    path = OUT_DIR / filename
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    y = height - 72
    pdf.setFont("DejaVuSans-Bold", 18)
    pdf.drawString(72, y, title)
    y -= 36

    pdf.setFont("DejaVuSans", 12)
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 22

    pdf.save()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    write_jpg(
        "north_hill_receipt.jpg",
        "NORTH HILL PROPERTY SERVICES",
        [
            "Receipt for onsite repair visit",
            "Customer: Maple Studio",
            "Service Date: 2026-04-04",
            "Work Order: 1842",
            "",
            "Labour                         180.00",
            "Materials                       20.00",
            "GST                             20.00",
            "Grand Total                    220.00",
            "",
            "Please remit within 7 days.",
        ],
    )

    write_jpg(
        "harbor_trade_ticket.jpg",
        "HARBOR TRADE SUPPLY",
        [
            "Sales Ticket",
            "Deliver To: Pine Cafe",
            "Counter Ref: 33-91",
            "",
            "Cutting discs                    32.50",
            "Fasteners                        35.50",
            "GST                              6.80",
            "Balance Due                     74.80",
            "",
            "Thank you for your business.",
        ],
    )

    write_pdf(
        "citywide_cleaning_statement.pdf",
        "CITYWIDE CLEANING CO",
        [
            "Service Summary",
            "Account: Brookside Dental",
            "Visit Date: 2026-04-18",
            "",
            "Evening clean                150.00",
            "Consumables                  18.00",
            "Subtotal                    168.00",
            "GST                          16.80",
            "Balance Due                 184.80",
            "",
            "Payment terms: 14 days",
        ],
    )

    write_jpg(
        "parking_notice.jpg",
        "BRIGHTSTAR OFFICE PARK",
        [
            "Internal Notice",
            "Parking area resurfacing starts Monday.",
            "Budget code 441 is listed for accounting records.",
            "No payment is requested from tenants.",
            "This notice is for scheduling only.",
        ],
    )

    write_jpg(
        "supplier_letter.jpg",
        "LUMEN PAPER GOODS",
        [
            "Supplier Letter",
            "Price list revisions take effect July 1.",
            "Sample carton estimate: 46.00 per unit.",
            "These figures are estimates only.",
            "This letter is not a bill and no balance is due.",
            "Please update your purchasing records.",
        ],
    )


if __name__ == "__main__":
    main()
