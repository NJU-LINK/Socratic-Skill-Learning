from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("harbor_bean_tax_receipt.jpg"): ("84.60", "7.05"),
        opaque_name("northline_guest_copy.pdf"): ("158.20", "12.20"),
        opaque_name("metro_foods_counter.jpg"): ("43.50", "3.50"),
        opaque_name("oak_market_supply.pdf"): ("231.10", "21.00"),
        opaque_name("green_tray_checkout.jpg"): ("96.30", "8.75"),
    }
    expected_other_files = {
        opaque_name("harbor_bean_payment.jpg"),
        opaque_name("northline_refund.pdf"),
        opaque_name("metro_foods_shift.jpg"),
        opaque_name("oak_market_settlement.jpg"),
        opaque_name("green_tray_endofday.pdf"),
    }
