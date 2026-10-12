from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("northwind_billing_statement.pdf"): ("1188.50", "108.05"),
        opaque_name("maple_tax_receipt.jpg"): ("583.20", "43.20"),
        opaque_name("orbit_settlement_record.pdf"): ("2125.00", "0.00"),
        opaque_name("blueharbor_client_statement.jpg"): ("1026.00", "76.00"),
    }
    expected_other_files = {
        opaque_name("q3_budget_overview.pdf"),
        opaque_name("harbor_payment_reminder.jpg"),
        opaque_name("jetstream_purchase_order.pdf"),
        opaque_name("team_expense_summary.jpg"),
    }
