from decimal import Decimal
from services.ledger_service import LedgerService
from db.db_manager import DBManager

def test_reverse_entry_happy_path():
    svc = LedgerService()

    # Post original
    r1 = svc.post_purchase_invoice(
        date="2025-06-01",
        supplier_name_or_code="FOR-001",
        doc_no="FP-10",
        doc_date="2025-06-01",
        descrizione="Fattura passiva",
        net_amount=Decimal("50.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
    )
    assert r1.success

    # Reverse
    r2 = svc.reverse_entry(original_entry_id=r1.entry_id, user_id="tester", descrizione="Storno test")
    assert r2.success

    # Check reversal linkage
    link = DBManager.fetch_one("SELECT * FROM entry_reversals WHERE reversal_of = ?", (r1.entry_id,))
    assert link is not None
    assert link["entry_id"] == r2.entry_id

def test_reverse_entry_rejected_if_already_reversed():
    svc = LedgerService()

    r1 = svc.post_bank_fee(date="2025-07-01", descrizione="Spesa banca", fee_amount=Decimal("5.00"), user_id="tester")
    assert r1.success

    r2 = svc.reverse_entry(original_entry_id=r1.entry_id, user_id="tester")
    assert r2.success

    r3 = svc.reverse_entry(original_entry_id=r1.entry_id, user_id="tester")
    assert not r3.success
    assert any(e.code == "ALREADY_REVERSED" for e in r3.error_details)
