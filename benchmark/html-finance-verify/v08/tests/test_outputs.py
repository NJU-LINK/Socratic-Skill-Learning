import re
from pathlib import Path


REPORT = Path("/app/earnings-report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<tr><td class="line">([^<]+)</td><td>([^<]+)</td>'
    r'<td class="value">([^<]+)</td></tr>'
)


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    text = OUTPUT.read_text(encoding="utf-8").strip()
    assert "," in text
    line, value = text.split(",", 1)
    return line.strip(), value.strip()


def report_rows() -> dict[str, tuple[str, str, int]]:
    return {
        metric: (line, shown, int(shown.replace(",", "")))
        for line, metric, shown in ROW.findall(REPORT.read_text(encoding="utf-8"))
    }


def test_answer_has_the_public_line_value_shape():
    line, value = read_answer()
    assert line.isdigit()
    int(value.replace(",", ""))


def test_answer_identifies_the_incorrect_operating_expense_subtotal():
    rows = report_rows()
    expected = sum(
        rows[metric][2]
        for metric in [
            "Research and development",
            "Sales and marketing",
            "General and administrative",
        ]
    )
    shown = rows["Total operating expenses"]
    assert shown[2] != expected
    assert read_answer() == (shown[0], shown[1])


def test_answer_preserves_the_displayed_thousands_separator():
    assert read_answer() == ("107", "1,845")
