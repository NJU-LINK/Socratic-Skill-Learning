from html.parser import HTMLParser
from pathlib import Path


REPORT = Path("/app/quarterly-report.html")
OUTPUT = Path("/app/value.txt")


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_body = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self.in_body = True
        elif self.in_body and tag == "tr":
            self.row = []
        elif self.in_body and tag == "td":
            self.in_cell = True
            self.cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.in_cell:
            self.row.append("".join(self.cell).strip())
            self.in_cell = False
        elif tag == "tr" and self.in_body and self.row:
            self.rows.append(self.row)
        elif tag == "tbody":
            self.in_body = False


def read_answer() -> tuple[str, str]:
    assert OUTPUT.is_file(), "Missing /app/value.txt"
    line, value = OUTPUT.read_text(encoding="utf-8").strip().split(",", 1)
    return line.strip(), value.strip()


def mismatch_rows() -> list[tuple[str, str, str]]:
    parser = TableParser()
    parser.feed(REPORT.read_text(encoding="utf-8"))
    mismatches = []
    for line, _label, current, prior, shown in parser.rows:
        expected = round(float(current.replace(",", "")) - float(prior.replace(",", "")), 2)
        if float(shown.replace(",", "")) != expected:
            canonical = f"{expected:.2f}".rstrip("0").rstrip(".")
            mismatches.append((line, shown, canonical))
    return mismatches


def test_generated_report_is_present_without_answer_bearing_generator():
    assert REPORT.is_file()
    assert not Path("/app/generate_report.py").exists()


def test_answer_has_the_public_report_line_and_numeric_shape():
    line, value = read_answer()
    assert line.isdigit()
    float(value)


def test_answer_matches_the_unique_incorrect_yoy_change():
    mismatches = mismatch_rows()
    assert len(mismatches) == 1
    line, shown, _correct = mismatches[0]
    assert read_answer() == (line, shown)


def test_answer_reports_the_displayed_value_not_the_recomputed_change():
    line, shown, correct = mismatch_rows()[0]
    assert read_answer() == (line, shown)
    assert shown != correct
