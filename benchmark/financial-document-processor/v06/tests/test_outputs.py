from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("north_harbor_billing_document.pdf"): ("1232.00", "112.00"),
        opaque_name("cedar_field_tax_invoice.jpg"): ("957.00", "87.00"),
        opaque_name("foothill_client_billing.pdf"): ("2520.00", "120.00"),
    }
    expected_other_files = {
        opaque_name("atlas_account_statement.pdf"),
        opaque_name("brio_proforma_quote.jpg"),
        opaque_name("luma_purchase_order.pdf"),
        opaque_name("marlow_expense_summary.jpg"),
        opaque_name("summit_monthly_statement.jpg"),
    }
