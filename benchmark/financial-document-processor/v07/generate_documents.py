#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pillow==11.3.0",
#   "reportlab==4.4.3",
# ]
# ///

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "documents"
MANIFEST_PATH = ROOT / "document_manifest.json"
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


@dataclass(frozen=True)
class DocumentSpec:
    filename: str
    kind: str
    total_amount: float | None
    vat_amount: float | None
    format: str
    embedded_pages: list[list[str]]
    scanned_pages: list[list[str]]


def load_font(size: int) -> ImageFont.ImageFont:
    for path in FONT_PATHS:
        font_path = Path(path)
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


TITLE_FONT = load_font(44)
BODY_FONT = load_font(34)
SMALL_FONT = load_font(28)


def money(value: float) -> str:
    return f"{value:,.2f}"


def make_scan(lines: list[str], width: int = 1654, height: int = 2339) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    y = 120
    for index, line in enumerate(lines):
        if index == 0:
            font = TITLE_FONT
            y_step = 84
        elif line.startswith(("Subtotal", "Tax Rate", "Tax Basis", "Sales Tax", "Grand Total", "Amount Due", "Closing Balance", "Estimate Total", "Quoted Total", "Proposal Total", "Projected Tax", "Total")):
            font = BODY_FONT
            y_step = 64
        else:
            font = SMALL_FONT
            y_step = 56
        draw.text((120, y), line, fill="black", font=font)
        y += y_step

    for y_line in range(110, height, 310):
        draw.line((90, y_line, width - 90, y_line), fill=(225, 225, 225), width=2)

    image = image.rotate(-0.4, expand=False, fillcolor="white")
    return image.filter(ImageFilter.SHARPEN)


def write_jpg(path: Path, lines: list[str]) -> None:
    image = make_scan(lines)
    image.save(path, format="JPEG", quality=92)


def draw_embedded_page(pdf: canvas.Canvas, lines: list[str]) -> None:
    text = pdf.beginText(54, 742)
    text.setFont("Helvetica-Bold", 20)
    text.textLine(lines[0])
    text.setFont("Helvetica", 12)
    for line in lines[1:]:
        text.textLine(line)
    pdf.drawText(text)


def draw_scanned_page(pdf: canvas.Canvas, lines: list[str]) -> None:
    image = make_scan(lines, width=1500, height=2050)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    pdf.drawImage(ImageReader(buffer), 36, 36, width=540, height=720, preserveAspectRatio=True, mask="auto")


def write_pdf(path: Path, embedded_pages: list[list[str]], scanned_pages: list[list[str]]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, bottomup=1, invariant=1, pageCompression=0)

    total_pages = max(len(embedded_pages), len(scanned_pages))
    for page_index in range(total_pages):
        embedded_lines = embedded_pages[page_index] if page_index < len(embedded_pages) else []
        scanned_lines = scanned_pages[page_index] if page_index < len(scanned_pages) else []

        if embedded_lines:
            draw_embedded_page(pdf, embedded_lines)
        if scanned_lines:
            draw_scanned_page(pdf, scanned_lines)
        pdf.showPage()

    pdf.save()


def sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


DOCUMENTS = [
    DocumentSpec(
        filename="alpha_medical_supply.pdf",
        kind="invoice",
        total_amount=1488.00,
        vat_amount=248.00,
        format="pdf",
        embedded_pages=[
            [
                "TAX INVOICE",
                "Alpha Medical Supply Co.",
                "Invoice Ref: AMS-2048",
                "Bill To: Northgate Family Practice",
                "Issue Date: 2026-02-03",
                "Payment Terms: 15 days",
                "Line Items",
                "Diagnostic trays                    4 x 210.00",
                "Sterile packs                       8 x 50.00",
                "Exam lamp service                     400.00",
                "See summary on next page.",
            ]
        ],
        scanned_pages=[
            [
                "Alpha Medical Supply Summary",
                "Customer: Northgate Family Practice",
                "Subtotal                         1,240.00",
                "Tax Rate                              20%",
                "Grand Total                      1,488.00",
                "Remit with invoice reference AMS-2048",
            ]
        ],
    ),
    DocumentSpec(
        filename="beacon_catering.jpg",
        kind="invoice",
        total_amount=945.54,
        vat_amount=70.04,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Beacon Catering Billing Notice",
                "Invoice No. BC-771",
                "Client: Alder Ridge Partners",
                "Event meal service                    875.50",
                "Tax Rate                                 8%",
                "Amount Due                           945.54",
                "Please pay using invoice BC-771",
            ]
        ],
    ),
    DocumentSpec(
        filename="cobalt_fabrication.pdf",
        kind="invoice",
        total_amount=3420.00,
        vat_amount=570.00,
        format="pdf",
        embedded_pages=[
            [
                "Cobalt Fabrication Services",
                "Commercial Invoice",
                "Invoice Code: CFS-118",
                "Customer: Marek Industrial Ltd.",
                "Steel brackets batch                 1,900.00",
                "Custom drill plate                     950.00",
                "Amounts summarized below.",
            ]
        ],
        scanned_pages=[
            [
                "Summary Block",
                "Subtotal                         2,850.00",
                "Tax Rate                              20%",
                "Total Payable                     3,420.00",
                "Thank you for your business",
            ]
        ],
    ),
    DocumentSpec(
        filename="delta_maintenance.jpg",
        kind="invoice",
        total_amount=602.00,
        vat_amount=42.00,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Delta Maintenance Invoice",
                "Ref DM-552",
                "Service Address: 18 Pine Street",
                "Air filter replacement                 320.00",
                "Vent cleaning                          240.00",
                "Subtotal                              560.00",
                "Sales Tax                              7.5%",
                "Grand Total                           602.00",
            ]
        ],
    ),
    DocumentSpec(
        filename="ember_logistics.pdf",
        kind="invoice",
        total_amount=2160.00,
        vat_amount=360.00,
        format="pdf",
        embedded_pages=[
            [
                "Ember Logistics Account",
                "Invoice Reference EL-9002",
                "Bill To: Glenhaven Retail Group",
                "Route support package               1,200.00",
                "Regional dispatch fee                 600.00",
                "Final amount due                    2,160.00",
                "Tax details are summarized with the shipment record.",
            ]
        ],
        scanned_pages=[
            [
                "Shipment Record Summary",
                "Tax Basis                           1,800.00",
                "Tax Rate                                20%",
                "Release for payment against EL-9002",
            ]
        ],
    ),
    DocumentSpec(
        filename="fjord_analytics.jpg",
        kind="invoice",
        total_amount=1633.91,
        vat_amount=134.91,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Fjord Analytics Client Billing",
                "Invoice Ref FA-314",
                "Reporting package                    1,149.00",
                "Dashboard setup                        350.00",
                "Subtotal                            1,499.00",
                "Tax Rate                                 9%",
                "Amount Due                         1,633.91",
            ]
        ],
    ),
    DocumentSpec(
        filename="grove_electric.pdf",
        kind="invoice",
        total_amount=766.50,
        vat_amount=36.50,
        format="pdf",
        embedded_pages=[
            [
                "Grove Electric Works",
                "Invoice: GE-44",
                "Client: Pine Harbor Offices",
                "Emergency callout                      410.00",
                "Lighting replacement                   320.00",
                "Refer to attached field summary.",
            ]
        ],
        scanned_pages=[
            [
                "Field Summary",
                "Subtotal                              730.00",
                "Tax Rate                                 5%",
                "Grand Total                           766.50",
                "Please include GE-44 on remittance",
            ]
        ],
    ),
    DocumentSpec(
        filename="harbor_packaging.pdf",
        kind="invoice",
        total_amount=3520.00,
        vat_amount=320.00,
        format="pdf",
        embedded_pages=[
            [
                "Harbor Packaging Partners",
                "Invoice Number HP-808",
                "Customer: Stonewell Foods",
                "Packaging run                       2,200.00",
                "Custom labeling                       1,000.00",
                "Subtotal                            3,200.00",
                "Grand Total                         3,520.00",
            ]
        ],
        scanned_pages=[
            [
                "Payment Advice",
                "Use invoice number HP-808 when paying.",
                "No separate tax line was printed on this copy.",
            ]
        ],
    ),
    DocumentSpec(
        filename="iris_office.jpg",
        kind="invoice",
        total_amount=1275.00,
        vat_amount=0.00,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Iris Office Interiors",
                "Invoice ID IO-215",
                "Reception desk refinishing          1,275.00",
                "Subtotal                            1,275.00",
                "Tax Rate                                 0%",
                "Amount Due                         1,275.00",
                "Remit against IO-215",
            ]
        ],
    ),
    DocumentSpec(
        filename="juno_quote.pdf",
        kind="other",
        total_amount=None,
        vat_amount=None,
        format="pdf",
        embedded_pages=[
            [
                "Juno Systems Quotation",
                "Quote No: JS-Q-77",
                "Prepared For: Northgate Family Practice",
                "Server refresh option                1,240.00",
                "Support option                         248.00",
                "Quoted Total                        1,488.00",
                "This quotation is valid for 30 days and is not an invoice.",
            ]
        ],
        scanned_pages=[],
    ),
    DocumentSpec(
        filename="kestrel_estimate.jpg",
        kind="other",
        total_amount=None,
        vat_amount=None,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Kestrel Design Estimate",
                "Estimate Ref KD-19",
                "Lobby artwork concept                  875.50",
                "Projected Tax                             8%",
                "Estimate Total                         945.54",
                "This estimate is for approval only.",
            ]
        ],
    ),
    DocumentSpec(
        filename="lumen_statement.pdf",
        kind="other",
        total_amount=None,
        vat_amount=None,
        format="pdf",
        embedded_pages=[
            [
                "Lumen Energy Account Statement",
                "Statement Period: January 2026",
                "Opening Balance                        980.00",
                "Payments Received                     -400.00",
                "New Charges                            612.40",
                "Closing Balance                      1,192.40",
                "This statement summarizes account activity.",
            ]
        ],
        scanned_pages=[
            [
                "Customer Services",
                "Please do not use this statement as a tax invoice.",
            ]
        ],
    ),
    DocumentSpec(
        filename="meadow_proposal.jpg",
        kind="other",
        total_amount=None,
        vat_amount=None,
        format="jpg",
        embedded_pages=[],
        scanned_pages=[
            [
                "Meadow Build Proposal",
                "Proposal No MB-302",
                "Kitchen shelving package             3,200.00",
                "Optional finish upgrade                320.00",
                "Proposal Total                       3,520.00",
                "Acceptance creates a future work order.",
            ]
        ],
    ),
]


def build_documents() -> list[dict]:
    DOCS_DIR.mkdir(exist_ok=True)
    for existing in DOCS_DIR.iterdir():
        if existing.is_file():
            existing.unlink()

    manifest: list[dict] = []
    for spec in DOCUMENTS:
        path = DOCS_DIR / spec.filename
        if spec.format == "jpg":
            write_jpg(path, spec.scanned_pages[0])
        else:
            write_pdf(path, spec.embedded_pages, spec.scanned_pages)

        manifest.append(
            {
                "filename": spec.filename,
                "kind": spec.kind,
                "total_amount": spec.total_amount,
                "vat_amount": spec.vat_amount,
                "sha512": sha512(path),
            }
        )

    totals = {
        "invoice_count": sum(1 for item in manifest if item["kind"] == "invoice"),
        "other_count": sum(1 for item in manifest if item["kind"] == "other"),
        "total_amount_sum": round(
            sum(item["total_amount"] or 0 for item in manifest if item["kind"] == "invoice"),
            2,
        ),
        "vat_amount_sum": round(
            sum(item["vat_amount"] or 0 for item in manifest if item["kind"] == "invoice"),
            2,
        ),
    }

    payload = {"documents": manifest, "totals": totals}
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    build_documents()
