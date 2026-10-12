from financial_document_test_support import FinancialDocumentContract, opaque_name


class TestFinancialDocumentCase(FinancialDocumentContract):
    expected_invoice_rows = {
        opaque_name("alpha_medical_supply.pdf"): ("1488.00", "248.00"),
        opaque_name("beacon_catering.jpg"): ("945.54", "70.04"),
        opaque_name("cobalt_fabrication.pdf"): ("3420.00", "570.00"),
        opaque_name("delta_maintenance.jpg"): ("602.00", "42.00"),
        opaque_name("ember_logistics.pdf"): ("2160.00", "360.00"),
        opaque_name("fjord_analytics.jpg"): ("1633.91", "134.91"),
        opaque_name("grove_electric.pdf"): ("766.50", "36.50"),
        opaque_name("harbor_packaging.pdf"): ("3520.00", "320.00"),
        opaque_name("iris_office.jpg"): ("1275.00", "0.00"),
    }
    expected_other_files = {
        opaque_name("juno_quote.pdf"),
        opaque_name("kestrel_estimate.jpg"),
        opaque_name("lumen_statement.pdf"),
        opaque_name("meadow_proposal.jpg"),
    }
