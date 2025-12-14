from decimal import Decimal
from services.ledger_service import LedgerService

def test_idempotent_posting_returns_existing_entry():
    svc = LedgerService()
    idem = "IDEM:FA-200:2025-01-16"

    r1 = svc.post_sales_invoice(
        date="2025-01-16",
        customer_name_or_code="CLI-002",
        doc_no="FA-200",
        doc_date="2025-01-16",
        descrizione="Fattura vendita idem",
        net_amount=Decimal("50.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
        idempotence_key=idem,
    )
    assert r1.success

    r2 = svc.post_sales_invoice(
        date="2025-01-16",
        customer_name_or_code="CLI-002",
        doc_no="FA-200",
        doc_date="2025-01-16",
        descrizione="Fattura vendita idem",
        net_amount=Decimal("50.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
        idempotence_key=idem,
    )
    assert r2.success
    assert r2.entry_id == r1.entry_id
    assert r2.protocol == r1.protocol

def test_idempotence_conflict_on_different_payload():
    svc = LedgerService()
    idem = "IDEM:FA-201:2025-01-17"

    r1 = svc.post_sales_invoice(
        date="2025-01-17",
        customer_name_or_code="CLI-003",
        doc_no="FA-201",
        doc_date="2025-01-17",
        descrizione="Vendita",
        net_amount=Decimal("80.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
        idempotence_key=idem,
    )
    assert r1.success

    r2 = svc.post_sales_invoice(
        date="2025-01-17",
        customer_name_or_code="CLI-003",
        doc_no="FA-201",
        doc_date="2025-01-17",
        descrizione="Vendita modificata",
        net_amount=Decimal("80.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
        idempotence_key=idem,
    )
    assert not r2.success
    assert any(ed.code == "IDEMPOTENCE_CONFLICT" for ed in r2.error_details)
