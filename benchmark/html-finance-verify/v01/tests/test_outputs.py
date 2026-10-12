import csv
import re
from pathlib import Path


REPORT = Path("/app/q2_earnings_report.html")
OUTPUT = Path("/app/value.txt")


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    rows = list(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(rows) == 1 and len(rows[0]) == 2
    return rows[0][0].strip(), rows[0][1].strip()


def report_rows() -> dict[str, tuple[str, str]]:
    html = REPORT.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<td class="line">([^<]+)</td>\s*'
        r'<td>([^<]+)</td>\s*'
        r'<td class="num">([^<]+)</td>'
    )
    return {metric: (line, value) for line, metric, value in pattern.findall(html)}


def money(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


def percent(text: str) -> float:
    return float(text.replace("%", "").replace(",", ""))


def test_answer_has_the_public_line_value_format():
    line, value = read_answer()
    assert line.isdigit()
    float(value)
    assert "%" not in value


def test_answer_identifies_the_unique_wrong_kpi():
    rows = report_rows()
    revenue = money(rows["Revenue"][1])
    expected = {
        "Gross margin": round(money(rows["Gross profit"][1]) / revenue * 100, 1),
        "Operating margin": round(money(rows["Operating income"][1]) / revenue * 100, 1),
        "Net margin": round(money(rows["Net income"][1]) / revenue * 100, 1),
    }
    wrong = [
        (rows[metric][0], rows[metric][1].removesuffix("%"))
        for metric, correct in expected.items()
        if percent(rows[metric][1]) != correct
    ]
    assert wrong == [read_answer()]


def test_answer_value_is_the_incorrect_displayed_value_not_the_correction():
    assert read_answer() == ("210", "60.8")

