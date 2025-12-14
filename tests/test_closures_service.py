# tests/test_closures_service.py
import pytest
from decimal import Decimal
from services.closures_service import ClosuresService, AccrualItem
from db.db_manager import DBManager

@pytest.fixture
def closures():
    return ClosuresService()

def setup_period(year="2025", month="12"):
    conn = DBManager.connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM periods WHERE year=? AND month=?", (year, month))
    cur.execute(
        "INSERT INTO periods(year, month, start_date, end_date, status) VALUES (?, ?, ?, ?, 'open')",
        (year, month, f"{year}-{month}-01", f"{year}-{month}-31"),
    )
    conn.commit()

def test_close_period_with_accrual(closures):
    setup_period()

    accrual = AccrualItem(
        descrizione="Rateo interessi",
        date_="2025-12-31",
        expense_account="6000",  # conto costi
        payable_account="2000",  # conto debiti
        amount=Decimal("100.00"),
    )

    result = closures.close_period("2025", "12", user_id="user1", accruals=[accrual])
    assert result.success is True

def test_open_new_period(closures):
    # Setup anno precedente finalizzato
    conn = DBManager.connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM periods WHERE year=?", ("2025",))
    cur.execute(
        "INSERT INTO periods(year, month, start_date, end_date, status) VALUES (?, NULL, ?, ?, 'finalized')",
        ("2025", "2025-01-01", "2025-12-31"),
    )
    conn.commit()

    result = closures.open_new_period("2026", user_id="user1")
    assert result.success is True
