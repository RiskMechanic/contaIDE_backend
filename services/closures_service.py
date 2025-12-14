# services/closures_service.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Iterable, Dict, Tuple, List

from core.models import EntryDTO, LineDTO, EntryResult, LedgerError, ErrorCode
from core.posting_engine import PostingEngine
from db.db_manager import DBManager
from kernel.validator_adapter import AccountsRepoDB, PeriodsRepoDB, EntriesRepoDB
from services.audit_service import AuditService


# -------------------------
# Data structures (inputs)
# -------------------------

@dataclass(frozen=True)
class AccrualItem:
    # Rateo: competenza maturata senza documento
    descrizione: str
    date_: str  # ISO date within the closing period
    expense_account: str  # conto costo (CE)
    payable_account: str  # debito (SP)
    amount: Decimal


@dataclass(frozen=True)
class DeferralItem:
    # Risconto: costo già registrato ma da rinviare
    descrizione: str
    date_: str
    prepaid_account: str  # risconti attivi (SP)
    expense_account: str  # conto costo (CE)
    amount: Decimal


@dataclass(frozen=True)
class AmortizationItem:
    # Ammortamento: quota di costo su cespite
    descrizione: str
    date_: str
    asset_account: str  # cespite (SP)
    amortization_expense_account: str  # ammortamento (CE)
    amount: Decimal


# -------------------------
# Closures service
# -------------------------

class ClosuresService:
    """
    Gestione chiusure/aperture di periodi contabili con scritture reali:
    - Chiusura periodi (mese o anno) e blocco scritture
    - Scritture di assestamento (ratei, risconti, ammortamenti) su input esplicito
    - Chiusura conti economici a patrimonio netto
    - Apertura nuovo esercizio con riporti dei saldi patrimoniali
    - Audit centralizzato e verificabile
    """

    def __init__(self, equity_account_code: str = "9999"):
        # equity_account_code: conto di patrimonio netto per utile/perdita d’esercizio
        self.engine = PostingEngine()
        self._accounts = AccountsRepoDB()
        self._periods = PeriodsRepoDB()
        self._entries = EntriesRepoDB()
        self._audit = AuditService()
        self._equity_account = equity_account_code


    # -------------------------
    # Public API
    # -------------------------

    def close_period(
        self,
        year: str,
        month: Optional[str],
        user_id: str,
        *,
        descrizione: str = "Chiusura periodo",
        accruals: Iterable[AccrualItem] = (),
        deferrals: Iterable[DeferralItem] = (),
        amortizations: Iterable[AmortizationItem] = (),
    ) -> EntryResult:
        """
        Chiude il periodo indicato:
        1) Verifica stato e aggiorna a 'closed'
        2) Posta scritture di assestamento (ratei/risconti/ammortamenti) se forniti
        3) Chiude conti economici (CE) a patrimonio netto
        4) Audita l’operazione

        Ritorna il result della scrittura di chiusura CE→PN (l’ultima postata); le altre sono comunque registrate.
        """
        period = self._get_period(year, month)
        if not period:
            return EntryResult(
                success=False,
                errors=[f"Periodo {year}-{month or ''} non esiste"],
                error_details=[LedgerError(ErrorCode.NOT_FOUND, f"Periodo {year}-{month or ''} non esiste")],
            )

        if period["status"] == "closed":
            return EntryResult(
                success=False,
                errors=[f"Periodo {year}-{month or ''} già chiuso"],
                error_details=[LedgerError(ErrorCode.PERIOD_CLOSED, f"Periodo {year}-{month or ''} già chiuso")],
            )
        if period["status"] == "finalized":
            return EntryResult(
                success=False,
                errors=[f"Periodo {year}-{month or ''} già finalizzato"],
                error_details=[LedgerError(ErrorCode.PERIOD_CLOSED, f"Periodo {year}-{month or ''} già finalizzato")],
            )

        # Blocca il periodo
        with DBManager.transaction() as cur:
            cur.execute(
                "UPDATE periods SET status='closed' WHERE year=? AND (month IS ? OR month=?)",
                (year, month, month),
            )

        # 2) Assestamenti (su input esplicito; nulla è “indovinato”)
        for item in accruals:
            self._post_accrual(item, user_id)
        for item in deferrals:
            self._post_deferral(item, user_id)
        for item in amortizations:
            self._post_amortization(item, user_id)

        # 3) Closing CE → Equity
        closing_result = self._post_income_closing_entry(period, user_id, descrizione)

        # 4) Audit operazione di chiusura periodo
        self._audit.log_action(
            "CLOSE_PERIOD",
            user_id,
            {
                "year": year,
                "month": month,
                "descrizione": descrizione,
                "period_start": period["start_date"],
                "period_end": period["end_date"],
            },
            entry_id=closing_result.entry_id if closing_result.success else None,
        )

        return closing_result

    def finalize_year(self, year: str, user_id: str, descrizione: str = "Finalizzazione anno") -> EntryResult:
        """
        Imposta lo stato dell'anno a 'finalized' dopo che tutti i mesi sono chiusi
        e la chiusura dei conti economici è stata effettuata. Non posta scritture.
        """
        # Verifica che tutti i mesi dell'anno siano chiusi (se presenti)
        rows = DBManager.fetch_all("SELECT status FROM periods WHERE year=? AND month IS NOT NULL", (year,))
        if any(r["status"] != "closed" for r in rows):
            return EntryResult(
                success=False,
                errors=[f"Anno {year} non chiudibile: esistono mesi non 'closed'"],
                error_details=[LedgerError(ErrorCode.PERIOD_OPEN, f"Mesi non chiusi per anno {year}")],
            )

        with DBManager.transaction() as cur:
            cur.execute(
                "UPDATE periods SET status='finalized' WHERE year=? AND month IS NULL",
                (year,),
            )

        self._audit.log_action(
            "FINALIZE_YEAR",
            user_id,
            {"year": year, "descrizione": descrizione},
            entry_id=None,
        )
        return EntryResult(success=True, entry_id=None, protocol=None)

    def open_new_period(self, year: str, user_id: str, descrizione: str = "Apertura nuovo esercizio") -> EntryResult:
        """
        Apre l'anno con stato 'open' (record month=NULL) e posta le scritture di apertura
        riportando i saldi patrimoniali dall'anno precedente (se finalizzato).
        """
        prev_year = str(int(year) - 1)

        # Inserisci/assicurati del periodo annuale open
        with DBManager.transaction() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO periods(year, month, start_date, end_date, status)
                VALUES (?, NULL, ? || '-01-01', ? || '-12-31', 'open')
                """,
                (year, year, year),
            )

        # Calcola e posta scrittura di apertura dagli SP del year-1
        opening_result = self._post_opening_balance_entry(prev_year, year, user_id, descrizione)

        # Audit
        self._audit.log_action(
            "OPEN_PERIOD",
            user_id,
            {"year": year, "descrizione": descrizione},
            entry_id=opening_result.entry_id if opening_result.success else None,
        )

        return opening_result

    # -------------------------
    # Internal logic
    # -------------------------

    def _get_period(self, year: str, month: Optional[str]) -> Optional[Dict]:
        row = DBManager.fetch_one(
            "SELECT year, month, start_date, end_date, status FROM periods WHERE year=? AND (month IS ? OR month=?)",
            (year, month, month),
        )
        return dict(row) if row else None

    def _post_accrual(self, item: AccrualItem, user_id: str) -> EntryResult:
        # Dare: costo (CE), Avere: debito (SP)
        entry = EntryDTO(
            date=item.date_,
            descrizione=item.descrizione,
            lines=[
                LineDTO(account_id=item.expense_account, dare=item.amount),
                LineDTO(account_id=item.payable_account, avere=item.amount),
            ],
        )
        return self.engine.post(entry, user_id, self._accounts, self._periods, self._entries, protocol_series="ADJ")

    def _post_deferral(self, item: DeferralItem, user_id: str) -> EntryResult:
        # Dare: risconto attivo (SP), Avere: costo (CE)
        entry = EntryDTO(
            date=item.date_,
            descrizione=item.descrizione,
            lines=[
                LineDTO(account_id=item.prepaid_account, dare=item.amount),
                LineDTO(account_id=item.expense_account, avere=item.amount),
            ],
        )
        return self.engine.post(entry, user_id, self._accounts, self._periods, self._entries, protocol_series="ADJ")

    def _post_amortization(self, item: AmortizationItem, user_id: str) -> EntryResult:
        # Dare: costo ammortamento (CE), Avere: fondo ammortamento/cespite (SP)
        entry = EntryDTO(
            date=item.date_,
            descrizione=item.descrizione,
            lines=[
                LineDTO(account_id=item.amortization_expense_account, dare=item.amount),
                LineDTO(account_id=item.asset_account, avere=item.amount),
            ],
        )
        return self.engine.post(entry, user_id, self._accounts, self._periods, self._entries, protocol_series="ADJ")

    def _post_income_closing_entry(self, period: Dict, user_id: str, descrizione: str) -> EntryResult:
        """
        Chiude tutti i conti economici (REVENUE/EXPENSE) azzerandone il saldo e
        riversando l'utile/perdita sul conto di patrimonio netto configurato.
        """
        balances = self._trial_balance(period["start_date"], period["end_date"])

        debit_total = Decimal("0")
        credit_total = Decimal("0")
        lines: List[LineDTO] = []

        # Per zeroing CE:
        # - REVENUE (natura credit): se ha saldo credit, si posta una riga a DARE dello stesso importo
        # - EXPENSE (natura debit): se ha saldo debit, si posta una riga a AVERE dello stesso importo
        for acc, bal in balances.items():
            st = bal["statement_type"]
            if st not in ("REVENUE", "EXPENSE"):
                continue
            side, amount = bal["side"], bal["amount"]
            if amount == 0:
                continue

            if st == "REVENUE":
                if side == "CREDIT":
                    # Zerare il ricavo: riga a DARE
                    lines.append(LineDTO(account_id=acc, dare=amount))
                    debit_total += amount
                else:
                    # Ricavo con saldo a DARE (anomalia, ma gestiamola): riga a AVERE
                    lines.append(LineDTO(account_id=acc, avere=amount))
                    credit_total += amount
            else:  # EXPENSE
                if side == "DEBIT":
                    # Zerare il costo: riga a AVERE
                    lines.append(LineDTO(account_id=acc, avere=amount))
                    credit_total += amount
                else:
                    # Costo con saldo a AVERE (anomalia): riga a DARE
                    lines.append(LineDTO(account_id=acc, dare=amount))
                    debit_total += amount

        # Controparte su patrimonio netto per differenza
        if debit_total > credit_total:
            diff = debit_total - credit_total  # perdita (debit > credit) → equity a AVERE per chiudere
            lines.append(LineDTO(account_id=self._equity_account, avere=diff))
            credit_total += diff
        elif credit_total > debit_total:
            diff = credit_total - debit_total  # utile → equity a DARE
            lines.append(LineDTO(account_id=self._equity_account, dare=diff))
            debit_total += diff

        # Se non c'erano CE da chiudere, posta una scrittura zero? Meglio: niente scrittura
        if not lines:
            return EntryResult(success=True, entry_id=None, protocol=None)

        entry = EntryDTO(
            date=period["end_date"],
            descrizione=descrizione,
            lines=lines,
        )
        return self.engine.post(entry, user_id, self._accounts, self._periods, self._entries, protocol_series="CLOSE")

    def _post_opening_balance_entry(self, prev_year: str, year: str, user_id: str, descrizione: str) -> EntryResult:
        """
        Riporta i saldi patrimoniali dall'anno precedente (finalizzato) come scrittura di apertura del nuovo anno.
        I conti economici dovrebbero essere a zero (chiusi a PN).
        """
        # Usa l'intero anno precedente
        prev_period = DBManager.fetch_one(
            "SELECT start_date, end_date, status FROM periods WHERE year=? AND month IS NULL",
            (prev_year,),
        )
        if not prev_period:
            return EntryResult(
                success=False,
                errors=[f"Anno precedente {prev_year} non trovato"],
                error_details=[LedgerError(ErrorCode.NOT_FOUND, f"Anno precedente {prev_year} non trovato")],
            )
        if prev_period["status"] != "finalized":
            return EntryResult(
                success=False,
                errors=[f"Anno precedente {prev_year} non finalizzato"],
                error_details=[LedgerError(ErrorCode.PERIOD_OPEN, f"Anno {prev_year} non finalizzato")],
            )

        balances = self._trial_balance(prev_period["start_date"], prev_period["end_date"])

        lines: List[LineDTO] = []
        debit_total = Decimal("0")
        credit_total = Decimal("0")

        for acc, bal in balances.items():
            st = bal["statement_type"]
            if st not in ("ASSET", "LIABILITY", "EQUITY"):
                # Escludi CE: devono già essere chiusi
                continue
            side, amount = bal["side"], bal["amount"]
            if amount == 0:
                continue
            if side == "DEBIT":
                lines.append(LineDTO(account_id=acc, dare=amount))
                debit_total += amount
            else:
                lines.append(LineDTO(account_id=acc, avere=amount))
                credit_total += amount

        # I saldi patrimoniali quadrano per definizione. Se non quadrano, è indice di errore a monte.
        if debit_total != credit_total:
            return EntryResult(
                success=False,
                errors=[f"Opening non bilanciata: D={debit_total} C={credit_total}"],
                error_details=[LedgerError(ErrorCode.UNBALANCED_ENTRY, "Opening non bilanciata")],
            )

        if not lines:
            # Nessun saldo da riportare
            return EntryResult(success=True, entry_id=None, protocol=None)

        entry = EntryDTO(
            date=f"{year}-01-01",
            descrizione=descrizione,
            lines=lines,
        )
        return self.engine.post(entry, user_id, self._accounts, self._periods, self._entries, protocol_series="OPEN")

    # -------------------------
    # Trial balance computation
    # -------------------------

    def _trial_balance(self, start_date: str, end_date: str) -> Dict[str, Dict[str, object]]:
        """
        Calcola il saldo per conto nel periodo [start_date, end_date].
        Ritorna: {account_code: {"statement_type": str, "side": "DEBIT"/"CREDIT", "amount": Decimal}}
        Regola di natura:
          - ASSET/EXPENSE: natura DEBIT
          - LIABILITY/EQUITY/REVENUE: natura CREDIT
        """
        rows = DBManager.fetch_all(
            """
            SELECT a.code AS account_code, a.statement_type,
                   COALESCE(SUM(el.dare_cents), 0) AS dare_cents,
                   COALESCE(SUM(el.avere_cents), 0) AS avere_cents
            FROM accounts a
            LEFT JOIN entry_lines el ON el.account_code = a.code
            LEFT JOIN entries e ON e.id = el.entry_id
            WHERE e.date BETWEEN ? AND ?
            GROUP BY a.code, a.statement_type
            """,
            (start_date, end_date),
        )

        result: Dict[str, Dict[str, object]] = {}
        for r in rows:
            acc = r["account_code"]
            st = r["statement_type"]
            dare = Decimal(r["dare_cents"]) / Decimal(100)
            avere = Decimal(r["avere_cents"]) / Decimal(100)

            # Natura
            if st in ("ASSET", "EXPENSE"):
                # saldo = dare - avere; lato = DEBIT se positivo
                net = dare - avere
                if net >= 0:
                    side = "DEBIT"
                    amount = net
                else:
                    side = "CREDIT"
                    amount = -net
            else:
                # natura credit: saldo = avere - dare; lato = CREDIT se positivo
                net = avere - dare
                if net >= 0:
                    side = "CREDIT"
                    amount = net
                else:
                    side = "DEBIT"
                    amount = -net

            result[acc] = {"statement_type": st, "side": side, "amount": amount}
        return result
    
    


# -------------------------
# Usage notes (non eseguibile)
# -------------------------
# - I metodi non “indovinano” gli assestamenti: AccrualItem/DeferralItem/AmortizationItem
#   sono input espliciti dell’utente power‑user, coerenti con la filosofia del sistema.
# - La chiusura CE calcola i saldi reali e li azzera contro patrimonio netto (utile/perdita).
# - L’apertura riporta solo i saldi patrimoniali dall’anno finalizzato precedente.
# - Il servizio non scrive direttamente su audit_log: usa AuditService.
# - Ogni scrittura passa dal PostingEngine con validazioni applicate e idempotenza opzionale.
