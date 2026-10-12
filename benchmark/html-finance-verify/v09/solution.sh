#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import os
from html.parser import HTMLParser


APP_DIR = os.environ.get("APP_DIR", "/app")
HTML_PATH = f"{APP_DIR}/q3_margin_report.html"
OUTPUT_PATH = f"{APP_DIR}/value.txt"


def parse_number(text: str) -> float:
    return float(text.replace(",", "").replace("%", "").strip())


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_tds = []
        self.current_td = []
        self.in_kpi = False
        self.in_kpi_label = False
        self.in_line = False
        self.in_kpi_value = False
        self.current_line = []
        self.current_label = []
        self.current_value = []
        self.financials = {}
        self.margins = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        class_names = set(attr_map.get("class", "").split())
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_tds = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_td = []
        elif tag == "div" and "kpi" in class_names:
            self.in_kpi = True
            self.current_line = []
            self.current_label = []
            self.current_value = []
        elif tag == "span" and self.in_kpi and "kpi-label" in class_names:
            self.in_kpi_label = True
        elif tag == "span" and self.in_kpi_label and "line" in class_names:
            self.in_line = True
        elif tag == "div" and self.in_kpi and "kpi-value" in class_names:
            self.in_kpi_value = True

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_tbody = False
        elif tag == "td" and self.in_td:
            self.in_td = False
            self.current_tds.append("".join(self.current_td).strip())
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if len(self.current_tds) == 3:
                _, metric, value = self.current_tds
                self.financials[metric] = parse_number(value)
        elif tag == "span" and self.in_line:
            self.in_line = False
        elif tag == "span" and self.in_kpi_label:
            self.in_kpi_label = False
        elif tag == "div" and self.in_kpi_value:
            self.in_kpi_value = False
        elif tag == "div" and self.in_kpi:
            self.in_kpi = False
            self.margins.append(
                {
                    "line": "".join(self.current_line).strip(),
                    "label": "".join(self.current_label).strip(),
                    "value": parse_number("".join(self.current_value).strip()),
                }
            )

    def handle_data(self, data):
        if self.in_td:
            self.current_td.append(data)
        if self.in_line:
            self.current_line.append(data)
        elif self.in_kpi_label:
            self.current_label.append(data)
        elif self.in_kpi_value:
            self.current_value.append(data)


with open(HTML_PATH, "r", encoding="utf-8") as handle:
    html = handle.read()

parser = ReportParser()
parser.feed(html)

revenue = parser.financials["Revenue"]
expected_margins = {
    "Gross margin": round(parser.financials["Gross profit"] / revenue * 100, 1),
    "Operating margin": round(parser.financials["Operating income"] / revenue * 100, 1),
    "Net margin": round(parser.financials["Net income"] / revenue * 100, 1),
}

for item in parser.margins:
    expected = expected_margins[item["label"]]
    if abs(item["value"] - expected) > 0.05:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
            handle.write(f'{item["line"]},{item["value"]}')
        break
else:
    raise SystemExit("No incorrect margin found")
PY
