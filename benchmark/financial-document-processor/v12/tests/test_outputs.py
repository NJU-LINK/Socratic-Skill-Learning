from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("apex-window-cleaning.pdf"): ("1814.40", "134.40"),
        opaque_name("blue-cable-it.pdf"): ("993.60", "73.60"),
        opaque_name("cedar-maintenance.pdf"): ("583.20", "43.20"),
        opaque_name("lighthouse-locksmith.jpg"): ("297.00", "22.00"),
    }
    expected_other_files = {
        opaque_name("packing-slip-north.pdf"),
        opaque_name("purchase-order-studio.jpg"),
        opaque_name("reminder-riverside.pdf"),
    }
