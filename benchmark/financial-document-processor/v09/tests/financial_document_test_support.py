from __future__ import annotations

import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path


DOCUMENTS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"
SUMMARY_COLUMNS = ["filename", "total_amount", "vat_amount"]
OPAQUE_NAME_SALT = "financial-document-processor-v2"


def opaque_name(original_name: str, salt: str = OPAQUE_NAME_SALT) -> str:
    original = Path(original_name)
    digest = hashlib.sha256(
        f"{salt}\0{original.name}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{digest}{original.suffix.lower()}"


def money(value: str) -> Decimal:
    cleaned = (value or "").strip().replace(",", "").replace("$", "")
    if cleaned == "":
        return Decimal("0.00")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise AssertionError(f"not a valid decimal amount: {value!r}") from error


def invoice_files() -> dict[str, Path]:
    assert INVOICES_DIR.is_dir(), "missing /app/invoices"
    return {
        path.name: path
        for path in INVOICES_DIR.iterdir()
        if path.is_file() and path.name != "summary.csv"
    }


def other_files() -> dict[str, Path]:
    assert OTHER_DIR.is_dir(), "missing /app/other"
    return {path.name: path for path in OTHER_DIR.iterdir() if path.is_file()}


def summary_rows() -> list[dict[str, str]]:
    assert SUMMARY_PATH.is_file(), "missing /app/invoices/summary.csv"
    with SUMMARY_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == SUMMARY_COLUMNS
        rows = list(reader)
    assert rows, "summary.csv must contain invoice rows and a final total row"
    return rows


def assert_output_directories_and_drained_input() -> None:
    assert DOCUMENTS_DIR.is_dir(), "missing /app/documents"
    assert not any(DOCUMENTS_DIR.iterdir()), "/app/documents must be empty"
    assert INVOICES_DIR.is_dir()
    assert OTHER_DIR.is_dir()


def assert_invoice_routing(expected_invoice_rows: dict[str, tuple[str, str]]) -> None:
    assert set(invoice_files()) == set(expected_invoice_rows)


def assert_other_routing(expected_other_files: set[str]) -> None:
    assert set(other_files()) == expected_other_files


def assert_moved_files_are_preserved() -> None:
    moved = [*invoice_files().values(), *other_files().values()]
    assert moved, "no documents were routed"
    assert all(path.stat().st_size > 0 for path in moved)
    assert all(path.suffix.lower() in {".pdf", ".jpg", ".jpeg"} for path in moved)
    assert len({path.name for path in moved}) == len(moved)


def assert_summary_covers_invoice_files(
    expected_invoice_rows: dict[str, tuple[str, str]],
) -> None:
    rows = summary_rows()
    assert len(rows) == len(expected_invoice_rows) + 1
    assert rows[-1]["filename"] == "total"
    detail_rows = rows[:-1]
    names = [row["filename"] for row in detail_rows]
    assert len(names) == len(set(names)), "duplicate invoice row in summary.csv"
    assert set(names) == set(invoice_files()) == set(expected_invoice_rows)


def assert_invoice_amounts(
    expected_invoice_rows: dict[str, tuple[str, str]],
) -> None:
    observed = {
        row["filename"]: (money(row["total_amount"]), money(row["vat_amount"]))
        for row in summary_rows()[:-1]
    }
    expected = {
        filename: (money(total_amount), money(vat_amount))
        for filename, (total_amount, vat_amount) in expected_invoice_rows.items()
    }
    assert observed == expected


def assert_total_row(
    expected_invoice_rows: dict[str, tuple[str, str]],
) -> None:
    rows = summary_rows()
    total_rows = [row for row in rows if row["filename"] == "total"]
    assert len(total_rows) == 1
    assert rows[-1] is total_rows[0]

    expected_total = sum(
        (money(values[0]) for values in expected_invoice_rows.values()),
        Decimal("0.00"),
    )
    expected_vat = sum(
        (money(values[1]) for values in expected_invoice_rows.values()),
        Decimal("0.00"),
    )
    assert money(total_rows[0]["total_amount"]) == expected_total
    assert money(total_rows[0]["vat_amount"]) == expected_vat


class FinancialDocumentContract:
    expected_invoice_rows: dict[str, tuple[str, str]]
    expected_other_files: set[str]

    def test_output_directories_exist_and_input_is_drained(self) -> None:
        assert_output_directories_and_drained_input()

    def test_every_invoice_is_routed_without_renaming(self) -> None:
        assert_invoice_routing(self.expected_invoice_rows)

    def test_every_non_invoice_is_routed_without_renaming(self) -> None:
        assert_other_routing(self.expected_other_files)

    def test_moved_document_artifacts_are_preserved(self) -> None:
        assert_moved_files_are_preserved()

    def test_summary_schema_and_invoice_coverage(self) -> None:
        assert_summary_covers_invoice_files(self.expected_invoice_rows)

    def test_each_invoice_has_the_correct_total_and_tax(self) -> None:
        assert_invoice_amounts(self.expected_invoice_rows)

    def test_final_row_equals_the_invoice_column_sums(self) -> None:
        assert_total_row(self.expected_invoice_rows)
