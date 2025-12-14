# tests/test_benchmark_posting.py
import time
from decimal import Decimal
from core.models import EntryDTO, LineDTO
from core.posting_engine import PostingEngine
from kernel.validator_adapter import AccountsRepoDB, PeriodsRepoDB, EntriesRepoDB

def test_posting_benchmark():
    engine = PostingEngine()
    accounts = AccountsRepoDB()
    periods = PeriodsRepoDB()
    entries = EntriesRepoDB()

    user = "bench"
    n = 1000
    start = time.perf_counter()

    for i in range(n):
        entry = EntryDTO(
            date="2025-12-01",
            descrizione=f"Bench entry {i}",
            lines=[LineDTO(account_id="4000", avere=Decimal("10.00")),
                   LineDTO(account_id="1000", dare=Decimal("10.00"))]
        )
        result = engine.post(entry, user, accounts, periods, entries)
        assert result.success

    elapsed = time.perf_counter() - start
    print(f"Posted {n} entries in {elapsed:.2f}s → {n/elapsed:.1f} entries/sec")
