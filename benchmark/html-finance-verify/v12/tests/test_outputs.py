import csv
import re
from pathlib import Path


REPORT = Path("/app/report.html")
OUTPUT = Path("/app/value.txt")
ROW = re.compile(
    r'<tr><td class="line">([^<]+)</td><td>([^<]+)</td>'
    r'<td class="num">([^<]+)</td></tr>'
)


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    row = next(csv.reader([OUTPUT.read_text(encoding="utf-8").strip()]))
    assert len(row) == 2
    return row[0].strip(), row[1].strip()


def amount(text: str) -> float:
    cleaned = re.sub(
        r"\b(million|shares|outstanding|per|net income|common stockholders)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    negative = "(" in cleaned and ")" in cleaned
    value = float(
        cleaned.replace("$", "")
        .replace(",", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )
    return -value if negative else value


def test_answer_has_two_decimal_places():
    line, value = read_answer()
    assert line.isdigit()
    assert re.fullmatch(r"-?\d+\.\d{2}", value)


def test_answer_identifies_the_unique_eps_cross_check_failure():
    rows = {
        metric: (line, shown, amount(shown))
        for line, metric, shown in ROW.findall(REPORT.read_text(encoding="utf-8"))
    }
    net_income = rows["Net income available to common stockholders"][2]
    candidates = []
    for label, shares_label in [
        ("Basic net income per share", "Basic weighted average shares outstanding"),
        ("Diluted net income per share", "Diluted weighted average shares outstanding"),
    ]:
        expected = round(net_income / rows[shares_label][2] + 1e-12, 2)
        line, shown, value = rows[label]
        if abs(value - expected) > 0.005:
            candidates.append((line, f"{value:.2f}"))
    assert candidates == [read_answer()]


def test_answer_reports_the_wrong_diluted_eps_value():
    assert read_answer() == ("135", "1.24")

