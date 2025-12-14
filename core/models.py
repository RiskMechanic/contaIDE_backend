from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from datetime import datetime, timezone

class ErrorCode(str, Enum):
    UNBALANCED = "UNBALANCED"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    PERIOD_CLOSED = "PERIOD_CLOSED"
    ALREADY_REVERSED = "ALREADY_REVERSED"
    AMBIGUOUS_LINE = "AMBIGUOUS_LINE"
    EMPTY_LINES = "EMPTY_LINES"
    DB_ERROR = "DB_ERROR"
    IDEMPOTENCE_CONFLICT = "IDEMPOTENCE_CONFLICT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    INVALID_DATE = "INVALID_DATE"       # new
    NOT_FOUND = "NOT_FOUND"             # new
    VAT_MISMATCH = "VAT_MISMATCH"       # new
    INVALID_INPUT = "INVALID_INPUT"



@dataclass(frozen=True)
class LedgerError:
    code: ErrorCode
    message: str
    details: Optional[dict] = None

@dataclass(frozen=True)
class LineDTO:
    account_id: str
    dare: Decimal = Decimal("0")
    avere: Decimal = Decimal("0")
    narration: Optional[str] = None

@dataclass(frozen=True)
class EntryDTO:
    date: str
    descrizione: str
    lines: List[LineDTO]
    documento: Optional[str] = None
    document_date: Optional[str] = None
    cliente_fornitore: Optional[str] = None
    reversal_of: Optional[int] = None
    client_reference_id: Optional[str] = None
    taxable_amount: Optional[Decimal] = None
    vat_rate: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    # Enterprise-grade additions
    period: Optional[str] = None
    protocol_series: Optional[str] = None
    idempotence_key: Optional[str] = None
    correlation_id: Optional[str] = None

@dataclass(frozen=True)
class EntryResult:
    success: bool
    entry_id: Optional[int] = None
    protocol: Optional[str] = None
    error_details: List[LedgerError] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
