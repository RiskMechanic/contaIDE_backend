# services/ledger_query_repo.py
from decimal import Decimal
from typing import List, Optional
from contextlib import contextmanager

from core.models import EntryDTO, LineDTO
from db.db_manager import DBManager
from core.utils import q2


class LedgerQueryRepo:
    """
    Read-only repository for journal entries and lines.
    Provides snapshots for reversals and reporting.
    """

    def get_entry(self, entry_id: int) -> Optional[EntryDTO]:
        """
        Returns an EntryDTO for a given entry_id or None if not found.
        """
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, date, document AS documento, document_date,
                       party AS cliente_fornitore, description AS descrizione,
                       taxable_amount, vat_rate, vat_amount, reversal_of
                FROM entries WHERE id = ?
                """,
                (entry_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            # Ottieni righe
            lines = self.get_entry_lines(entry_id)

            # Costruisci EntryDTO coerente con LedgerService
            entry_dto = EntryDTO(
                date=row["date"],
                descrizione=row["descrizione"] or "",
                lines=lines,
                documento=row["documento"],
                document_date=row["document_date"],
                cliente_fornitore=row["cliente_fornitore"],
                taxable_amount=Decimal(row["taxable_amount"]) if row["taxable_amount"] is not None else None,
                vat_rate=Decimal(row["vat_rate"]) if row["vat_rate"] is not None else None,
                vat_amount=Decimal(row["vat_amount"]) if row["vat_amount"] is not None else None,
                reversal_of=row["reversal_of"],
            )
            return entry_dto
        finally:
            cur.close()

    def get_entry_lines(self, entry_id: int) -> List[LineDTO]:
        """
        Returns a list of LineDTO for a given entry_id.
        """
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT account_code, dare_cents, avere_cents FROM entry_lines WHERE entry_id=?",
                (entry_id,),
            )
            rows = cur.fetchall()
            lines: List[LineDTO] = []
            for row in rows:
                dare = (Decimal(row["dare_cents"]) / 100) if row["dare_cents"] else None
                avere = (Decimal(row["avere_cents"]) / 100) if row["avere_cents"] else None
                lines.append(LineDTO(account_id=row["account_code"], dare=dare, avere=avere))
            return lines
        finally:
            cur.close()

    # ---------------------------
    # Transaction wrapper helper
    # ---------------------------
    @contextmanager
    def transaction(self):
        """
        Context manager for atomic operations on ledger queries (reversal, complex reads).
        """
        with DBManager.transaction() as cur:
            yield cur

    # ---------------------------
    # Helper for reversals (storno)
    # ---------------------------
    def build_reversal(self, original_entry_id: int, descrizione: str = "Storno") -> Optional[EntryDTO]:
        """
        Costruisce un EntryDTO di reversal invertendo dare/avere.
        Copia documento, document_date e party dalla entry originale.
        """
        # Fetch originale
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM entries WHERE id = ?", (original_entry_id,))
            row = cur.fetchone()
            if not row:
                return None

            # Linee originali
            cur.execute(
                "SELECT account_code, dare_cents, avere_cents FROM entry_lines WHERE entry_id=?",
                (original_entry_id,)
            )
            lines = cur.fetchall()

            inv_lines: List[LineDTO] = []
            for l in lines:
                dare = (Decimal(l["dare_cents"]) / 100) if l["dare_cents"] else None
                avere = (Decimal(l["avere_cents"]) / 100) if l["avere_cents"] else None

                # Inversione dare/avere
                inv_lines.append(LineDTO(account_id=l["account_code"], dare=avere, avere=dare))

            # --- Punto per logiche custom ---
            # Esempio: cambiare account specifici, aggiungere linee supplementari, rettifiche
            # for line in inv_lines:
            #     if line.account_id == "XXXX":
            #         line.account_id = "YYYY"

            today = q2.today() if hasattr(q2, "today") else __import__("datetime").datetime.today().strftime("%Y-%m-%d")

            reversal_dto = EntryDTO(
                date=today,
                descrizione=descrizione,
                lines=inv_lines,
                documento=row["document"],
                document_date=row["document_date"],
                cliente_fornitore=row["party"],
                reversal_of=original_entry_id,
                taxable_amount=row.get("taxable_amount"),
                vat_rate=row.get("vat_rate"),
                vat_amount=row.get("vat_amount"),
            )

            return reversal_dto

        finally:
            cur.close()

