from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("harbor_billing_statement.pdf"): ("1595.00", "145.00"),
        opaque_name("lighthouse_account_summary.pdf"): ("907.20", "67.20"),
        opaque_name("spruce_service_record.pdf"): ("485.00", "0.00"),
    }
    expected_other_files = {
        opaque_name("autumn_quote_request.jpg"),
        opaque_name("northshore_account_memo.jpg"),
    }
