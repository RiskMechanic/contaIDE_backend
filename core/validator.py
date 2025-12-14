# core/validator.py
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Protocol
import re

from core.models import EntryDTO, LedgerError, ErrorCode

# --- Helpers ---
def q2(value: Decimal | None) -> Decimal:
    return (value or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Repository protocols (read-only) ---
class AccountRepo(Protocol):
    def exists(self, account_code: str) -> bool: ...


class PeriodRepo(Protocol):
    def is_open_by_date(self, iso_date: str) -> bool: ...


class EntryRepo(Protocol):
    def exists(self, entry_id: int) -> bool: ...
    def has_reversal_for(self, original_entry_id: int) -> bool: ...


# --- Validation rules ---
def validate_balanced(entry: EntryDTO) -> List[LedgerError]:
    total_dare = Decimal("0.00")
    total_avere = Decimal("0.00")
    for l in entry.lines:
        total_dare += q2(l.dare)
        total_avere += q2(l.avere)

    if total_dare != total_avere:
        return [LedgerError(
            ErrorCode.UNBALANCED,
            f"Entry non bilanciata: Dare={total_dare}, Avere={total_avere}"
        )]
    return []


def validate_no_negative(entry: EntryDTO) -> List[LedgerError]:
    errors: List[LedgerError] = []
    for l in entry.lines:
        if l.dare < 0 or l.avere < 0:
            errors.append(LedgerError(
                ErrorCode.NEGATIVE_AMOUNT,
                f"Valore negativo su account {l.account_id}"
            ))
        if l.dare > 0 and l.avere > 0:
            errors.append(LedgerError(
                ErrorCode.AMBIGUOUS_LINE,
                f"Riga ambigua su account {l.account_id}: dare e avere > 0"
            ))
        if l.dare == 0 and l.avere == 0:
            errors.append(LedgerError(
                ErrorCode.EMPTY_LINES,
                f"Riga nulla su account {l.account_id}: dare e avere = 0"
            ))
    return errors


def validate_accounts_exist(entry: EntryDTO, accounts: AccountRepo) -> List[LedgerError]:
    return [
        LedgerError(ErrorCode.INVALID_ACCOUNT, f"Account {l.account_id} non esiste")
        for l in entry.lines
        if not accounts.exists(l.account_id)
    ]


def validate_period_open(entry: EntryDTO, periods: PeriodRepo) -> List[LedgerError]:
    if not isinstance(entry.date, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", entry.date):
        return [LedgerError(ErrorCode.INVALID_DATE, f"Data non valida: {entry.date}")]
    if not periods.is_open_by_date(entry.date):
        return [LedgerError(ErrorCode.PERIOD_CLOSED, f"Periodo chiuso per data {entry.date}")]
    return []


def validate_not_already_reversed(entry: EntryDTO, entries: EntryRepo) -> List[LedgerError]:
    if entry.reversal_of:
        if not entries.exists(entry.reversal_of):
            return [LedgerError(ErrorCode.NOT_FOUND, f"Entry {entry.reversal_of} non esiste")]
        if entries.has_reversal_for(entry.reversal_of):
            return [LedgerError(ErrorCode.ALREADY_REVERSED, f"L'entry {entry.reversal_of} è già stata stornata")]
    return []


def validate_vat_consistency(entry: EntryDTO) -> List[LedgerError]:
    """
    Optional VAT consistency rule:
    If taxable_amount, vat_rate, vat_amount are provided, enforce vat_amount == taxable_amount * vat_rate (rounded).
    """
    if entry.taxable_amount is None or entry.vat_rate is None or entry.vat_amount is None:
        return []
    expected = q2(q2(entry.taxable_amount) * q2(entry.vat_rate))
    actual = q2(entry.vat_amount)
    if expected != actual:
        return [LedgerError(
            ErrorCode.VAT_MISMATCH,
            f"IVA incoerente: attesa={expected}, trovata={actual}"
        )]
    return []


# --- Composite validator ---
def validate(entry: EntryDTO, accounts: AccountRepo, periods: PeriodRepo, entries: EntryRepo) -> List[LedgerError]:
    errors: List[LedgerError] = []
    errors += validate_balanced(entry)
    errors += validate_no_negative(entry)
    errors += validate_accounts_exist(entry, accounts)
    errors += validate_period_open(entry, periods)
    errors += validate_not_already_reversed(entry, entries)
    errors += validate_vat_consistency(entry)
    return errors
