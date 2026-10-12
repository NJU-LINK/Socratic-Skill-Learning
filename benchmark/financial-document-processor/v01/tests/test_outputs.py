from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("alpine_analytics_billing_statement.pdf"): ("1408.00", "128.00"),
        opaque_name("blueharbor_studio_tax_document.pdf"): ("751.68", "55.68"),
        opaque_name("northfield_supply_remittance_notice.pdf"): ("2646.00", "196.00"),
        opaque_name("orbit_logistics_charge_note.jpg"): ("1058.40", "78.40"),
    }
    expected_other_files = {
        opaque_name("payment_reminder_lumen_partners.pdf"),
        opaque_name("purchase_order_greenline_trade.pdf"),
        opaque_name("receipt_lakeside_cafe.jpg"),
        opaque_name("expense_summary_summit_travel.jpg"),
    }
