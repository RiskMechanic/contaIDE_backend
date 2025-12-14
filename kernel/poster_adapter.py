# kernel/poster_adapter.py
import logging
from typing import Optional
from core.models import EntryDTO, EntryResult, LedgerError, ErrorCode
from core.posting_engine import PostingEngine
from kernel.validator_adapter import AccountsRepoDB, PeriodsRepoDB, EntriesRepoDB

logger = logging.getLogger("poster_adapter")


class PosterAdapter:
    """
    Facade between services and PostingEngine.
    - Injects DB-backed repos for validation
    - Normalizes input/output
    - Supports protocol series + idempotence
    """

    def __init__(self):
        self.engine = PostingEngine()
        self._accounts = AccountsRepoDB()
        self._periods = PeriodsRepoDB()
        self._entries = EntriesRepoDB()

    def post_entry(
        self,
        entry: EntryDTO,
        user_id: str,
        *,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        if not isinstance(entry, EntryDTO):
            return EntryResult(
                success=False,
                errors=["Invalid object, must be EntryDTO"],
                error_details=[LedgerError(code=ErrorCode.INVALID_INPUT, message=str(entry))],
            )

        try:
            logger.info(
                "Posting entry: user=%s series=%s idempotence=%s descr=%s",
                user_id,
                protocol_series,
                idempotence_key,
                getattr(entry, "descrizione", None),
            )
            result: EntryResult = self.engine.post(
                entry,
                user_id,
                self._accounts,
                self._periods,
                self._entries,
                protocol_series=protocol_series,
                idempotence_key=idempotence_key,
            )
            if result.success:
                logger.info("Posted entry successfully: protocol=%s entry_id=%s", result.protocol, result.entry_id)
            else:
                logger.warning("Posting failed: errors=%s", result.errors)
            return result

        except Exception as ex:
            logger.exception("Posting exception")
            return EntryResult(
                success=False,
                errors=[str(ex)],
                error_details=[LedgerError(code=ErrorCode.DB_ERROR, message=str(ex))],
            )
