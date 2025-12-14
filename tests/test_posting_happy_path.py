from decimal import Decimal
from services.ledger_service import LedgerService
from db.db_manager import DBManager

def test_post_sales_invoice_happy_path():
    svc = LedgerService()
    result = svc.post_sales_invoice(
        date="2025-01-15",
        customer_name_or_code="CLI-001",
        doc_no="FA-100",
        doc_date="2025-01-15",
        descrizione="Fattura vendita",
        net_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        user_id="tester",
        protocol_series="GEN",
    )
    assert result.success, f"Posting failed: {result.errors}"
    assert result.entry_id is not None
    assert isinstance(result.protocol, str) and result.protocol.startswith("2025/GEN/")

    entry = DBManager.fetch_one("SELECT * FROM entries WHERE id = ?", (result.entry_id,))
    assert entry is not None
    assert entry["protocol"] == result.protocol
    assert entry["document"] == "FA-100"
    assert entry["party"] == "CLI-001"
    assert entry["description"] == "Fattura vendita"

    lines = DBManager.fetch_all("SELECT * FROM entry_lines WHERE entry_id = ?", (result.entry_id,))
    assert len(lines) == 3
    dare = sum(l["dare_cents"] or 0 for l in lines)
    avere = sum(l["avere_cents"] or 0 for l in lines)
    assert dare == avere and dare > 0

def test_protocol_increments_atomically():
    svc = LedgerService()
    r1 = svc.post_bank_fee(date="2025-02-01", descrizione="Spese", fee_amount=Decimal("5.00"), user_id="tester")
    r2 = svc.post_bank_fee(date="2025-02-01", descrizione="Spese 2", fee_amount=Decimal("3.00"), user_id="tester")
    assert r1.success and r2.success
    assert r1.protocol != r2.protocol
