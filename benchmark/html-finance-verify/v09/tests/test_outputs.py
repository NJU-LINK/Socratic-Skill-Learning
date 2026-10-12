import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT = Path("/app/q3_margin_report.html")
OUTPUT = Path("/app/value.txt")
FINANCIAL_ROW = re.compile(
    r"<tr>\s*<td>[^<]+</td>\s*<td>([^<]+)</td>\s*"
    r'<td class="num">([^<]+)</td>\s*</tr>',
    re.DOTALL,
)
KPI = re.compile(
    r'<span class="kpi-label"><span class="line">([^<]+)</span>'
    r'([^<]+)</span>\s*<div class="kpi-value">([^<]+)</div>',
    re.DOTALL,
)


def number(text: str) -> Decimal:
    return Decimal(text.replace(",", "").replace("%", "").strip())


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    line, value = OUTPUT.read_text(encoding="utf-8").strip().split(",", 1)
    return line.strip(), value.strip()


def expected_answer() -> tuple[str, str]:
    html = REPORT.read_text(encoding="utf-8")
    financials = {label: number(value) for label, value in FINANCIAL_ROW.findall(html)}
    revenue = financials["Revenue"]
    expected = {
        "Gross margin": (financials["Gross profit"] / revenue * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ),
        "Operating margin": (financials["Operating income"] / revenue * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ),
        "Net margin": (financials["Net income"] / revenue * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ),
    }
    mismatches = [
        (line.strip(), shown.removesuffix("%"))
        for line, label, shown in KPI.findall(html)
        if number(shown) != expected[label.strip()]
    ]
    assert len(mismatches) == 1
    return mismatches[0]


def test_answer_has_the_public_line_and_percentage_number_shape():
    line, value = read_answer()
    assert line.isdigit()
    Decimal(value)
    assert "%" not in value


def test_answer_matches_the_unique_incorrect_margin():
    assert read_answer() == expected_answer()


def test_underlying_income_statement_is_internally_consistent():
    financials = {
        label: number(value)
        for label, value in FINANCIAL_ROW.findall(REPORT.read_text(encoding="utf-8"))
    }
    assert financials["Gross profit"] == financials["Revenue"] - financials["Cost of revenue"]
    assert financials["Total operating expenses"] == sum(
        financials[label]
        for label in [
            "Research and development",
            "Sales and marketing",
            "General and administrative",
        ]
    )
    assert financials["Operating income"] == (
        financials["Gross profit"] - financials["Total operating expenses"]
    )
