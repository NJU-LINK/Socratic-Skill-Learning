#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pillow==11.3.0",
# ]
# ///

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


DOCS = [
    {
        "filename": "north_harbor_billing_document.pdf",
        "kind": "pdf",
        "lines": [
            "North Harbor Studio",
            "Billing Document",
            "",
            "Bill To: Lattice Retail Ltd",
            "Service Window: April 2026",
            "Reference: BD-1048",
            "",
            "Creative retainers and print revisions    1,120.00",
            "VAT                                         112.00",
            "Amount Due                                1,050.00",
            "Total                                     1,232.00",
            "",
            "Please remit within 14 days.",
        ],
    },
    {
        "filename": "cedar_field_tax_invoice.jpg",
        "kind": "jpg",
        "lines": [
            "CEDAR FIELD SERVICES",
            "Tax Invoice",
            "",
            "Customer: Greyline Foods",
            "Visit Date: 2026-05-03",
            "Ticket: T-3381",
            "",
            "Drain inspection and reset          870.00",
            "Tax                                  87.00",
            "Amount Due                          900.00",
            "Total                               957.00",
            "",
            "Thank you for your business.",
        ],
    },
    {
        "filename": "foothill_client_billing.pdf",
        "kind": "pdf",
        "lines": [
            "Foothill Equipment Care",
            "Client Billing",
            "",
            "Customer: Aster Logistics",
            "Maintenance cycle: May 2026",
            "",
            "Inspection labor                    2,000.00",
            "Parts and consumables                 400.00",
            "GST                                   120.00",
            "Grand Total                         2,520.00",
            "",
            "Footer Ref: Invoice No FR-2081",
        ],
    },
    {
        "filename": "atlas_account_statement.pdf",
        "kind": "pdf",
        "lines": [
            "Atlas Office Supply",
            "Statement of Account",
            "",
            "Opening Balance                       410.00",
            "Payments Received                    -410.00",
            "Tax Posted This Period                35.00",
            "Statement Total                        0.00",
            "Amount Due                             0.00",
            "",
            "This statement is not a tax invoice.",
        ],
    },
    {
        "filename": "brio_proforma_quote.jpg",
        "kind": "jpg",
        "lines": [
            "BRIO INTERIORS",
            "Pro Forma Quote",
            "",
            "Proposed shelving package          1,400.00",
            "Tax                                  140.00",
            "Quoted Total                       1,540.00",
            "Deposit Due                          300.00",
            "",
            "This quote is for approval only.",
        ],
    },
    {
        "filename": "luma_purchase_order.pdf",
        "kind": "pdf",
        "lines": [
            "Luma Kitchens",
            "Purchase Order",
            "",
            "PO Number: 318-77",
            "Cabinet pulls and hinges             640.00",
            "Tax Estimate                          64.00",
            "Order Total                          704.00",
            "",
            "Please ship against this purchase order.",
        ],
    },
    {
        "filename": "marlow_expense_summary.jpg",
        "kind": "jpg",
        "lines": [
            "MARLOW CONSULTING",
            "Travel Expense Summary",
            "",
            "Meals                                120.00",
            "Tax                                    8.40",
            "Grand Total                          128.40",
            "Reimbursement Pending                128.40",
            "",
            "Internal expense summary only.",
        ],
    },
    {
        "filename": "summit_monthly_statement.jpg",
        "kind": "jpg",
        "lines": [
            "SUMMIT WHOLESALE",
            "Monthly Account Statement",
            "",
            "Merchandise subtotal                 980.00",
            "Tax                                   98.00",
            "Statement Total                    1,078.00",
            "Amount Due                             0.00",
            "",
            "For account review only.",
        ],
    },
]


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_bytes(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "72 740 Td"]
    first = True
    for line in lines:
        if not first:
            content_lines.append("0 -18 Td")
        first = False
        safe = pdf_escape(line)
        content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return buffer.getvalue()


def build_scan_image(lines: list[str]) -> Image.Image:
    font = ImageFont.load_default()
    image = Image.new("L", (1100, 1500), color=255)
    draw = ImageDraw.Draw(image)

    y = 60
    for line in lines:
        draw.text((50, y), line, font=font, fill=0)
        y += 24

    image = image.resize((2200, 3000), resample=Image.Resampling.NEAREST)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.4))
    return image.convert("RGB")


def write_doc(target_dir: Path, doc: dict[str, object]) -> None:
    path = target_dir / str(doc["filename"])
    lines = [str(line) for line in doc["lines"]]

    if doc["kind"] == "pdf":
        path.write_bytes(build_pdf_bytes(lines))
        return

    image = build_scan_image(lines)
    image.save(path, format="JPEG", quality=92)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_documents.py TARGET_DIR")

    target_dir = Path(sys.argv[1])
    target_dir.mkdir(parents=True, exist_ok=True)

    for doc in DOCS:
        write_doc(target_dir, doc)


if __name__ == "__main__":
    main()
