from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("north_harbor_invoice_a.jpg"): ("1944.54", "144.04"),
        opaque_name("north_harbor_invoice_b.pdf"): ("2991.60", "221.60"),
        opaque_name("bluefern_invoice_scan.jpg"): ("4962.60", "367.60"),
        opaque_name("bluefern_invoice_letter.pdf"): ("1512.00", "112.00"),
        opaque_name("copperleaf_invoice_packet.jpg"): ("3564.00", "264.00"),
        opaque_name("copperleaf_invoice_copy.pdf"): ("2473.20", "183.20"),
    }
    expected_other_files = {
        opaque_name("north_harbor_expense_claim.jpg"),
        opaque_name("north_harbor_purchase_summary.pdf"),
        opaque_name("bluefern_reimbursement_form.jpg"),
        opaque_name("bluefern_budget_statement.pdf"),
        opaque_name("copperleaf_procurement_review.jpg"),
        opaque_name("copperleaf_expense_rollup.pdf"),
        opaque_name("summit_expense_packet.jpg"),
        opaque_name("summit_rebate_statement.pdf"),
        opaque_name("mesa_claim_sheet.jpg"),
        opaque_name("mesa_quarterly_summary.pdf"),
        opaque_name("harborpoint_spend_report.pdf"),
        opaque_name("prairie_internal_packet.jpg"),
    }
