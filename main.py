# main.py
import logging
from decimal import Decimal
from db.db_manager import DBManager
from services.ledger_service import LedgerService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

def bootstrap_db():
    """
    Initialize schema, seed chart of accounts, run migrations,
    and ensure at least one open period exists.
    """
    logger.info("Initializing database...")
    DBManager.initialize()
    logger.info("Database initialized.")

def demo_postings():
    """
    Run a few demo postings to show the backend works end-to-end.
    """
    svc = LedgerService()

    # Example: Sales invoice
    result = svc.post_sales_invoice(
        date="2025-12-14",
        customer_name_or_code="CLI-DEMO",
        doc_no="FA-DEMO-1",
        doc_date="2025-12-14",
        descrizione="Demo fattura vendita",
        net_amount=Decimal("100.00"),
        vat_rate=Decimal("0.22"),
        user_id="demo_user",
    )
    if result.success:
        logger.info(f"Sales invoice posted: entry_id={result.entry_id}, protocol={result.protocol}")
    else:
        logger.error(f"Sales invoice failed: {result.errors}")

    # Example: Bank fee
    result2 = svc.post_bank_fee(
        date="2025-12-14",
        descrizione="Spese bancarie demo",
        fee_amount=Decimal("5.00"),
        user_id="demo_user",
    )
    if result2.success:
        logger.info(f"Bank fee posted: entry_id={result2.entry_id}, protocol={result2.protocol}")
    else:
        logger.error(f"Bank fee failed: {result2.errors}")

def main():
    bootstrap_db()
    demo_postings()

if __name__ == "__main__":
    main()
