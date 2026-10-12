import csv
import re
from pathlib import Path


REPORT = Path("/app/aurora-q2-report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<td class="line">([^<]+)</td>\s*'
    r'<td>([^<]+)</td>\s*'
    r'<td class="num">([^<]+)</td>'
)


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def report_rows() -> dict[str, tuple[str, str, float]]:
    return {
        metric: (line, shown, float(shown.replace(",", "")))
        for line, metric, shown in ROW.findall(REPORT.read_text(encoding="utf-8"))
    }


def test_answer_has_the_public_line_value_shape():
    line, value = read_answer()
    assert line.isdigit()
    float(value)


def test_answer_is_the_only_reconciliation_failure_beyond_tolerance():
    rows = report_rows()
    segment_sum = round(
        sum(
            rows[name][2]
            for name in [
                "Automation Platforms",
                "Smart Infrastructure",
                "Lifecycle Services",
            ]
        ),
        1,
    )
    mismatches = [
        (rows[name][0], rows[name][1])
        for name in ["Consolidated revenue", "Segment revenue total"]
        if abs(rows[name][2] - segment_sum) > 0.1
    ]
    assert mismatches == [read_answer()]


def test_answer_reports_the_incorrect_displayed_total():
    assert read_answer() == ("217", "84.7")
