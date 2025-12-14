# kernel/accounting_kernel.py
from typing import Optional
from core.models import EntryDTO, EntryResult, LedgerError, ErrorCode
from core.validator import validate
from core.posting_engine import PostingEngine
from kernel.validator_adapter import AccountsRepoDB, PeriodsRepoDB, EntriesRepoDB


class AccountingKernel:
    """
    Central coordinator for accounting flows.
    - Stateless validation (pure core rules)
    - PostingEngine as the single DB writer
    - DB-backed repos wired here (DI-friendly)
    """

    def __init__(
        self,
        posting_engine: Optional[PostingEngine] = None,
        accounts_repo: Optional[AccountsRepoDB] = None,
        periods_repo: Optional[PeriodsRepoDB] = None,
        entries_repo: Optional[EntriesRepoDB] = None,
    ):
        self.posting_engine = posting_engine or PostingEngine()
        self.accounts_repo = accounts_repo or AccountsRepoDB()
        self.periods_repo = periods_repo or PeriodsRepoDB()
        self.entries_repo = entries_repo or EntriesRepoDB()

    def process_entry(
        self,
        entry: EntryDTO,
        user_id: str,
        protocol_series: str = "GEN",
        idempotence_key: Optional[str] = None,
    ) -> EntryResult:
        """
        1) Validate using DB-backed repos
        2) Post through single DB writer (PostingEngine)
        """
        errors = validate(entry, self.accounts_repo, self.periods_repo, self.entries_repo)
        if errors:
            return EntryResult(
                success=False,
                errors=[e.message for e in errors],
                error_details=errors,
            )

        result: EntryResult = self.posting_engine.post(
            entry,
            user_id,
            self.accounts_repo,
            self.periods_repo,
            self.entries_repo,
            protocol_series=protocol_series,
            idempotence_key=idempotence_key,
        )
        return result
