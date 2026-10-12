import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/cashflow_review.html")
OUTPUT = Path("/app/answer.txt")
ROW = re.compile(r'<tr><td>([^<]+)</td><td class="num">([^<]+)</td></tr>')


def number(text: str) -> Decimal:
    return Decimal(text.replace(",", "").removesuffix("%").strip())


def report_metrics() -> dict[str, tuple[str, str, Decimal]]:
    metrics = {}
    for line_number, line in enumerate(REPORT.read_text(encoding="utf-8").splitlines(), 1):
        match = ROW.search(line)
        if match:
            label, shown = match.groups()
            metrics[label] = (str(line_number), shown, number(shown))
    return metrics


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/answer.txt"
    line, value = OUTPUT.read_text(encoding="utf-8").strip().split(",", 1)
    return line.strip(), value.strip()


def mismatches() -> list[tuple[str, str]]:
    m = report_metrics()
    operating = m["Net cash provided by operating activities"][2]
    capex = m["Capital expenditures"][2]
    shares = m["Weighted-average diluted shares outstanding (millions)"][2]
    expected = {
        "Net cash used in investing activities": (
            m["Capital expenditures"][2]
            + m["Acquisitions, net of cash acquired"][2]
            - m["Proceeds from asset disposals"][2]
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "Net cash used in financing activities": (
            m["Repurchases of common stock"][2]
            + m["Cash dividends paid"][2]
            - m["Net borrowings"][2]
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "Free cash flow": (operating - capex).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ),
        "Free cash flow per diluted share": (
            m["Free cash flow"][2] / shares
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "Capital expenditures as a percentage of operating cash flow": (
            capex / operating * Decimal("100")
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    }
    return [
        (m[label][0], m[label][1].removesuffix("%"))
        for label, correct in expected.items()
        if m[label][2] != correct
    ]


def test_answer_has_the_public_source_line_and_displayed_number_shape():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value.replace(",", ""))
    assert "%" not in value


def test_answer_matches_the_unique_cash_flow_cross_check_failure():
    assert mismatches() == [read_answer()]


def test_investing_financing_and_free_cash_flow_totals_are_consistent():
    assert len(mismatches()) == 1
    assert mismatches()[0][0] == report_metrics()["Free cash flow per diluted share"][0]


def test_answer_reports_the_displayed_wrong_per_share_value():
    assert read_answer() == ("53", "4.30")
