import re
from html.parser import HTMLParser
import os
from pathlib import Path


HTML_PATH = Path(os.environ.get("TBENCH_HTML_PATH", "/app/solis_cash_flow_statement.html"))
ANSWER_PATH = Path(os.environ.get("TBENCH_ANSWER_PATH", "/app/answer.txt"))


class CashFlowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "td":
            self.in_td = True
            self.current_cell = []
        elif self.in_tbody and tag == "tr":
            self.current_row = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_tbody = False
        elif self.in_tbody and tag == "td":
            self.in_td = False
            self.current_row.append("".join(self.current_cell).strip())
        elif self.in_tbody and tag == "tr":
            if self.current_row:
                while len(self.current_row) < 3:
                    self.current_row.append("")
                self.rows.append(self.current_row[:3])


def parse_rows():
    parser = CashFlowParser()
    parser.feed(HTML_PATH.read_text(encoding="utf-8"))
    rows = []
    for line, description, amount in parser.rows:
        rows.append(
            {
                "line": line,
                "description": description,
                "amount_text": amount,
                "amount": int(amount) if amount else None,
            }
        )
    return rows


def expected_bad_metric():
    rows = parse_rows()
    by_line = {row["line"]: row for row in rows}

    section_checks = []
    for total_line, detail_lines in {
        "290": ["200", "210", "220", "230"],
        "490": ["400", "410", "420"],
        "590": ["500", "510", "520"],
    }.items():
        detail_sum = sum(by_line[line]["amount"] for line in detail_lines)
        total_amount = by_line[total_line]["amount"]
        section_checks.append((abs(detail_sum - total_amount), total_line, by_line[total_line]["amount_text"]))

    ending_calc = (
        by_line["100"]["amount"]
        + by_line["290"]["amount"]
        + by_line["490"]["amount"]
        + by_line["590"]["amount"]
        + by_line["600"]["amount"]
    )
    section_checks.append((abs(ending_calc - by_line["610"]["amount"]), "610", by_line["610"]["amount_text"]))
    return max(section_checks)[1:]


def read_answer_match():
    content = ANSWER_PATH.read_text(encoding="utf-8")
    match = re.fullmatch(r"\s*(\d+)\s*,\s*(-?\d+)\s*", content)
    assert match, f"unexpected answer format: {content!r}"
    return match


def test_answer_file_has_public_line_and_integer_value_format():
    match = read_answer_match()
    assert match.group(1).isdigit()
    int(match.group(2))


def test_answer_matches_the_largest_non_rounding_reconciliation_failure():
    match = read_answer_match()
    expected_line, expected_amount = expected_bad_metric()
    assert match.group(1) == expected_line
    assert match.group(2) == expected_amount


def test_wrong_rounding_tolerance_does_not_pass():
    rows = parse_rows()
    by_line = {row["line"]: row for row in rows}

    harmless_candidates = []
    operating_sum = sum(by_line[line]["amount"] for line in ["200", "210", "220", "230"])
    investing_sum = sum(by_line[line]["amount"] for line in ["400", "410", "420"])
    if abs(operating_sum - by_line["290"]["amount"]) <= 1:
        harmless_candidates.append(("290", by_line["290"]["amount_text"]))
    if abs(investing_sum - by_line["490"]["amount"]) <= 1:
        harmless_candidates.append(("490", by_line["490"]["amount_text"]))

    actual = tuple(read_answer_match().groups())
    assert actual not in harmless_candidates
