# services/ledger_service.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from datetime import datetime
from core.models import EntryDTO, EntryResult, LineDTO
from kernel.poster_adapter import PosterAdapter
from kernel.validator_adapter import PeriodsRepoDB, EntriesRepoDB
from services.ledger_query_repo import LedgerQueryRepo
from core.utils import q2
from services.constants import AccountCodes


def _default_idempotence_key(prefix: str, date: str, doc_no: Optional[str], descrizione: str) -> str:
    base = f"{prefix}:{date}:{doc_no or ''}:{descrizione}"
    # Keep it deterministic; PostingEngine will compare payload hashes for conflicts.
    return base


# ---- Optional default account map (suitable for an Italian baseline) ----
@dataclass(frozen=True)
class AccountMap:
    # Attività
    crediti_clienti: str = AccountCodes.CREDITI_CLIENTI
    iva_a_credito: str = AccountCodes.IVA_A_CREDITO
    banca_cc: str = AccountCodes.BANCA_CC
    cassa: str = AccountCodes.CASSA
    debiti_fornitori: str = AccountCodes.DEBITI_FORNITORI
    iva_a_debito: str = AccountCodes.IVA_A_DEBITO
    vendite_prestazioni: str = AccountCodes.VENDITE_PRESTAZIONI
    costi_servizi: str = AccountCodes.COSTI_SERVIZI
    oneri_finanziari: str = AccountCodes.ONERI_FINANZIARI


class LedgerService:
    """
    Enterprise-grade prima nota / libro giornale service.
    - Builds EntryDTOs for common operations
    - Delegates posting to PosterAdapter (which wraps PostingEngine)
    - Supports protocol series and idempotence keys
    """

    def __init__(self, accounts: Optional[AccountMap] = None):
        self.adapter = PosterAdapter()
        self.acc = accounts or AccountMap()

    # ---------------------------
    # Core posting method (generic)
    # ---------------------------
    def post_entry(
        self,
        entry: EntryDTO,
        user_id: str,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        return self.adapter.post_entry(
            entry,
            user_id,
            protocol_series=protocol_series,
            idempotence_key=idempotence_key,
        )
    # ---------------------------
    # Builders for common operations
    # ---------------------------

    def build_sales_invoice(
        self,
        *,
        date: str,
        customer_name_or_code: str,
        doc_no: Optional[str],
        doc_date: Optional[str],
        descrizione: str,
        net_amount: Decimal,
        vat_rate: Decimal,
    ) -> EntryDTO:
        """
        Cliente (fattura attiva):
          Dare: Crediti verso clienti (netto + IVA)
          Avere: Vendite e prestazioni (netto)
          Avere: IVA a debito (IVA)
        """
        net = q2(net_amount)
        rate = q2(vat_rate)
        vat = q2(net * rate)
        total = q2(net + vat)

        lines = [
            LineDTO(account_id=self.acc.crediti_clienti, dare=total),
            LineDTO(account_id=self.acc.vendite_prestazioni, avere=net),
            LineDTO(account_id=self.acc.iva_a_debito, avere=vat),
        ]

        return EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
            documento=doc_no,
            document_date=doc_date,
            cliente_fornitore=customer_name_or_code,
            taxable_amount=net,
            vat_rate=rate,
            vat_amount=vat,
        )

    def post_sales_invoice(
        self,
        *,
        date: str,
        customer_name_or_code: str,
        doc_no: Optional[str],
        doc_date: Optional[str],
        descrizione: str,
        net_amount: Decimal,
        vat_rate: Decimal,
        user_id: str,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        entry = self.build_sales_invoice(
            date=date,
            customer_name_or_code=customer_name_or_code,
            doc_no=doc_no,
            doc_date=doc_date,
            descrizione=descrizione,
            net_amount=net_amount,
            vat_rate=vat_rate,
        )
        idem = idempotence_key or _default_idempotence_key("SALES", date, doc_no, descrizione)
        return self.post_entry(entry, user_id, protocol_series=protocol_series, idempotence_key=idem)

    def build_purchase_invoice(
        self,
        *,
        date: str,
        supplier_name_or_code: str,
        doc_no: Optional[str],
        doc_date: Optional[str],
        descrizione: str,
        net_amount: Decimal,
        vat_rate: Decimal,
        expense_account_code: Optional[str] = None,
    ) -> EntryDTO:
        """
        Fornitore (fattura passiva):
          Dare: Costi (netto) - default costi servizi
          Dare: IVA a credito (IVA)
          Avere: Debiti verso fornitori (netto + IVA)
        """
        net = q2(net_amount)
        rate = q2(vat_rate)
        vat = q2(net * rate)
        total = q2(net + vat)

        expense_acc = expense_account_code or self.acc.costi_servizi

        lines = [
            LineDTO(account_id=expense_acc, dare=net),
            LineDTO(account_id=self.acc.iva_a_credito, dare=vat),
            LineDTO(account_id=self.acc.debiti_fornitori, avere=total),
        ]

        return EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
            documento=doc_no,
            document_date=doc_date,
            cliente_fornitore=supplier_name_or_code,
            taxable_amount=net,
            vat_rate=rate,
            vat_amount=vat,
        )

    def post_purchase_invoice(
        self,
        *,
        date: str,
        supplier_name_or_code: str,
        doc_no: Optional[str],
        doc_date: Optional[str],
        descrizione: str,
        net_amount: Decimal,
        vat_rate: Decimal,
        user_id: str,
        expense_account_code: Optional[str] = None,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        entry = self.build_purchase_invoice(
            date=date,
            supplier_name_or_code=supplier_name_or_code,
            doc_no=doc_no,
            doc_date=doc_date,
            descrizione=descrizione,
            net_amount=net_amount,
            vat_rate=vat_rate,
            expense_account_code=expense_account_code,
        )
        idem = idempotence_key or _default_idempotence_key("PURCHASE", date, doc_no, descrizione)
        return self.post_entry(entry, user_id, protocol_series=protocol_series, idempotence_key=idem)

    def build_cash_receipt(
        self,
        *,
        date: str,
        customer_name_or_code: str,
        descrizione: str,
        amount: Decimal,
        bank_account_code: Optional[str] = None,
    ) -> EntryDTO:
        """
        Incasso da cliente:
          Dare: Banca c/c (importo)
          Avere: Crediti verso clienti (importo)
        """
        amt = q2(amount)
        bank_acc = bank_account_code or self.acc.banca_cc
        lines = [
            LineDTO(account_id=bank_acc, dare=amt),
            LineDTO(account_id=self.acc.crediti_clienti, avere=amt),
        ]
        return EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
            cliente_fornitore=customer_name_or_code,
        )

    def post_cash_receipt(
        self,
        *,
        date: str,
        customer_name_or_code: str,
        descrizione: str,
        amount: Decimal,
        user_id: str,
        bank_account_code: Optional[str] = None,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        entry = self.build_cash_receipt(
            date=date,
            customer_name_or_code=customer_name_or_code,
            descrizione=descrizione,
            amount=amount,
            bank_account_code=bank_account_code,
        )
        idem = idempotence_key or _default_idempotence_key("RECEIPT", date, None, descrizione)
        return self.post_entry(entry, user_id, protocol_series=protocol_series, idempotence_key=idem)

    def build_cash_payment(
        self,
        *,
        date: str,
        supplier_name_or_code: str,
        descrizione: str,
        amount: Decimal,
        bank_account_code: Optional[str] = None,
    ) -> EntryDTO:
        """
        Pagamento a fornitore:
          Dare: Debiti verso fornitori (importo)
          Avere: Banca c/c (importo)
        """
        amt = q2(amount)
        bank_acc = bank_account_code or self.acc.banca_cc
        lines = [
            LineDTO(account_id=self.acc.debiti_fornitori, dare=amt),
            LineDTO(account_id=bank_acc, avere=amt),
        ]
        return EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
            cliente_fornitore=supplier_name_or_code,
        )

    def post_cash_payment(
        self,
        *,
        date: str,
        supplier_name_or_code: str,
        descrizione: str,
        amount: Decimal,
        user_id: str,
        bank_account_code: Optional[str] = None,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        entry = self.build_cash_payment(
            date=date,
            supplier_name_or_code=supplier_name_or_code,
            descrizione=descrizione,
            amount=amount,
            bank_account_code=bank_account_code,
        )
        idem = idempotence_key or _default_idempotence_key("PAYMENT", date, None, descrizione)
        return self.post_entry(entry, user_id, protocol_series=protocol_series, idempotence_key=idem)

    def build_bank_fee(
        self,
        *,
        date: str,
        descrizione: str,
        fee_amount: Decimal,
        bank_account_code: Optional[str] = None,
    ) -> EntryDTO:
        """
        Spese bancarie:
          Dare: Oneri finanziari (spesa)
          Avere: Banca c/c (spesa)
        """
        fee = q2(fee_amount)
        bank_acc = bank_account_code or self.acc.banca_cc
        lines = [
            LineDTO(account_id=self.acc.oneri_finanziari, dare=fee),
            LineDTO(account_id=bank_acc, avere=fee),
        ]
        return EntryDTO(
            date=date,
            descrizione=descrizione,
            lines=lines,
        )

    def post_bank_fee(
        self,
        *,
        date: str,
        descrizione: str,
        fee_amount: Decimal,
        user_id: str,
        bank_account_code: Optional[str] = None,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        entry = self.build_bank_fee(
            date=date,
            descrizione=descrizione,
            fee_amount=fee_amount,
            bank_account_code=bank_account_code,
        )
        idem = idempotence_key or _default_idempotence_key("BANKFEE", date, None, descrizione)
        return self.post_entry(entry, user_id, protocol_series=protocol_series, idempotence_key=idem)

    # ---------------------------
    # Reversal (storno) support
    # ---------------------------
    def reverse_entry(
        self,
        *,
        original_entry_id: int,
        user_id: str,
        descrizione: str = "Storno",
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        """
        Reversal sicuro:
        - Controlli su esistenza entry
        - Controllo che non sia già stornata
        - Controllo periodo aperto (oggi)
        - Costruzione e posting reversal
        """

        repo = LedgerQueryRepo()
        entries_repo = EntriesRepoDB()
        periods_repo = PeriodsRepoDB()

        # --- Validazioni preliminari ---
        # Entry esiste?
        if not entries_repo.exists(original_entry_id):
            return EntryResult(success=False, errors=[f"Entry {original_entry_id} non trovata"], error_details=[])

        # Non già stornata?
        err_rev = entries_repo.assert_not_reversed(original_entry_id)
        if err_rev:
            return EntryResult(success=False, errors=[err_rev.message], error_details=[err_rev])

        # Periodo odierno aperto?
        today = datetime.today().strftime("%Y-%m-%d")
        err_period = periods_repo.assert_open(today)
        if err_period:
            return EntryResult(success=False, errors=[err_period.message], error_details=[err_period])

        # --- Costruzione reversal DTO ---
        reversal_dto = repo.build_reversal(original_entry_id, descrizione)
        if not reversal_dto:
            return EntryResult(success=False, errors=[f"Impossibile costruire reversal per id {original_entry_id}"], error_details=[])

        # --- Punto per logiche custom ---
        # Esempio: sostituire account specifici se necessario
        # for line in reversal_dto.lines:
        #     if line.account_id == "XXXX":
        #         line.account_id = "YYYY"

        # --- Idempotence key ---
        idem = idempotence_key or _default_idempotence_key("REV", reversal_dto.date, reversal_dto.documento, descrizione)

        # --- Posting tramite adapter ---
        return self.post_entry(reversal_dto, user_id, protocol_series=protocol_series, idempotence_key=idem)