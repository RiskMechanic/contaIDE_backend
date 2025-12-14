# core/posting_engine.py
import json
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from core.models import EntryDTO, EntryResult, LedgerError, ErrorCode
from core.validator import validate
from db.db_manager import DBManager
from services.audit_service import AuditService


# --- Helpers ---

def q2(value: Optional[Decimal]) -> Decimal:
    return (value or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def cents(value: Optional[Decimal]) -> int:
    return int(q2(value) * 100)

def canonical_payload(entry: EntryDTO, user_id: str, protocol: Optional[str]) -> dict:
    """
    Full audit payload (includes protocol); used for audit_log hashing.
    """
    return {
        "entry": {
            "date": entry.date,
            "descrizione": entry.descrizione,
            "documento": entry.documento,
            "document_date": entry.document_date,
            "cliente_fornitore": entry.cliente_fornitore,
            "reversal_of": entry.reversal_of,
            "client_reference_id": entry.client_reference_id,
            "taxable_amount": str(q2(entry.taxable_amount)) if entry.taxable_amount is not None else None,
            "vat_rate": str(q2(entry.vat_rate)) if entry.vat_rate is not None else None,
            "vat_amount": str(q2(entry.vat_amount)) if entry.vat_amount is not None else None,
            "lines": [
                {"account_code": l.account_id, "dare_cents": cents(l.dare), "avere_cents": cents(l.avere)}
                for l in entry.lines
            ],
        },
        "protocol": protocol,
        "user": user_id,
    }

def idempotence_content(entry: EntryDTO, user_id: str) -> dict:
    """
    Content payload for idempotence check (excludes protocol and timestamps).
    Ensures we can compare before allocating protocol.
    """
    return {
        "entry": {
            "date": entry.date,
            "descrizione": entry.descrizione,
            "documento": entry.documento,
            "document_date": entry.document_date,
            "cliente_fornitore": entry.cliente_fornitore,
            "reversal_of": entry.reversal_of,
            "client_reference_id": entry.client_reference_id,
            "taxable_amount": str(q2(entry.taxable_amount)) if entry.taxable_amount is not None else None,
            "vat_rate": str(q2(entry.vat_rate)) if entry.vat_rate is not None else None,
            "vat_amount": str(q2(entry.vat_amount)) if entry.vat_amount is not None else None,
            "lines": [
                {"account_code": l.account_id, "dare_cents": cents(l.dare), "avere_cents": cents(l.avere)}
                for l in entry.lines
            ],
        },
        "user": user_id,
    }

def payload_hash(payload: dict) -> str:
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --- Posting Engine ---

class PostingEngine:
    def __init__(self):
        self._audit = AuditService()

    def _next_protocol(self, cur, year: str, series: str) -> tuple[int, str]:
        """
        Atomic per-(year, series) increment. Returns (protocol_no, protocol_str).
        """
        cur.execute(
            "INSERT OR IGNORE INTO protocol_counters(year, series, counter) VALUES (?, ?, 0)",
            (year, series),
        )
        cur.execute(
            "UPDATE protocol_counters SET counter = counter + 1 WHERE year = ? AND series = ?",
            (year, series),
        )
        cur.execute(
            "SELECT counter FROM protocol_counters WHERE year = ? AND series = ?",
            (year, series),
        )
        protocol_no = int(cur.fetchone()["counter"])
        protocol_str = f"{year}/{series}/{protocol_no:06d}"
        return protocol_no, protocol_str

    def post(
        self,
        entry: EntryDTO,
        user_id: str,
        accounts_repo,
        periods_repo,
        entries_repo,
        *,
        protocol_series: Optional[str] = None,
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        # 1) Validate (read-only)
        errs = validate(entry, accounts_repo, periods_repo, entries_repo)
        if errs:
            return EntryResult(
                success=False,
                errors=[e.message for e in errs],
                error_details=errs,
            )

        try:
            # 2) Transaction (single-writer)
            with DBManager.transaction() as cur:
                year = entry.date[:4]
                series = (protocol_series or getattr(entry, "protocol_series", None) or "GEN").upper()

                # 3) Idempotence pre-check (before any mutation)
                if idempotence_key:
                    # Compute idempotence content hash
                    content_hash = payload_hash(idempotence_content(entry, user_id))
                    cur.execute(
                        "SELECT payload_hash, entry_id, protocol FROM idempotence WHERE key = ?",
                        (idempotence_key,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        if existing["payload_hash"] == content_hash:
                            # Safe retry: return existing entry/protocol without mutating
                            return EntryResult(success=True, entry_id=existing["entry_id"], protocol=existing["protocol"])
                        else:
                            # Conflict: same key, different content
                            return EntryResult(
                                success=False,
                                errors=[f"Idempotence conflict for key {idempotence_key}"],
                                error_details=[LedgerError(ErrorCode.IDEMPOTENCE_CONFLICT, f"Key {idempotence_key} payload mismatch")],
                            )

                # 4) Protocol allocation (atomic)
                protocol_no, protocol_str = self._next_protocol(cur, year, series)

                # 5) Persist entry
                cur.execute(
                    """
                    INSERT INTO entries (
                        date, year, protocol, protocol_series, protocol_no,
                        document, document_date, party, description,
                        created_by, reversal_of, client_reference_id,
                        taxable_amount, vat_rate, vat_amount, document_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.date,
                        year,
                        protocol_str,
                        series,
                        protocol_no,
                        entry.documento,
                        entry.document_date,
                        entry.cliente_fornitore,
                        entry.descrizione,
                        user_id,
                        entry.reversal_of,
                        entry.client_reference_id or idempotence_key,
                        float(q2(entry.taxable_amount)) if entry.taxable_amount is not None else None,
                        float(q2(entry.vat_rate)) if entry.vat_rate is not None else None,
                        float(q2(entry.vat_amount)) if entry.vat_amount is not None else None,
                        None,  # document_type optional placeholder
                    ),
                )
                entry_id = cur.lastrowid

                # 6) Persist lines (integer cents)
                for l in entry.lines:
                    cur.execute(
                        """
                        INSERT INTO entry_lines (entry_id, account_code, dare_cents, avere_cents)
                        VALUES (?, ?, ?, ?)
                        """,
                        (entry_id, l.account_id, cents(l.dare), cents(l.avere)),
                    )

                # 7) Reversal linkage (explicit table)
                if entry.reversal_of:
                    cur.execute(
                        "INSERT INTO entry_reversals (entry_id, reversal_of) VALUES (?, ?)",
                        (entry_id, entry.reversal_of),
                    )

                # 8) Audit tramite AuditService
                payload = canonical_payload(entry, user_id, protocol_str)
                self._audit.log_action("POST", user_id, payload, entry_id=entry_id)

                # 9) Idempotence record (store content hash + protocol)
                if idempotence_key:
                    content_hash = payload_hash(idempotence_content(entry, user_id))
                    cur.execute(
                        """
                        INSERT INTO idempotence (key, payload_hash, entry_id, protocol)
                        VALUES (?, ?, ?, ?)
                        """,
                        (idempotence_key, content_hash, entry_id, protocol_str),
                    )

            return EntryResult(success=True, entry_id=entry_id, protocol=protocol_str)

        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            code = ErrorCode.IDEMPOTENCE_CONFLICT if "Idempotence conflict" in msg else ErrorCode.DB_ERROR
            return EntryResult(success=False, errors=[msg], error_details=[LedgerError(code, msg)])
