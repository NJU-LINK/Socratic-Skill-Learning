#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["pillow==11.3.0"]
# ///

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


OUT_DIR = Path("/tmp/original_documents")


DOCUMENTS = [
    {
        "filename": "alpine_analytics_billing_statement.pdf",
        "kind": "pdf",
        "lines": [
            "Billing Statement",
            "Statement Ref: AS-10017",
            "Service Date: 2026-01-18",
            "Bill To: Cedar Trail Retail",
            "Consulting Services: 1,280.00",
            "Net Charges: 1,280.00",
            "VAT 10%: 128.00",
            "Amount Due: 1,408.00",
        ],
    },
    {
        "filename": "blueharbor_studio_tax_document.pdf",
        "kind": "pdf",
        "lines": [
            "Tax Document",
            "Reference: BH-10021",
            "Issued: 2026-01-20",
            "Client: Harbor View Cafe",
            "Design Retainer: 696.00",
            "Tax: 55.68",
            "Grand Total: 751.68",
            "Please remit within 14 days.",
        ],
    },
    {
        "filename": "northfield_supply_remittance_notice.pdf",
        "kind": "pdf",
        "lines": [
            "Remittance Notice",
            "Document ID: NF-10032",
            "Dispatch Date: 2026-02-02",
            "Ship To: Linden Works",
            "Hardware Order: 2,450.00",
            "Subtotal: 2,450.00",
            "Sales Tax: 196.00",
            "Payable Total: 2,646.00",
        ],
    },
    {
        "filename": "orbit_logistics_charge_note.jpg",
        "kind": "jpg",
        "style": "scan_light",
        "lines": [
            "Charge Note",
            "Doc Ref: OR-10044",
            "Issue Date: 2026-02-11",
            "Customer: Moss Street Market",
            "Freight Services: 980.00",
            "GST: 78.40",
            "Total Due: 1,058.40",
        ],
    },
    {
        "filename": "payment_reminder_lumen_partners.pdf",
        "kind": "pdf",
        "lines": [
            "Payment Reminder",
            "Reference: ACC-204",
            "Customer: Lumen Partners",
            "Outstanding Balance: 1,408.00",
            "Total Due This Week: 1,408.00",
            "Prior Tax Amount: 128.00",
            "This notice is not a tax invoice.",
        ],
    },
    {
        "filename": "purchase_order_greenline_trade.pdf",
        "kind": "pdf",
        "lines": [
            "Purchase Order",
            "PO Number: PO-7713",
            "Vendor: Greenline Trade",
            "Requested Total: 2,250.00",
            "Estimated Tax: 180.00",
            "Approved Spend Ceiling: 2,430.00",
            "Approval Status: Pending",
        ],
    },
    {
        "filename": "receipt_lakeside_cafe.jpg",
        "kind": "jpg",
        "style": "scan_heavy",
        "lines": [
            "Receipt",
            "Lakeside Cafe",
            "Card Payment Approved",
            "Subtotal: 49.27",
            "VAT Included: 4.93",
            "Total Paid: 54.20",
        ],
    },
    {
        "filename": "expense_summary_summit_travel.jpg",
        "kind": "jpg",
        "style": "scan_light",
        "lines": [
            "Expense Reimbursement Summary",
            "Employee: Dana Cole",
            "Approved Meals: 118.40",
            "Approved Taxi: 200.00",
            "Approved Total: 318.40",
            "Reclaimable Tax: 0.00",
        ],
    },
]


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, lines: list[str]) -> None:
    text_ops = ["BT", "/F1 14 Tf", "50 750 Td"]
    for index, line in enumerate(lines):
        if index:
            text_ops.append("0 -22 Td")
        text_ops.append(f"({_escape_pdf_text(line)}) Tj")
    text_ops.append("ET")
    content = "\n".join(text_ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_num, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    path.write_bytes(pdf)


def write_jpg(path: Path, lines: list[str], style: str = "clean") -> None:
    image = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()

    y = 120
    for line in lines:
        draw.text((120, y), line, fill="black", font=font)
        y += 95

    if style == "scan_light":
        image = image.rotate(0.8, expand=True, fillcolor="white")
        image = image.filter(ImageFilter.GaussianBlur(0.4))
        image = image.crop((40, 40, image.width - 40, image.height - 40))
    elif style == "scan_heavy":
        image = image.rotate(-1.2, expand=True, fillcolor="white")
        image = image.filter(ImageFilter.GaussianBlur(0.9))
        image = image.crop((60, 60, image.width - 60, image.height - 60))

    image.save(path, format="JPEG", quality=78 if style == "scan_heavy" else 90, subsampling=0)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUT_DIR.iterdir():
        if existing.is_file():
            existing.unlink()

    for document in DOCUMENTS:
        path = OUT_DIR / document["filename"]
        if document["kind"] == "pdf":
            write_pdf(path, document["lines"])
        else:
            write_jpg(path, document["lines"], document.get("style", "clean"))


if __name__ == "__main__":
    main()
