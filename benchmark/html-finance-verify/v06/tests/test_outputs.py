import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/aurora_q2_earnings_release.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(r"<tr><td>([^<]+)</td><td>([^<]+)</td></tr>")


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def section_rows() -> dict[str, dict[str, tuple[str, Decimal]]]:
    sections: dict[str, dict[str, tuple[str, Decimal]]] = {}
    current = ""
    for line_number, line in enumerate(REPORT.read_text(encoding="utf-8").splitlines(), 1):
        heading = re.search(r"<h2>([^<]+)</h2>", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, {})
        match = ROW.search(line)
        if match and current:
            label, shown = match.groups()
            sections[current][label] = (str(line_number), Decimal(shown.replace(",", "")))
    return sections


def test_answer_has_the_public_source_line_and_precision():
    line, value = read_answer()
    assert line.isdigit()
    assert re.fullmatch(r"-?\d+\.\d{2}", value)


def test_share_reconciliation_is_consistent():
    note = section_rows()["Note 4. Earnings Per Share Reconciliation"]
    basic = note["Weighted-average common shares outstanding, basic"][1]
    awards = note["Effect of dilutive stock awards"][1]
    diluted = note["Weighted-average common shares outstanding, diluted"][1]
    assert basic + awards == diluted


def test_answer_is_the_unique_diluted_eps_inconsistency():
    sections = section_rows()
    summary = sections["Quarter Highlights"]
    note = sections["Note 4. Earnings Per Share Reconciliation"]
    net_income = note["Net income attributable to common shareholders"][1]
    diluted_shares = note["Weighted-average common shares outstanding, diluted"][1]
    line, reported = summary["Diluted earnings per share"]
    expected = (net_income / diluted_shares).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    assert reported != expected
    assert read_answer() == (line, f"{reported:.2f}")


def test_basic_eps_cross_check_is_otherwise_consistent():
    sections = section_rows()
    summary = sections["Quarter Highlights"]
    note = sections["Note 4. Earnings Per Share Reconciliation"]
    net_income = note["Net income attributable to common shareholders"][1]
    basic_shares = note["Weighted-average common shares outstanding, basic"][1]
    expected = (net_income / basic_shares).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert summary["Basic earnings per share"][1] == expected
