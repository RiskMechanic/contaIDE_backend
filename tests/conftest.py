# tests/conftest.py
import uuid
import pytest
from db.db_manager import DBManager
from services.closures_service import ClosuresService

@pytest.fixture(autouse=True, scope="function")
def setup_isolated_db():
    """
    Fresh shared in-memory DB per test function.
    Prevents cross-test contamination while keeping threads aligned.
    """
    uri = f"file:memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
    DBManager.configure(path=uri)
    DBManager.initialize()   # schema + chart_of_accounts + migrations
    yield
    DBManager.close()

@pytest.fixture(scope="session")
def shared_session_db():
    """
    Concurrency tests: one shared DB for the whole session.
    """
    uri = "file:memdb_session?mode=memory&cache=shared"
    DBManager.configure(path=uri)
    DBManager.initialize()
    yield
    DBManager.close()

@pytest.fixture
def closures():
    svc = ClosuresService()
    svc.refresh_accounts()   # <-- qui ricarichi i conti dal DB
    return svc