# kernel/validator_adapter.py
from typing import Optional
from db.db_manager import DBManager
from core.models import LedgerError, ErrorCode


class AccountsRepoDB:
    """
    Read-only account existence checks backed by DB.
    """

    def exists(self, account_code: str) -> bool:
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM accounts WHERE code = ? LIMIT 1", (account_code,))
            return cur.fetchone() is not None
        finally:
            cur.close()

    def assert_exists(self, account_code: str) -> Optional[LedgerError]:
        if not self.exists(account_code):
            return LedgerError(code=ErrorCode.NOT_FOUND, message=f"Account non trovato: {account_code}")
        return None


class PeriodsRepoDB:
    """
    Period openness checks. Returns True if date is in an open period.
    A closed period match yields False.
    """

    def is_open_by_date(self, iso_date: str) -> bool:
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT 1 FROM periods
                WHERE status='closed'
                  AND date(?) BETWEEN start_date AND end_date
                LIMIT 1
                """,
                (iso_date,),
            )
            closed_hit = cur.fetchone() is not None
            return not closed_hit
        finally:
            cur.close()

    def assert_open(self, iso_date: str) -> Optional[LedgerError]:
        if not self.is_open_by_date(iso_date):
            return LedgerError(code=ErrorCode.PERIOD_CLOSED, message=f"Periodo chiuso per data: {iso_date}")
        return None


class EntriesRepoDB:
    """
    Journal entry existence + reversal checks.
    """

    def has_reversal_for(self, original_entry_id: int) -> bool:
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM entries WHERE reversal_of = ? LIMIT 1", (original_entry_id,))
            return cur.fetchone() is not None
        finally:
            cur.close()

    def exists(self, entry_id: int) -> bool:
        conn = DBManager.connect()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM entries WHERE id = ? LIMIT 1", (entry_id,))
            return cur.fetchone() is not None
        finally:
            cur.close()

    def assert_exists(self, entry_id: int) -> Optional[LedgerError]:
        if not self.exists(entry_id):
            return LedgerError(code=ErrorCode.NOT_FOUND, message=f"Prima nota non trovata: id={entry_id}")
        return None

    def assert_not_reversed(self, original_entry_id: int) -> Optional[LedgerError]:
        if self.has_reversal_for(original_entry_id):
            return LedgerError(code=ErrorCode.ALREADY_REVERSED, message=f"Storno già presente per id={original_entry_id}")
        return None
