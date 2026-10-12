from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("north_hill_receipt.jpg"): ("220.00", "20.00"),
        opaque_name("harbor_trade_ticket.jpg"): ("74.80", "6.80"),
        opaque_name("citywide_cleaning_statement.pdf"): ("184.80", "16.80"),
    }
    expected_other_files = {
        opaque_name("parking_notice.jpg"),
        opaque_name("supplier_letter.jpg"),
    }
