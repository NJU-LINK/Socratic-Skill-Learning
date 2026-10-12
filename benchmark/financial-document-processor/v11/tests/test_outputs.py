from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("north_harbor_service_record.pdf"): ("2475.00", "225.00"),
        opaque_name("lattice_cloud_billing_note.jpg"): ("918.00", "68.00"),
        opaque_name("elm_street_maintenance_sheet.pdf"): ("700.00", "70.00"),
        opaque_name("solstice_design_fee_notice.jpg"): ("1408.00", "128.00"),
    }
    expected_other_files = {
        opaque_name("atlas_budget_projection.pdf"),
        opaque_name("greenline_purchase_request.jpg"),
        opaque_name("cedar_account_memo.pdf"),
        opaque_name("riverside_team_expense_sheet.jpg"),
    }
