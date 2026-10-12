#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pillow>=11.3.0",
#   "reportlab>=4.4.3",
# ]
# ///

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


OUTPUT_DIR = Path("/tmp/original_documents")


DOCUMENTS = [
    {
        "filename": "northwind_service_completion.pdf",
        "kind": "other",
        "title": "Service Completion Packet",
        "lines": [
            "Vendor: Northwind Climate Services",
            "Work Order: NC-5412",
            "Site: Alder Ridge Family Clinic",
            "Status: Completed - not an invoice",
            "Labor hours closed: 14.0",
            "Parts used: compressor relay, condenser fan",
            "Recorded labor and parts total: $1,840.00",
            "Estimated service tax exposure: $147.20",
            "Projected final charges for billing review: $1,987.20",
            "Customer signature captured on completion packet.",
            "No payment is due from this document.",
        ],
    },
    {
        "filename": "northwind_invoice.pdf",
        "kind": "invoice",
        "title": "Vendor Billing Invoice",
        "lines": [
            "Vendor: Northwind Climate Services",
            "Invoice Number: INV-NC-5412",
            "Bill To: Alder Ridge Family Clinic",
            "Service Date: 2026-03-11",
            "Labor and parts subtotal: $1,840.00",
            "Service Tax: $147.20",
            "Amount Payable: $1,987.20",
            "Remit payment within 15 days.",
        ],
    },
    {
        "filename": "blueharbor_repair_summary.pdf",
        "kind": "other",
        "title": "Repair Summary",
        "lines": [
            "Vendor: Blue Harbor Elevator Works",
            "Summary ID: BH-884",
            "Status: Work completed and filed",
            "Labor charges recorded: $2,210.00",
            "Replacement parts estimate: $330.00",
            "Estimated tax for later billing: $203.20",
            "Projected total after approvals: $2,743.20",
            "This repair summary is not a bill.",
        ],
    },
    {
        "filename": "blueharbor_invoice.pdf",
        "kind": "invoice",
        "title": "Accounts Receivable Invoice",
        "lines": [
            "Vendor: Blue Harbor Elevator Works",
            "Invoice Number: BH-884-AR",
            "Bill To: Alder Ridge Family Clinic",
            "Service subtotal: $2,540.00",
            "Service Tax: $203.20",
            "Final Charges: $2,743.20",
            "Please remit to Accounts Receivable.",
        ],
    },
    {
        "filename": "cedarfield_work_order.pdf",
        "kind": "other",
        "title": "Closed Work Order",
        "lines": [
            "Vendor: Cedarfield Office Systems",
            "Work Order: CFO-2217",
            "Status: Closed",
            "Technician notes: fleet copier feed assembly replaced",
            "Internal cost rollup: $612.00",
            "Tax reference for billing queue: $0.00",
            "Document type: work order archive",
            "No remittance required.",
        ],
    },
    {
        "filename": "granitepeak_service_report.pdf",
        "kind": "other",
        "title": "Field Service Report",
        "lines": [
            "Vendor: Granite Peak Fire & Safety",
            "Report: GP-1109",
            "Inspection result: service complete",
            "Recorded materials total: $1,160.00",
            "Forecast tax line: $92.80",
            "Forecast billing total: $1,252.80",
            "This report closes the field visit and does not request payment.",
        ],
    },
    {
        "filename": "granitepeak_invoice.jpg",
        "kind": "invoice",
        "title": "Payment Invoice",
        "lines": [
            "Vendor: Granite Peak Fire & Safety",
            "Invoice Number: GP-1109-INV",
            "Bill To: Alder Ridge Family Clinic",
            "Inspection and parts subtotal $1,160.00",
            "Service Tax $92.80",
            "Amount Payable $1,252.80",
            "Remit to Granite Peak Fire & Safety",
        ],
    },
    {
        "filename": "harborlight_completion_packet.pdf",
        "kind": "other",
        "title": "Completion Packet",
        "lines": [
            "Vendor: Harborlight Grounds Maintenance",
            "Packet ID: HGM-772",
            "Completed services: irrigation controller reset and trench repair",
            "Labor and equipment record: $955.00",
            "Estimated service tax: $76.40",
            "Budget total for billing conversion: $1,031.40",
            "Operational packet only. Not an invoice.",
        ],
    },
    {
        "filename": "harborlight_invoice.pdf",
        "kind": "invoice",
        "title": "Customer Invoice",
        "lines": [
            "Vendor: Harborlight Grounds Maintenance",
            "Invoice Number: HGM-772-01",
            "Bill To: Alder Ridge Family Clinic",
            "Service subtotal: $955.00",
            "Service Tax: $76.40",
            "Final Charges: $1,031.40",
            "Payment due upon receipt.",
        ],
    },
    {
        "filename": "ironwood_maintenance_summary.jpg",
        "kind": "other",
        "title": "Maintenance Summary",
        "lines": [
            "Vendor: Ironwood Security Integrators",
            "Summary Ref: ISI-448",
            "Panel firmware updated and sensors recalibrated",
            "Labor record $1,480.00",
            "Parts reserve $210.00",
            "Estimated tax $135.20",
            "Projected final charges $1,825.20",
            "Maintenance summary only - no payment due",
        ],
    },
    {
        "filename": "ironwood_invoice.pdf",
        "kind": "invoice",
        "title": "Service Invoice",
        "lines": [
            "Vendor: Ironwood Security Integrators",
            "Invoice Number: ISI-448-B",
            "Bill To: Alder Ridge Family Clinic",
            "Labor and parts subtotal: $1,690.00",
            "Service Tax: $135.20",
            "Total Due Now: $1,825.20",
            "Please remit electronically.",
        ],
    },
    {
        "filename": "juniperlane_work_record.pdf",
        "kind": "other",
        "title": "Work Record",
        "lines": [
            "Vendor: Juniper Lane Plumbing",
            "Record ID: JLP-619",
            "Backflow preventer replaced and tested",
            "Captured cost total: $780.00",
            "Possible tax line for billing office: $62.40",
            "Expected payable figure after invoicing: $842.40",
            "Work record archived. This is not a request for payment.",
        ],
    },
    {
        "filename": "juniperlane_invoice.pdf",
        "kind": "invoice",
        "title": "Invoice",
        "lines": [
            "Vendor: Juniper Lane Plumbing",
            "Invoice Number: JLP-619-INV",
            "Bill To: Alder Ridge Family Clinic",
            "Service subtotal: $780.00",
            "Service Tax: $62.40",
            "Amount Payable: $842.40",
            "Thank you for your business.",
        ],
    },
    {
        "filename": "lakeside_av_closeout.pdf",
        "kind": "other",
        "title": "Job Closeout Summary",
        "lines": [
            "Vendor: Lakeside AV Support",
            "Closeout Ref: LAV-390",
            "Conference-room amplifier restored to service",
            "Cost summary for review: $425.00",
            "Tax planning line: $34.00",
            "Potential billing total: $459.00",
            "Closeout package only. No invoice enclosed.",
        ],
    },
    {
        "filename": "oakbranch_generators_completion_note.jpg",
        "kind": "other",
        "title": "Completion Note",
        "lines": [
            "Vendor: Oakbranch Generator Service",
            "Completion Ref: OGS-208",
            "Preventive maintenance completed on backup generator",
            "Labor and fuel rollup $690.00",
            "Estimated tax line $55.20",
            "Budgeted billing total $745.20",
            "Completion note only - this is not an invoice",
        ],
    },
    {
        "filename": "meadowrun_service_packet.pdf",
        "kind": "other",
        "title": "Service Packet",
        "lines": [
            "Vendor: Meadowrun Refrigeration",
            "Packet: MR-508",
            "Cooler temperature issue resolved",
            "Recorded cost of service: $1,125.00",
            "Estimated tax for accounts team: $90.00",
            "Projected total after billing: $1,215.00",
            "Service packet retained for records. No payment due.",
        ],
    },
    {
        "filename": "meadowrun_invoice.jpg",
        "kind": "invoice",
        "title": "Invoice For Payment",
        "lines": [
            "Vendor: Meadowrun Refrigeration",
            "Invoice Number MR-508-2",
            "Bill To Alder Ridge Family Clinic",
            "Service subtotal $1,125.00",
            "Service Tax $90.00",
            "Final Charges $1,215.00",
            "Payment due within 15 days",
        ],
    },
]


def create_pdf(path: Path, title: str, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    pdf.setTitle(title)
    y = height - 72
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, y, title)
    y -= 28
    pdf.setFont("Helvetica", 11)
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 18
    pdf.showPage()
    pdf.save()


def create_jpg(path: Path, title: str, lines: list[str]) -> None:
    image = Image.new("RGB", (1600, 1200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    y = 80
    draw.text((80, y), title, fill="black", font=font)
    y += 80
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 58
    image.save(path, quality=95)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUTPUT_DIR.iterdir():
        if existing.is_file():
            existing.unlink()

    for document in DOCUMENTS:
        path = OUTPUT_DIR / document["filename"]
        if path.suffix.lower() == ".pdf":
            create_pdf(path, document["title"], document["lines"])
        else:
            create_jpg(path, document["title"], document["lines"])


if __name__ == "__main__":
    main()
