from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("doc01.pdf"): ("88.94", "6.59"),
        opaque_name("doc02.jpg"): ("69.55", "5.15"),
        opaque_name("doc03.pdf"): ("123.90", "9.18"),
        opaque_name("doc04.pdf"): ("64.79", "4.80"),
    }
    expected_other_files = {
        opaque_name("doc05.pdf"),
        opaque_name("doc06.jpg"),
        opaque_name("doc07.pdf"),
        opaque_name("doc08.pdf"),
    }
