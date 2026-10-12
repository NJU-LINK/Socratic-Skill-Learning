from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("bluepine_facilities.jpg"): ("1344.00", "224.00"),
        opaque_name("nimbus_health_supply.jpg"): ("523.25", "68.25"),
        opaque_name("oakroute_logistics.jpg"): ("2086.40", "347.73"),
        opaque_name("verdant_it_services.jpg"): ("947.80", "157.97"),
        opaque_name("northspur_cleaning.jpg"): ("681.30", "61.30"),
        opaque_name("cedar_printing.jpg"): ("1752.64", "292.11"),
        opaque_name("solace_catering.pdf"): ("486.00", "36.00"),
        opaque_name("marlowe_air_systems.pdf"): ("1289.55", "214.93"),
    }
    expected_other_files = {
        opaque_name("field_team_expense_summary.jpg"),
        opaque_name("payment_memo_q3.jpg"),
        opaque_name("internal_cost_report.jpg"),
        opaque_name("travel_reconciliation.jpg"),
        opaque_name("budget_reallocation.jpg"),
        opaque_name("petty_cash_audit.jpg"),
        opaque_name("warehouse_spend_digest.jpg"),
        opaque_name("vendor_spend_digest.pdf"),
        opaque_name("project_chargeback_note.pdf"),
    }
