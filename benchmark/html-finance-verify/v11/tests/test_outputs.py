import re
from decimal import Decimal
from pathlib import Path


REPORT = Path("/app/aurora_q2_earnings.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r"<tr>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*"
    r'<td class="num">([^<]+)</td>\s*</tr>',
    re.DOTALL,
)


def number(text: str) -> Decimal:
    return Decimal(text.replace(",", "").strip())


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    line, value = OUTPUT.read_text(encoding="utf-8").strip().split(",", 1)
    return line.strip(), value.strip()


def report_rows():
    rows = ROW.findall(REPORT.read_text(encoding="utf-8"))
    main = {label.split(" (", 1)[0]: number(value) for line, label, value in rows if line.startswith("1")}
    notes = [(line, label, value) for line, label, value in rows if line.startswith("2")]
    return main, notes


def mismatches() -> list[tuple[str, str]]:
    main, notes = report_rows()
    wrong = []
    for line, label, shown in notes:
        metric = label.split(" (", 1)[0]
        expected = (
            main["Diluted earnings per share"]
            if "per share" in label.lower()
            else main[metric] * Decimal("1000000")
        )
        if number(shown) != expected:
            wrong.append((line, shown))
    return wrong


def test_answer_preserves_the_displayed_report_line_and_numeric_format():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value.replace(",", ""))
    assert value.count(".") == 1


def test_answer_matches_the_unique_million_to_dollar_conversion_failure():
    assert mismatches() == [read_answer()]


def test_main_summary_is_internally_consistent():
    main, _ = report_rows()
    assert main["Gross profit"] == main["Revenue"] - main["Cost of revenue"]
    assert main["Diluted earnings per share"].quantize(Decimal("0.01")) == (
        main["Net income"] / main["Diluted weighted average shares"]
    ).quantize(Decimal("0.01"))


def test_answer_preserves_commas_and_decimal_places_from_report():
    assert read_answer() == ("210", "6,412,500.00")
