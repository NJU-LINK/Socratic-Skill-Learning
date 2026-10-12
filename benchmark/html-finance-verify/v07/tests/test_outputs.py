import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/segment_report.html")
OUTPUT = Path("/app/value.txt")
SEGMENT_ROW = re.compile(
    r"<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*"
    r"<td>([^<]+)</td>\s*</tr>",
    re.DOTALL,
)
SNAPSHOT_ROW = re.compile(
    r"<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*</tr>",
    re.DOTALL,
)


def number(text: str) -> Decimal:
    return Decimal(text.replace(",", "").replace("%", "").strip())


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    line, value = OUTPUT.read_text(encoding="utf-8").strip().split(",", 1)
    return line.strip(), value.strip()


def expected_answer() -> tuple[str, str]:
    text = REPORT.read_text(encoding="utf-8")
    segment_text = text.split("Section A: Segment performance", 1)[1].split(
        "Section B: Consolidated snapshot",
        1,
    )[0]
    segments = SEGMENT_ROW.findall(segment_text)
    revenue = sum((number(row[1]) for row in segments), Decimal("0"))
    income = sum((number(row[2]) for row in segments), Decimal("0"))

    snapshot_text = text.split("Section B: Consolidated snapshot", 1)[1]
    shown = {label.strip(): value.strip() for label, value in SNAPSHOT_ROW.findall(snapshot_text)}
    expected = {
        "Consolidated revenue": revenue,
        "Adjusted operating income": income,
        "Operating margin": (income / revenue * Decimal("100")).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_UP,
        ),
    }
    mismatches = [label for label, value in shown.items() if number(value) != expected[label]]
    assert len(mismatches) == 1

    label = mismatches[0]
    lines = text.splitlines()
    label_index = next(i for i, line in enumerate(lines) if label in line)
    shown_value = shown[label]
    value_index = next(
        i
        for i in range(label_index + 1, min(label_index + 5, len(lines)))
        if shown_value in lines[i]
    )
    return str(value_index + 1), shown_value.replace(",", "").replace("%", "")


def test_answer_has_the_public_source_line_and_number_shape():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value)
    assert "," not in value and "%" not in value


def test_answer_matches_the_unique_segment_reconciliation_failure():
    assert read_answer() == expected_answer()


def test_answer_reports_the_displayed_wrong_value():
    assert read_answer() == ("65", "6511000")
