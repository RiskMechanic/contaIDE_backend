from db.db_manager import DBManager

def test_schema_bootstrap_creates_core_tables():
    # Spot check core tables
    conn = DBManager.connect()
    cur = conn.cursor()
    for table in [
        "accounts", "entries", "entry_lines", "periods",
        "protocol_counters", "audit_log", "idempotence", "entry_reversals",
        "schema_migrations"
    ]:
        cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
        assert cur.fetchone() is not None, f"Missing table: {table}"
    cur.close()

def test_chart_of_accounts_seeded_minimally():
    row = DBManager.fetch_one("SELECT COUNT(*) AS c FROM accounts")
    assert row["c"] > 0
