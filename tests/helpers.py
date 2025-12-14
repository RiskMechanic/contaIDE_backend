from decimal import Decimal
from datetime import date
from core.models import EntryDTO, LineDTO

def make_entry(descr="Test", amount=Decimal("100.00"), debit_code="1000", credit_code="2000", date_=None):
    return EntryDTO(
        date=(date_ or date.today().isoformat()),
        descrizione=descr,
        lines=[
            LineDTO(account_id=debit_code, dare=amount),
            LineDTO(account_id=credit_code, avere=amount),
        ],
    )

def assert_keys(row, keys):
    ks = set(row.keys())
    missing = [k for k in keys if k not in ks]
    assert not missing, f"Missing keys {missing} in row: {ks}"

def extract_errors(result) -> list[str]:
    # Normalize to list of strings for diagnostics
    errs = getattr(result, "errors", None)
    if not errs:
        return []
    if isinstance(errs, list):
        return [str(e) for e in errs]
    return [str(errs)]
