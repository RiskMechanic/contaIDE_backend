# tests/test_backend_e2e.py
import uuid
import pytest
from decimal import Decimal

from db.db_manager import DBManager
from core.models import LineDTO, EntryDTO
from services.ledger_service import LedgerService
from services.audit_service import AuditService
from services.closures_service import ClosuresService

# -----------------------------
# Isolated DB per test
# -----------------------------
@pytest.fixture(autouse=True, scope="function")
def isolated_db():
    uri = f"file:memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
    DBManager.configure(path=uri)
    DBManager.initialize()  # schema + chart + migrations
    yield
    DBManager.close()

@pytest.fixture
def ledger():
    return LedgerService()

@pytest.fixture
def audit():
    return AuditService()

@pytest.fixture
def closures():
    svc = ClosuresService()
    # Assicura che la cache conti sia aggiornata
    if hasattr(svc, "refresh_accounts"):
        svc.refresh_accounts()
    return svc

# -----------------------------
# Helpers
# -----------------------------
def count_entries():
    row = DBManager.fetch_one("SELECT COUNT(*) AS c FROM entries")
    return int(row["c"])

def lines_totals(entry_id: int):
    # Allineato allo schema: dare_cents / avere_cents
    row = DBManager.fetch_one("""
        SELECT 
            SUM(dare_cents) AS dare_total,
            SUM(avere_cents) AS avere_total
        FROM entry_lines
        WHERE entry_id=?
    """, (entry_id,))
    return {
        "DEBIT": int(row["dare_total"] or 0),
        "CREDIT": int(row["avere_total"] or 0),
    }

def period_status(year: str, month: str | None = None):
    if month is None:
        row = DBManager.fetch_one("SELECT status FROM periods WHERE year=? AND month IS NULL", (year,))
    else:
        row = DBManager.fetch_one("SELECT status FROM periods WHERE year=? AND month=?", (year, month))
    return row["status"] if row else None

def set_year_open(year: str):
    conn = DBManager.connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM periods WHERE year=?", (year,))
    cur.execute("""
        INSERT INTO periods(year, month, start_date, end_date, status)
        VALUES (?, NULL, ? || '-01-01', ? || '-12-31', 'open')
    """, (year, year, year))
    conn.commit()
    cur.close()

def set_year_finalized(year: str):
    conn = DBManager.connect()
    cur = conn.cursor()
    cur.execute("UPDATE periods SET status='finalized' WHERE year=?", (year,))
    conn.commit()
    cur.close()

# -----------------------------
# Full E2E
# -----------------------------
def test_backend_full_e2e(ledger, audit, closures):
    user = "tester"

    # 0) Bootstrap periodo 2025 aperto
    set_year_open("2025")
    assert period_status("2025") == "open"

    # 1) Posting fattura vendita (con protocol GEN)
    r_sale = ledger.post_sales_invoice(
        date="2025-01-15",
        customer_name_or_code="CLI-001",
        doc_no="FA-100",
        doc_date="2025-01-15",
        descrizione="Fattura vendita",
        net_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        user_id=user,
        protocol_series="GEN",
    )
    assert r_sale.success, f"Vendita fallita: {r_sale.errors}"
    t_sale = lines_totals(r_sale.entry_id)
    assert t_sale["DEBIT"] == t_sale["CREDIT"], "Vendita non bilanciata"
    assert r_sale.protocol.startswith("2025/GEN/"), "Protocollo non nella serie GEN"

        # 2) Idempotenza: stessa fattura, stesso idempotence_key => non deve fallire
    idem_key = "IDEM:FA-100:2025-01-15"
    r_sale_idem = ledger.post_sales_invoice(
        date="2025-01-15",
        customer_name_or_code="CLI-001",
        doc_no="FA-100",
        doc_date="2025-01-15",
        descrizione="Fattura vendita idem",
        net_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        user_id=user,
        idempotence_key=idem_key,
    )
    assert r_sale_idem.success, f"Idempotenza fallita: {r_sale_idem.errors}"
    # Verifica che la chiave sia registrata
    row = DBManager.fetch_one("SELECT entry_id FROM idempotence WHERE key=?", (idem_key,))
    assert row is not None, "Chiave idempotence non registrata"
    # Verifica che la scrittura sia bilanciata
    t_sale_idem = lines_totals(r_sale_idem.entry_id)
    assert t_sale_idem["DEBIT"] == t_sale_idem["CREDIT"], "Scrittura idem non bilanciata"

    
    # 3) Posting costo (6000/2000)
    # Assicurati che il conto 6000 esista nel DB e nella cache
    row = DBManager.fetch_one("SELECT code FROM accounts WHERE code='6000'")
    if row is None:
        DBManager.execute(
            "INSERT INTO accounts(code, name, class, statement_type) VALUES (?,?,?,?)",
            ("6000", "Costi vari", "C", "EXPENSE")
        )
    closures.refresh_accounts()

    e_cost = EntryDTO(
        date="2025-01-16",
        descrizione="Acquisto",
        lines=[
            LineDTO(account_id="6000", dare=Decimal("200.00")),
            LineDTO(account_id="2000", avere=Decimal("200.00")),
        ],
    )
    r_cost = closures.engine.post(e_cost, user, closures._accounts, closures._periods, closures._entries)
    assert r_cost.success, f"Costo fallito: {r_cost.errors}"
    t_cost = lines_totals(r_cost.entry_id)
    assert t_cost["DEBIT"] == t_cost["CREDIT"], "Costo non bilanciato"

    # 4) Reverse della fattura vendita
    r_rev = ledger.reverse_entry(r_sale.entry_id, user_id=user, descrizione="Storno vendita")
    assert r_rev.success, f"Reverse fallito: {r_rev.errors}"
    t_rev = lines_totals(r_rev.entry_id)
    assert t_rev["DEBIT"] == t_rev["CREDIT"], "Reverse non bilanciato"

    # 5) Audit: chain incrementale presente per le entry principali
    chain_rows = DBManager.fetch_all("""
        SELECT entry_id, prev_hash, curr_hash
        FROM audit_log
        WHERE entry_id IN (?, ?, ?)
        ORDER BY entry_id
    """, (r_sale.entry_id, r_cost.entry_id, r_rev.entry_id))
    assert len(chain_rows) == 3, "Audit chain incompleta"
    assert all(row["prev_hash"] is not None and row["curr_hash"] is not None for row in chain_rows), "Hash chain non valorizzata"

    # 6) Protocol atomico: più post ravvicinati incrementano correttamente
    r_fee1 = ledger.post_bank_fee(date="2025-02-01", descrizione="Spese", fee_amount=Decimal("5.00"), user_id=user)
    r_fee2 = ledger.post_bank_fee(date="2025-02-01", descrizione="Spese 2", fee_amount=Decimal("3.00"), user_id=user)
    assert r_fee1.success and r_fee2.success, f"Posting fee fallito: {r_fee1.errors or r_fee2.errors}"
    assert r_fee1.protocol != r_fee2.protocol, "Protocollo non incrementato"

    # 7) Chiusura mese con rateo (fine 2025-12)
    accrual = {
        "descrizione": "Rateo interessi",
        "date_": "2025-12-31",
        "expense_account": "6000",
        "payable_account": "2000",
        "amount": Decimal("100.00"),
    }
    before_entries = count_entries()
    r_close = closures.close_period("2025", "12", user_id=user, accruals=[accrual])
    assert r_close.success, f"Chiusura mese fallita: {r_close.errors}"
    assert count_entries() == before_entries + 1, "Scrittura di chiusura non registrata"
    t_close = lines_totals(r_close.entry_id)
    assert t_close["DEBIT"] == t_close["CREDIT"], "Chiusura mese non bilanciata"

    # 8) Finalizza anno 2025 e apri 2026 con opening
    set_year_finalized("2025")
    assert period_status("2025") == "finalized", "Anno 2025 non finalizzato"

    r_open = closures.open_new_period("2026", user_id=user)
    assert r_open.success, f"Apertura nuovo esercizio fallita: {r_open.errors}"

    # Opening bilanciata e su soli conti patrimoniali (ASSET/LIABILITY/EQUITY)
    t_open = lines_totals(r_open.entry_id)
    assert t_open["DEBIT"] == t_open["CREDIT"], "Opening non bilanciata"

    st_types = DBManager.fetch_all("""
        SELECT DISTINCT a.statement_type
        FROM entry_lines el
        JOIN accounts a ON a.code = el.account_code
        WHERE el.entry_id=?
    """, (r_open.entry_id,))
    allowed = {row["statement_type"] for row in st_types}
    assert allowed.issubset({"ASSET", "LIABILITY", "EQUITY"}), f"Opening include conti economici: {allowed - {'ASSET','LIABILITY','EQUITY'}}"
