from pathlib import Path

import openpyxl


OUTPUT = Path("/app/output.xlsx")
EXPECTED_CURRENCY_FORMAT = '"$"#,##0.00_);[Red]\\("$"#,##0.00\\)'


def test_all_target_cells_use_requested_currency_format() -> None:
    assert OUTPUT.exists(), "output.xlsx not found"
    workbook = openpyxl.load_workbook(OUTPUT, data_only=False)
    worksheet = workbook["Sample Data"]
    mismatches = [
        (cell.coordinate, cell.number_format)
        for row in worksheet["G12:J15"]
        for cell in row
        if cell.number_format != EXPECTED_CURRENCY_FORMAT
    ]
    assert not mismatches, f"Target cells are not in the requested Currency format: {mismatches!r}"
