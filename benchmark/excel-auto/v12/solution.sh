#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import os

def run():
    from icalendar import Calendar
    import openpyxl
    from reportlab.pdfgen import canvas

    events = {}
    for name in ['Tom', 'Bob']:
        events[name] = {}
        cal = Calendar.from_ical(open(f'data/calendar/{name}.ics', 'rb').read())
        for component in cal.walk():
            if component.name == 'VEVENT':
                summary = str(component.get('summary')).lower().strip()
                if 'class' in summary:
                    cat = 'class'
                elif 'sleep' in summary:
                    cat = 'sleep'
                elif 'nap' in summary:
                    cat = 'nap'
                elif 'dinner' in summary:
                    cat = 'dinner'
                elif 'lunch' in summary:
                    cat = 'lunch'
                else:
                    cat = summary
                events[name][cat] = events[name].get(cat, 0) + 1

    os.makedirs('data', exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(1, 1, 'Person')
    ws.cell(1, 2, 'Event Type')
    ws.cell(1, 3, 'Count')
    row = 2
    for person in ['Tom', 'Bob']:
        for etype, count in sorted(events[person].items()):
            ws.cell(row, 1, person)
            ws.cell(row, 2, etype)
            ws.cell(row, 3, count)
            row += 1
    wb.save('data/events.xlsx')

    c = canvas.Canvas('data/daily_event.pdf')
    c.drawString(100, 750, 'Daily Event Summary')
    y = 720
    for person in ['Tom', 'Bob']:
        c.drawString(100, y, f'{person}:')
        y -= 20
        for etype, count in sorted(events[person].items()):
            c.drawString(120, y, f'{etype}: {count}')
            y -= 20
        y -= 10
    c.save()

if __name__ == '__main__':
    run()
PYEOF
python3 /app/solve.py
