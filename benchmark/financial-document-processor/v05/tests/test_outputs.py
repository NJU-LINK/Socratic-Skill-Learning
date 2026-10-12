from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("northwind_invoice.pdf"): ("1987.20", "147.20"),
        opaque_name("blueharbor_invoice.pdf"): ("2743.20", "203.20"),
        opaque_name("granitepeak_invoice.jpg"): ("1252.80", "92.80"),
        opaque_name("harborlight_invoice.pdf"): ("1031.40", "76.40"),
        opaque_name("ironwood_invoice.pdf"): ("1825.20", "135.20"),
        opaque_name("juniperlane_invoice.pdf"): ("842.40", "62.40"),
        opaque_name("meadowrun_invoice.jpg"): ("1215.00", "90.00"),
    }
    expected_other_files = {
        opaque_name("northwind_service_completion.pdf"),
        opaque_name("blueharbor_repair_summary.pdf"),
        opaque_name("cedarfield_work_order.pdf"),
        opaque_name("granitepeak_service_report.pdf"),
        opaque_name("harborlight_completion_packet.pdf"),
        opaque_name("ironwood_maintenance_summary.jpg"),
        opaque_name("juniperlane_work_record.pdf"),
        opaque_name("lakeside_av_closeout.pdf"),
        opaque_name("oakbranch_generators_completion_note.jpg"),
        opaque_name("meadowrun_service_packet.pdf"),
    }
