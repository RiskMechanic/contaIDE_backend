from decimal import Decimal
from services.ledger_service import LedgerService
from db.db_manager import DBManager

def test_audit_log_written_with_hash_chain():
    svc = LedgerService()
    r = svc.post_cash_receipt(
        date="2025-08-01",
        customer_name_or_code="CLI-009",
        descrizione="Incasso",
        amount=Decimal("30.00"),
        user_id="tester",
    )
    assert r.success

    # Payload exists and curr_hash set
    row = DBManager.fetch_one("SELECT * FROM audit_log WHERE entry_id = ? ORDER BY id DESC LIMIT 1", (r.entry_id,))
    assert row is not None
    assert row["action"] == "POST"
    assert row["curr_hash"] is not None

def test_lines_persisted_in_cents():
    svc = LedgerService()
    r = svc.post_cash_payment(
        date="2025-09-01",
        supplier_name_or_code="FOR-XYZ",
        descrizione="Pagamento",
        amount=Decimal("10.23"),
        user_id="tester",
    )
    assert r.success
    lines = DBManager.fetch_all("SELECT dare_cents, avere_cents FROM entry_lines WHERE entry_id = ?", (r.entry_id,))
    assert len(lines) == 2
    cents_set = {tuple((row["dare_cents"], row["avere_cents"])) for row in lines}
    assert (1023, 0) in cents_set or (0, 1023) in cents_set
