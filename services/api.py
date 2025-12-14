# services/api.py
# Scopo: raccogliere API interne del dominio contabile, cioè le funzioni che userà il DSL Parser o CLI/Web

from decimal import Decimal
from services.ledger_service import LedgerService

ledger = LedgerService()

def create_sales_invoice(date: str, customer: str, doc_no: str, net_amount: Decimal, vat_rate: Decimal, user_id: str):
    return ledger.post_sales_invoice(
        date=date,
        customer_name_or_code=customer,
        doc_no=doc_no,
        doc_date=date,
        descrizione=f"Fattura vendita {doc_no}",
        net_amount=net_amount,
        vat_rate=vat_rate,
        user_id=user_id
    )
