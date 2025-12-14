# services/vat_service.py
from decimal import Decimal
from typing import List
from core.models import EntryDTO, LineDTO, EntryResult
from services.ledger_service import LedgerService

class VATService:
    def __init__(self, ledger: LedgerService):
        self._ledger = ledger

    def post_vat_entry(self,
                       date: str,
                       descrizione: str,
                       taxable_amount: Decimal,
                       vat_rate: Decimal,
                       revenue_account: str,
                       vat_liability_account: str,
                       receivable_account: str,
                       user_id: str) -> EntryResult:
        vat_amount = (taxable_amount * vat_rate).quantize(Decimal("0.01"))
        # Example: sale on credit: Dr A/R, Cr Revenue, Cr VAT liability
        lines = [
            LineDTO(account_id=receivable_account, dare=taxable_amount + vat_amount),
            LineDTO(account_id=revenue_account, avere=taxable_amount),
            LineDTO(account_id=vat_liability_account, avere=vat_amount),
        ]
        entry = EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
            taxable_amount=taxable_amount,
            vat_rate=vat_rate,
            vat_amount=vat_amount
        )
        return self._ledger.post_entry(entry, user_id)
