#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import os

def run():
    import openpyxl
    from docx import Document

    wb = openpyxl.load_workbook("data/company_revenues.xlsx")
    ws = wb.active

    first_revenue = ws.cell(row=2, column=2).value
    last_revenue = ws.cell(row=ws.max_row, column=2).value
    diff = int(first_revenue - last_revenue)

    os.makedirs("data", exist_ok=True)

    with open("data/improvement.txt", "w") as f:
        f.write(str(diff))

    doc = Document()
    doc.add_paragraph(f"Revenue difference between first and last year: {diff}")
    doc.save("data/reports.docx")


if __name__ == "__main__":
    run()
PYEOF
