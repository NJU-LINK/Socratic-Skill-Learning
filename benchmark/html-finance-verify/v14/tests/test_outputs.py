import csv
import re
from pathlib import Path


REPORT = Path("/app/cash-flow-report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<tr(?: class="([^"]+)")?>\s*'
    r'<td class="line">([^<]+)</td>\s*'
    r"<td>([^<]+)</td>\s*"
    r'<td class="value">([^<]+)</td>',
    re.DOTALL,
)


def amount(text: str) -> int:
    cleaned = text.replace("$", "").replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return int(cleaned)


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def report_rows():
    return [
        {
            "class": row_class,
            "line": line,
            "label": label.strip(),
            "shown": shown,
            "value": amount(shown),
        }
        for row_class, line, label, shown in ROW.findall(REPORT.read_text(encoding="utf-8"))
    ]


def test_answer_has_normalized_accounting_number_format():
    line, value = read_answer()
    assert line.isdigit()
    assert re.fullmatch(r"-?\d+", value)
    assert not any(symbol in value for symbol in ["(", ")", "$", ","])


def test_three_section_subtotals_match_their_detail_rows():
    rows = report_rows()
    by_line = {row["line"]: row for row in rows}
    assert by_line["4143"]["value"] == sum(
        by_line[line]["value"] for line in ["4101", "4108", "4115", "4122", "4129", "4136"]
    )
    assert by_line["4171"]["value"] == sum(
        by_line[line]["value"] for line in ["4150", "4157", "4164"]
    )
    assert by_line["4199"]["value"] == sum(
        by_line[line]["value"] for line in ["4178", "4185", "4192"]
    )


def test_answer_is_the_unique_cross_reconciliation_failure():
    rows = {row["line"]: row for row in report_rows()}
    section_change = sum(rows[line]["value"] for line in ["4143", "4171", "4199"])
    balance_change = rows["4220"]["value"] - rows["4213"]["value"]
    assert section_change == balance_change
    assert rows["4206"]["value"] != section_change
    assert read_answer() == ("4206", str(rows["4206"]["value"]))


def test_answer_reports_the_displayed_wrong_value_not_implied_correction():
    assert read_answer() == ("4206", "6270")
    assert read_answer()[1] != "8000"
