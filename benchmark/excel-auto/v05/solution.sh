#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
def run():
    import openpyxl
    from docx import Document
    from reportlab.pdfgen import canvas
    import os
    from statistics import mean

    wb = openpyxl.load_workbook('data/score.xlsx')
    ws = wb.active

    mid1_scores = []
    mid2_scores = []
    improved = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        m1, m2 = row[1], row[2]
        mid1_scores.append(m1)
        mid2_scores.append(m2)
        if m2 > m1:
            improved += 1

    avg1 = mean(mid1_scores)
    avg2 = mean(mid2_scores)
    pass1 = sum(1 for s in mid1_scores if s >= 60)
    pass2 = sum(1 for s in mid2_scores if s >= 60)
    pass_rate1 = pass1 / len(mid1_scores) * 100
    pass_rate2 = pass2 / len(mid2_scores) * 100

    os.makedirs('data', exist_ok=True)

    doc = Document()
    doc.add_heading('Teaching Report', level=1)
    doc.add_paragraph(f'Total students: {len(mid1_scores)}')
    doc.add_paragraph(f'Average of midterm1: {avg1:.2f}')
    doc.add_paragraph(f'Average of midterm2: {avg2:.2f}')
    doc.add_paragraph(f'Pass rate midterm1: {pass_rate1:.1f}%')
    doc.add_paragraph(f'Pass rate midterm2: {pass_rate2:.1f}%')
    doc.add_paragraph(f'Students who improved: {improved}')
    doc.save('data/teaching.docx')

    c = canvas.Canvas('data/teaching.pdf')
    c.drawString(100, 770, 'Teaching Report')
    c.drawString(100, 750, f'Total students: {len(mid1_scores)}')
    c.drawString(100, 730, f'Average of midterm1: {avg1:.2f}')
    c.drawString(100, 710, f'Average of midterm2: {avg2:.2f}')
    c.drawString(100, 690, f'Pass rate midterm1: {pass_rate1:.1f}%')
    c.drawString(100, 670, f'Pass rate midterm2: {pass_rate2:.1f}%')
    c.drawString(100, 650, f'Students who improved: {improved}')
    c.save()


if __name__ == '__main__':
    run()
PYEOF
