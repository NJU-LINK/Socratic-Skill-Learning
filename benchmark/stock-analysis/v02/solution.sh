#!/bin/bash
set -e

python3 << 'PYEOF'
import csv, os

data_file = None
for f in sorted(os.listdir("/app")):
    if not f.endswith(".csv"):
        continue
    fp = os.path.join("/app", f)
    content = open(fp).read()
    if "Date,Open,High,Low,Close,Volume" in content:
        # Verify it has enough rows (120+)
        row_count = len([l for l in content.splitlines() if l.strip() and not l.startswith("Date")])
        if row_count > 100:
            data_file = fp
            break

if not data_file:
    print("ERROR: Could not find stock data file")
    exit(1)

print(f"Found: {data_file}")
rows = []
with open(data_file) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

with open("/app/results.csv", "w") as f:
    f.write("date,close,sma5,sma10\n")
    for i, r in enumerate(rows):
        close = float(r["Close"])
        s5 = sum(float(rows[j]["Close"]) for j in range(i-4, i+1)) / 5 if i >= 4 else None
        s10 = sum(float(rows[j]["Close"]) for j in range(i-9, i+1)) / 10 if i >= 9 else None
        out = f"{r['Date']},{close:.2f}"
        out += f",{s5:.2f}" if s5 is not None else ",N/A"
        out += f",{s10:.2f}" if s10 is not None else ",N/A"
        f.write(out + "\n")

print("Done")
PYEOF
