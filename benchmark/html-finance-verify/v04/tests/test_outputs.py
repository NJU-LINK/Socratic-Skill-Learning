import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/quarterly-bridge.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r"<tr><td>([^<]+)</td><td>([^<]+)</td>"
    r"<td>([^<]+)</td><td>([^<]+)</td></tr>"
)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def decimal(text: str) -> Decimal:
    match = NUMBER.search(text.replace(",", ""))
    assert match
    return Decimal(match.group())


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def expected_answer() -> tuple[str, str]:
    mismatches = []
    for line_number, line in enumerate(REPORT.read_text(encoding="utf-8").splitlines(), 1):
        match = ROW.search(line)
        if not match:
            continue
        _, current_text, prior_text, reported_text = match.groups()
        current = decimal(current_text)
        prior = decimal(prior_text)
        reported = decimal(reported_text)
        actual = ((current - prior) / prior * Decimal("100")).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_UP,
        )
        if actual != reported:
            mismatches.append((str(line_number), str(reported)))
    assert len(mismatches) == 1
    return mismatches[0]


def test_answer_has_exactly_two_fields():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value)


def test_answer_matches_the_only_inconsistent_yoy_row():
    assert read_answer() == expected_answer()


def test_answer_reports_the_shown_wrong_value():
    assert read_answer() == ("36", "18.0")

