from pathlib import Path

import openpyxl


OUTPUT = Path("/app/output.xlsx")


def test_source_table_has_requested_autofilter() -> None:
    assert OUTPUT.exists(), "output.xlsx not found"
    workbook = openpyxl.load_workbook(OUTPUT, data_only=False)
    worksheet = workbook["raw 1"]
    assert worksheet.auto_filter.ref == "A1:C9493"
