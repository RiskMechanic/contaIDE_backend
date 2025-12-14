from decimal import Decimal
from services.api import create_sales_invoice

def test_sales_invoice_posting():
    result = create_sales_invoice(
        date="2025-12-14",
        customer="Mario Rossi",
        doc_no="F123",
        net_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        user_id="CEO"
    )
    assert result.success
