# tests/test_audit_service.py
import json
import pytest
from services.audit_service import AuditService
from db.db_manager import DBManager

@pytest.fixture
def audit():
    return AuditService()

def test_log_action_and_verify_chain(audit):
    # Pulizia audit_log
    conn = DBManager.connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_log")
    conn.commit()

    payload = {"test": "value"}
    audit.log_action("TEST_ACTION", "user1", payload, entry_id=1)

    # Verifica che sia stato inserito
    rows = DBManager.fetch_all("SELECT * FROM audit_log WHERE entry_id=?", (1,))
    assert len(rows) == 1
    assert json.loads(rows[0]["payload"])["test"] == "value"

    # Verifica catena
    assert audit.verify_chain(1) is True
