# db/db_manager.py
import sqlite3
import threading
import pathlib
import time
from contextlib import contextmanager
from typing import Optional, Callable, Iterable, Sequence

BASE_DIR = pathlib.Path(__file__).parent
SCHEMA_SQL = pathlib.Path("db/schema_accounting.sql").read_text(encoding="utf-8")
CHART_SQL = pathlib.Path("db/chart_of_accounts.sql").read_text(encoding="utf-8")
DB_PATH_DEFAULT = "contaIDE.db"
_lock = threading.Lock()

MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None] | str]] = [
    (1, "Add index on entries(protocol)", """
        CREATE INDEX IF NOT EXISTS idx_entries_protocol ON entries(protocol);
    """),
    (2, "Add index on entry_lines(entry_id)", """
        CREATE INDEX IF NOT EXISTS idx_entry_lines_entry ON entry_lines(entry_id);
    """),
]

class DBManager:
    _conn: Optional[sqlite3.Connection] = None
    _path: str = DB_PATH_DEFAULT
    _max_retries: int = 5
    _retry_backoff_s: float = 0.15

    @classmethod
    def configure(cls, path: str = DB_PATH_DEFAULT, max_retries: int = 5, retry_backoff_s: float = 0.15):
        cls._path = path
        cls._max_retries = max_retries
        cls._retry_backoff_s = retry_backoff_s
        cls._conn = None  # reset cached connection


    @classmethod
    def _open_connection(cls, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(
    db_path,
    timeout=30.0,
    isolation_level=None,
    uri=True,                  # needed if you use file:memdb?mode=memory&cache=shared
    check_same_thread=False    # allow connection to be used across threads
)

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if db_path != ":memory__":
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = FULL;")
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    @classmethod
    def connect(cls, path: Optional[str] = None) -> sqlite3.Connection:
        """
        Connect to the database. Cache a single connection per configured path.
        For ':memory:' also cache, so schema and queries share the same DB.
        If the cached connection was closed, transparently reopen it.
        """
        db_path = path or cls._path
        with _lock:
            if cls._conn is None:
                cls._conn = cls._open_connection(db_path)
            else:
                # Safety guard: check if connection is still alive
                try:
                    cls._conn.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    # Reopen transparently if closed
                    cls._conn = cls._open_connection(db_path)
            return cls._conn

    @classmethod
    @contextmanager
    def transaction(cls):
        conn = cls.connect()
        cur = conn.cursor()
        attempt = 0
        while True:
            try:
                cur.execute("BEGIN IMMEDIATE;")
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt >= cls._max_retries:
                        cur.close()
                        raise
                    time.sleep(cls._retry_backoff_s * (2 ** attempt))
                    attempt += 1
                    continue
                cur.close()
                raise
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @classmethod
    def execute_script(cls, script: str, path: Optional[str] = None):
        conn = cls.connect(path)
        cur = conn.cursor()
        cur.executescript(script)
        conn.commit()
        cur.close()

    @classmethod
    def fetch_one(cls, sql: str, params: tuple = (), path: Optional[str] = None) -> Optional[sqlite3.Row]:
        conn = cls.connect(path)
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return row

    @classmethod
    def fetch_all(cls, sql: str, params: tuple = (), path: Optional[str] = None) -> list[sqlite3.Row]:
        conn = cls.connect(path)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    @classmethod
    def bulk_insert(cls, sql: str, rows: Iterable[Sequence], path: Optional[str] = None):
        conn = cls.connect(path)
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE;")
            cur.executemany(sql, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    # --- Migrations ---

    @classmethod
    def _ensure_migrations_table(cls):
        conn = cls.connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now')),
                description TEXT
            );
        """)
        conn.commit()
        cur.close()

    @classmethod
    def _current_version(cls) -> int:
        cls._ensure_migrations_table()
        row = cls.fetch_one("SELECT MAX(version) AS v FROM schema_migrations")
        return int(row["v"]) if row and row["v"] is not None else 0

    @classmethod
    def _apply_migration(cls, version: int, description: str, mig: Callable[[sqlite3.Connection], None] | str):
        conn = cls.connect()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE;")
            if isinstance(mig, str):
                cur.executescript(mig)
            else:
                mig(conn)
            cur.execute("INSERT INTO schema_migrations(version, description) VALUES (?, ?)", (version, description))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @classmethod
    def migrate(cls):
        cls._ensure_migrations_table()
        current = cls._current_version()
        for version, description, mig in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version > current:
                cls._apply_migration(version, description, mig)

    # --- Initialization ---

    @classmethod
    def initialize(cls):
        # Always create schema
        cls.execute_script(SCHEMA_SQL)

        # Seed chart only if accounts table is empty
        count = cls.fetch_one("SELECT COUNT(*) AS c FROM accounts")["c"]
        if count == 0:
            cls.execute_script(CHART_SQL)
        else:
            # Ensure required codes exist, insert missing ones only
            must_have = ["1000", "2000", "3000", "4000"]
            rows = cls.fetch_all(
                "SELECT code FROM accounts WHERE code IN ({})".format(",".join("?"*len(must_have))),
                tuple(must_have)
            )
            present = {r["code"] for r in rows}
            missing = [c for c in must_have if c not in present]
            if missing:
                cls.execute_script(CHART_SQL.replace("INSERT INTO accounts", "INSERT OR IGNORE INTO accounts"))

        # Run migrations
        cls.migrate()

        # Ensure an open period exists
        conn = cls.connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO periods(year, month, start_date, end_date, status)
            VALUES (strftime('%Y','now'), NULL,
                    strftime('%Y','now') || '-01-01',
                    strftime('%Y','now') || '-12-31',
                    'open')
        """)
        conn.commit()
        cur.close()


    @classmethod
    def close(cls):
        with _lock:
            if cls._conn:
                try:
                    cls._conn.execute("PRAGMA wal_checkpoint(FULL);")
                except Exception:
                    pass
                cls._conn.close()
                cls._conn = None
