
from decimal import Decimal
from services.ledger_service import LedgerService
from core.models import LineDTO, EntryDTO

def test_unbalanced_entry_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="2025-03-01",
        descrizione="Unbalanced",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("100.00")),
            LineDTO(account_id="4100", avere=Decimal("90.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "UNBALANCED" for e in r.error_details)

def test_negative_amount_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="2025-03-02",
        descrizione="Negative",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("-1.00")),
            LineDTO(account_id="4100", avere=Decimal("1.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "NEGATIVE_AMOUNT" for e in r.error_details)

def test_ambiguous_line_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="2025-03-03",
        descrizione="Ambiguous",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("1.00"), avere=Decimal("1.00")),
            LineDTO(account_id="4100", dare=Decimal("0.00"), avere=Decimal("0.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    codes = {e.code for e in r.error_details}
    assert "AMBIGUOUS_LINE" in codes
    assert "EMPTY_LINES" in codes

def test_invalid_account_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="2025-03-04",
        descrizione="Invalid account",
        lines=[
            LineDTO(account_id="ZZZ", dare=Decimal("10.00")),
            LineDTO(account_id="4100", avere=Decimal("10.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "INVALID_ACCOUNT" for e in r.error_details)

def test_period_closed_rejected():
    # Close a period window covering 2025-04-01 explicitly
    from db.db_manager import DBManager
    DBManager.execute_script("""
        INSERT INTO periods(year, month, start_date, end_date, status)
        VALUES ('2025', NULL, '2025-04-01', '2025-04-30', 'closed');
    """)

    svc = LedgerService()
    entry = EntryDTO(
        date="2025-04-15",
        descrizione="Periodo chiuso",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("10.00")),
            LineDTO(account_id="4100", avere=Decimal("10.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "PERIOD_CLOSED" for e in r.error_details)

def test_invalid_date_format_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="15-04-2025",  # invalid format
        descrizione="Data non valida",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("10.00")),
            LineDTO(account_id="4100", avere=Decimal("10.00")),
        ],
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "INVALID_DATE" for e in r.error_details)

def test_vat_mismatch_rejected():
    svc = LedgerService()
    entry = EntryDTO(
        date="2025-05-01",
        descrizione="IVA mismatch",
        lines=[
            LineDTO(account_id="1410", dare=Decimal("122.00")),
            LineDTO(account_id="4100", avere=Decimal("100.00")),
            LineDTO(account_id="2321", avere=Decimal("21.00")),  # wrong VAT (should be 22.00)
        ],
        taxable_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        vat_amount=Decimal("21.00"),
    )
    r = svc.post_entry(entry, user_id="tester")
    assert not r.success
    assert any(e.code == "VAT_MISMATCH" for e in r.error_details)
