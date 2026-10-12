import csv
import re
from decimal import Decimal
from pathlib import Path


REPORT = Path("/app/earnings-report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<td class="line">([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*'
    r'<td class="value">([^<]+)</td>',
    re.DOTALL,
)


def rows() -> dict[str, tuple[str, str, Decimal]]:
    return {
        line: (label.strip(), shown, Decimal(shown))
        for line, label, shown in ROW.findall(REPORT.read_text(encoding="utf-8"))
    }


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def mismatches() -> list[tuple[str, str]]:
    values = rows()
    equations = [
        ("5240", ["5210", "5220", "5230"], 1),
        ("5290", ["5260", "5270", "5280"], 1),
        ("5300", ["5240", "5290"], -1),
        ("5350", ["5320", "5330", "5340"], 1),
        ("5360", ["5300", "5350"], -1),
        ("5400", ["5360", "5380", "5390"], 1),
        ("5420", ["5400", "5410"], -1),
    ]
    wrong = []
    for target, inputs, operation in equations:
        expected = (
            sum((values[line][2] for line in inputs), Decimal("0"))
            if operation == 1
            else values[inputs[0]][2] - values[inputs[1]][2]
        )
        if values[target][2] != expected:
            wrong.append((target, values[target][1]))
    return wrong


def test_answer_has_the_public_line_value_shape():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value)


def test_answer_matches_the_unique_inconsistent_subtotal():
    assert mismatches() == [read_answer()]


def test_answer_reports_the_displayed_value_not_the_correction():
    assert read_answer() == ("5360", "448.1")
