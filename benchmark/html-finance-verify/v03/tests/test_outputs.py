import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/earnings-reconciliation.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<td class="line">([^<]+)</td>\s*<td>(.*?)</td>\s*'
    r'<td class="value">([^<]+)</td>',
    re.DOTALL,
)


def number(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return -Decimal(cleaned[1:-1])
    return Decimal(cleaned)


def display_number(text: str) -> str:
    cleaned = text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return f"-{cleaned[1:-1]}"
    return cleaned


def report_rows() -> dict[str, tuple[str, str, Decimal]]:
    rows = {}
    for line, raw_label, shown in ROW.findall(REPORT.read_text(encoding="utf-8")):
        label = re.sub(r"<[^>]+>", "", raw_label)
        rows[" ".join(label.split())] = (line, shown, number(shown))
    return rows


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def test_answer_preserves_public_line_and_decimal_format():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value)
    assert "(" not in value and ")" not in value


def test_income_reconciliation_is_consistent():
    rows = report_rows()
    reconciled = (
        rows["GAAP net income (loss)"][2]
        + rows["Restructuring charges"][2]
        + rows["Acquisition and integration costs"][2]
        + rows["Tax effect of non-GAAP adjustments"][2]
    )
    assert reconciled == rows["Adjusted net income (loss)"][2]


def test_answer_is_the_unique_per_share_inconsistency():
    rows = report_rows()
    adjusted = rows["Adjusted net income (loss)"][2]
    shares = rows["Diluted weighted-average shares outstanding (millions)"][2]
    line, shown, reported = rows["Adjusted diluted earnings (loss) per share"]
    expected = (adjusted / shares).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert reported != expected
    assert read_answer() == (line, display_number(shown))


def test_answer_reports_the_displayed_value_not_the_recomputed_value():
    assert read_answer() == ("154", "-1.42")
