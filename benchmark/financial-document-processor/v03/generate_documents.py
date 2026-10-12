#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pillow==11.3.0",
# ]
# ///

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


DOCUMENTS = [
    {
        "filename": "harbor_bean_tax_receipt.jpg",
        "kind": "invoice",
        "title": "Tax Receipt",
        "merchant": "Harbor Bean Roastery",
        "lines": [
            "78 Pier Arcade",
            "GST Reg 44-812-991",
            "Txn ID HB-48201",
            "Date 2026-03-12 14:09",
            "Bill To Blue Fern Studio",
            "Arabica Beans      2 x 18.50",
            "Catering Prep      1 x 40.55",
            "Subtotal              77.55",
            "GST                    7.05",
            "Amount Payable        84.60",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "northline_guest_copy.pdf",
        "kind": "invoice",
        "title": "Guest Tax Receipt",
        "merchant": "Northline Hotel Pantry",
        "lines": [
            "Lobby Market Counter",
            "VAT ID NL-557-20",
            "Ref NL-1138",
            "Stay Date 2026-03-18",
            "Account Cora Lane Events",
            "Refreshment Tray   1 x 132.00",
            "Service Charge     1 x 14.00",
            "Net                  146.00",
            "VAT                   12.20",
            "To Pay               158.20",
        ],
        "format": "pdf",
        "phone_capture": False,
    },
    {
        "filename": "metro_foods_counter.jpg",
        "kind": "invoice",
        "title": "Business Receipt",
        "merchant": "Metro Foods Canteen",
        "lines": [
            "Terminal 2 Concourse",
            "GST No 77-404-112",
            "Slip MF-9007",
            "Date 2026-03-27 08:31",
            "Bill To Maple Ward Clinic",
            "Breakfast Packs    3 x 10.00",
            "Delivery Fee       1 x 10.00",
            "Subtotal              40.00",
            "GST                    3.50",
            "Net Pay               43.50",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "oak_market_supply.pdf",
        "kind": "invoice",
        "title": "Supply Tax Slip",
        "merchant": "Oak Market Wholesale",
        "lines": [
            "Warehouse K4",
            "VAT Reg OM-2201",
            "Txn OM-73492",
            "Date 2026-04-02",
            "Buyer Juniper Office Services",
            "Pantry Cartons     6 x 29.80",
            "Cleaning Wipes     2 x 15.75",
            "Goods Total          210.10",
            "VAT                  21.00",
            "Amount Payable      231.10",
        ],
        "format": "pdf",
        "phone_capture": False,
    },
    {
        "filename": "green_tray_checkout.jpg",
        "kind": "invoice",
        "title": "Commercial Receipt",
        "merchant": "Green Tray Catering",
        "lines": [
            "South Arcade Kitchen",
            "GST Reg 08-330-614",
            "Receipt GT-6504",
            "Date 2026-04-07 11:22",
            "Client Lattice Repair Co",
            "Lunch Set           4 x 18.40",
            "Drink Pack          1 x 14.35",
            "Subtotal              87.55",
            "GST                    8.75",
            "To Pay               96.30",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "harbor_bean_payment.jpg",
        "kind": "other",
        "title": "Payment Confirmation",
        "merchant": "Harbor Bean Roastery",
        "lines": [
            "78 Pier Arcade",
            "Card Approval Copy",
            "Txn ID HB-48201",
            "Date 2026-03-12 14:10",
            "Merchant Copy",
            "Charged Amount       84.60",
            "Card Visa            84.60",
            "Status Approved",
            "No amount due",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "northline_refund.pdf",
        "kind": "other",
        "title": "Refund Notice",
        "merchant": "Northline Hotel Pantry",
        "lines": [
            "Lobby Market Counter",
            "Case RF-1138",
            "Processed 2026-03-19",
            "Guest Card Refund",
            "Original Charge      21.00",
            "Refunded             21.00",
            "Method Card Return",
            "Closed by Desk Lead",
        ],
        "format": "pdf",
        "phone_capture": False,
    },
    {
        "filename": "metro_foods_shift.jpg",
        "kind": "other",
        "title": "Shift Sales Report",
        "merchant": "Metro Foods Canteen",
        "lines": [
            "Terminal 2 Concourse",
            "Morning Shift",
            "Opened 2026-03-27 06:00",
            "Sales Count 43",
            "Gross Sales         618.40",
            "GST Collected        49.12",
            "Cards               590.10",
            "Cash                 28.30",
            "Supervisor Mina P",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "oak_market_settlement.jpg",
        "kind": "other",
        "title": "Settlement Advice",
        "merchant": "Oak Market Wholesale",
        "lines": [
            "Warehouse K4",
            "Settlement Batch OM-73492",
            "Date 2026-04-02",
            "Payment Received",
            "Transfer Amount     231.10",
            "Reference Matched",
            "No open balance",
            "Accounts Team Copy",
        ],
        "format": "jpg",
        "phone_capture": True,
    },
    {
        "filename": "green_tray_endofday.pdf",
        "kind": "other",
        "title": "End of Day Summary",
        "merchant": "Green Tray Catering",
        "lines": [
            "South Arcade Kitchen",
            "Kitchen Day Close",
            "Date 2026-04-07",
            "Receipts Count 17",
            "Net Sales           622.15",
            "GST Total            53.14",
            "Card Settled        590.00",
            "Cash Drawer          32.15",
            "Manager Signed Inez",
        ],
        "format": "pdf",
        "phone_capture": False,
    },
]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def render_receipt(doc: dict, destination: Path) -> None:
    width = 760 if doc["format"] == "jpg" else 580
    padding_x = 42
    padding_top = 30
    line_height = 38
    content_height = padding_top + 90 + len(doc["lines"]) * line_height + 30

    paper = Image.new("RGB", (width, content_height), (250, 248, 242))
    draw = ImageDraw.Draw(paper)

    if doc["phone_capture"]:
        draw.rectangle((0, 0, width, content_height), fill=(235, 232, 227))
        receipt = Image.new("RGB", (width - 52, content_height - 40), (253, 252, 247))
        receipt_draw = ImageDraw.Draw(receipt)
        receipt_draw.rectangle((0, 0, receipt.width - 1, receipt.height - 1), outline=(210, 205, 198), width=2)
        draw.rounded_rectangle((26, 20, width - 18, content_height - 12), radius=16, fill=(210, 206, 199))
        paper.paste(receipt, (18, 12))
        draw = ImageDraw.Draw(paper)
    else:
        draw.rectangle((0, 0, width - 1, content_height - 1), outline=(205, 205, 205), width=1)

    title_font = load_font(34, bold=True)
    merchant_font = load_font(30, bold=True)
    text_font = load_font(26)

    left = padding_x
    draw.text((left, padding_top), doc["merchant"], font=merchant_font, fill=(25, 25, 25))
    draw.text((left, padding_top + 40), doc["title"], font=title_font, fill=(45, 45, 45))

    y = padding_top + 95
    for line in doc["lines"]:
        draw.text((left, y), line, font=text_font, fill=(35, 35, 35))
        y += line_height

    if doc["phone_capture"]:
        paper = paper.filter(ImageFilter.GaussianBlur(radius=0.35))
        paper = paper.rotate(1.4, expand=True, fillcolor=(232, 229, 223))
        paper = paper.crop(paper.getbbox())

    if doc["format"] == "pdf":
        paper.convert("RGB").save(destination, "PDF", resolution=160.0)
    else:
        paper.save(destination, "JPEG", quality=88)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for doc in DOCUMENTS:
        render_receipt(doc, output_dir / doc["filename"])


if __name__ == "__main__":
    main()
