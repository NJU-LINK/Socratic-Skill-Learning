import csv
import re
from pathlib import Path


REPORT = Path("/app/annual-report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(r"<tr><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>")


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def revenue_rows() -> list[tuple[str, str, str, int]]:
    rows = []
    for line, label, shown in ROW.findall(REPORT.read_text(encoding="utf-8")):
        rows.append((line, label, shown, int(shown.replace(",", ""))))
    return rows


def subtotal_mismatches() -> list[tuple[str, str]]:
    mismatches = []
    running_total = 0
    for line, label, shown, value in revenue_rows():
        if "subtotal" in label.lower():
            if value != running_total:
                mismatches.append((line, shown.replace(",", "")))
            running_total = 0
        elif label not in {
            "Consumer Markets revenue",
            "Enterprise Platforms revenue",
            "Logistics Systems revenue",
            "Total company revenue",
        }:
            running_total += value
    return mismatches


def test_answer_has_the_public_line_value_format():
    line, value = read_answer()
    assert line.isdigit()
    assert value.isdigit()
    assert "," not in value


def test_answer_matches_the_unique_inconsistent_subtotal():
    assert subtotal_mismatches() == [read_answer()]


def test_company_total_and_segment_summary_are_otherwise_consistent():
    rows = {label: value for _, label, _, value in revenue_rows()}
    assert rows["Total company revenue"] == sum(
        rows[label]
        for label in [
            "Consumer Markets revenue",
            "Enterprise Platforms revenue",
            "Logistics Systems revenue",
        ]
    )


def test_answer_reports_the_displayed_wrong_value_not_the_correction():
    assert read_answer() == ("32", "8200")
