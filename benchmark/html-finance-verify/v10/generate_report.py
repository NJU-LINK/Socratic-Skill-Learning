from pathlib import Path


ROWS = [
    (110, "Revenue", 642.8, 598.2),
    (120, "Gross profit", 311.4, 287.0),
    (130, "Research and development", 78.9, 74.1),
    (140, "Sales and marketing", 46.3, 44.4),
    (150, "General and administrative", 18.7, 19.4),
    (160, "Operating income", 167.5, 149.1),
    (170, "Interest expense", 14.2, 16.5),
    (180, "Pre-tax income", 153.3, 132.6),
    (190, "Net income", 121.1, 104.5),
    (200, "Diluted EPS", 2.14, 1.85),
]

WRONG_LINE = 160
WRONG_VALUE = 28.4


def format_number(value: float) -> str:
    text = f"{value:.2f}" if abs(value) < 10 and value != round(value, 1) else f"{value:.1f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def reported_change(line_number: int, current: float, prior: float) -> float:
    if line_number == WRONG_LINE:
        return WRONG_VALUE
    return round(current - prior, 2)


def build_rows() -> str:
    parts = []
    for line_number, label, current, prior in ROWS:
        change = reported_change(line_number, current, prior)
        parts.append(
            "      <tr>"
            f"<td>{line_number}</td>"
            f"<td>{label}</td>"
            f"<td>{format_number(current)}</td>"
            f"<td>{format_number(prior)}</td>"
            f"<td>{format_number(change)}</td>"
            "</tr>"
        )
    return "\n".join(parts)


HTML = f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Arbor Ridge Systems Q2 Earnings Comparison</title>
    <style>
      body {{
        font-family: Arial, Helvetica, sans-serif;
        margin: 32px;
        color: #1f2937;
        background: #f8fafc;
      }}
      main {{
        max-width: 960px;
        margin: 0 auto;
        background: #ffffff;
        border: 1px solid #dbe4ee;
        border-radius: 12px;
        padding: 24px 28px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: 28px;
      }}
      p {{
        margin: 0 0 16px;
        line-height: 1.5;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 18px;
      }}
      th, td {{
        border: 1px solid #cbd5e1;
        padding: 10px 12px;
        text-align: right;
      }}
      th:first-child, td:first-child,
      th:nth-child(2), td:nth-child(2) {{
        text-align: left;
      }}
      thead th {{
        background: #e2e8f0;
        font-weight: 700;
      }}
      tbody tr:nth-child(even) {{
        background: #f8fafc;
      }}
      .note {{
        font-size: 14px;
        color: #475569;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>Arbor Ridge Systems</h1>
      <p>Selected quarterly metrics for the three months ended June 30, 2025 compared with the three months ended June 30, 2024.</p>
      <p class=\"note\">All values are in millions except diluted EPS. The year-over-year change column is presented as current quarter minus prior-year quarter.</p>
      <table>
        <thead>
          <tr><th>Line</th><th>Metric</th><th>Q2 2025</th><th>Q2 2024</th><th>YoY change</th></tr>
        </thead>
        <tbody>
{build_rows()}
        </tbody>
      </table>
    </main>
  </body>
</html>
"""


Path("/app/quarterly-report.html").write_text(HTML, encoding="utf-8")
