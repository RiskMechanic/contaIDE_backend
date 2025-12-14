-- db/schema_accounting.sql
-- Enterprise-grade accounting schema (SQLite)
-- Copy-paste and run as a single script. Idempotent where possible.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

-- ----------------------------
-- Accounts (hierarchical chart)
-- ----------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    class TEXT CHECK(class IN ('A','P','C','R')),
    parent_code TEXT REFERENCES accounts(code),
    is_leaf INTEGER NOT NULL DEFAULT 1,
    statement_type TEXT CHECK(statement_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE'))
);

CREATE INDEX IF NOT EXISTS idx_accounts_code ON accounts(code);
CREATE INDEX IF NOT EXISTS idx_accounts_parent ON accounts(parent_code);
CREATE INDEX IF NOT EXISTS idx_accounts_statement_type ON accounts(statement_type);

-- Optional: parent existence consistency
CREATE TRIGGER IF NOT EXISTS trg_accounts_parent_exists
BEFORE INSERT ON accounts
FOR EACH ROW
WHEN NEW.parent_code IS NOT NULL
BEGIN
    SELECT CASE
        WHEN (SELECT 1 FROM accounts WHERE code = NEW.parent_code) IS NULL
        THEN RAISE(ABORT, 'Parent account does not exist')
    END;
END;

-- ----------------------------
-- Period registry and locks
-- ----------------------------
CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    month INTEGER, 
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT CHECK(status IN ('open','closed','finalized')) NOT NULL DEFAULT 'open',
    UNIQUE(year, month)
);

CREATE TABLE IF NOT EXISTS period_locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    month INTEGER,
    locked_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    UNIQUE(year, month)
);

-- ----------------------------
-- Entries (journal)
-- ----------------------------
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                     -- ISO YYYY-MM-DD
    year TEXT,                              -- derived from date (YYYY)
    protocol TEXT,                          -- formatted display (e.g., 2025/GEN/000001)
    protocol_series TEXT,                   -- e.g., GEN, VAT, PAY
    protocol_no INTEGER,                    -- sequential per (year, series)
    document TEXT,
    document_date TEXT,
    party TEXT,
    description TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    reversal_of INTEGER,
    client_reference_id TEXT UNIQUE,
    taxable_amount REAL,                    -- optional payload attributes
    vat_rate REAL,
    vat_amount REAL,
    document_type TEXT,
    FOREIGN KEY(reversal_of) REFERENCES entries(id)
);

CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entries_protocol ON entries(year, protocol_series, protocol_no);

-- Prevent posting into closed periods (belt-and-braces)
CREATE TRIGGER IF NOT EXISTS trg_entries_prevent_closed
BEFORE INSERT ON entries
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM periods
            WHERE status IN ('closed','finalized')
              AND date(NEW.date) BETWEEN date(start_date) AND date(end_date)
        )
        THEN RAISE(ABORT, 'Posting in closed/finalized period is not allowed')
    END;
END;

-- ----------------------------
-- Entry lines (integer cents)
-- ----------------------------
CREATE TABLE IF NOT EXISTS entry_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    account_code TEXT NOT NULL,
    dare_cents INTEGER DEFAULT 0 CHECK (dare_cents >= 0),
    avere_cents INTEGER DEFAULT 0 CHECK (avere_cents >= 0),
    CHECK (NOT (dare_cents > 0 AND avere_cents > 0)),
    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY(account_code) REFERENCES accounts(code)
);

CREATE INDEX IF NOT EXISTS idx_entry_lines_entry ON entry_lines(entry_id);
CREATE INDEX IF NOT EXISTS idx_entry_lines_account ON entry_lines(account_code);

-- ----------------------------
-- Protocol counters (by year+series)
-- ----------------------------
CREATE TABLE IF NOT EXISTS protocol_counters (
    year TEXT NOT NULL,
    series TEXT NOT NULL,
    counter INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (year, series)
);

-- ----------------------------
-- Reversal linkage (explicit)
-- ----------------------------
CREATE TABLE IF NOT EXISTS entry_reversals (
    entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    reversal_of INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_reversal_of_unique ON entry_reversals(reversal_of);
CREATE INDEX IF NOT EXISTS ix_entry_reversals_rev_of ON entry_reversals(reversal_of);

-- ----------------------------
-- Idempotence registry
-- ----------------------------
CREATE TABLE IF NOT EXISTS idempotence (
    key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    protocol TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_idemp_entry ON idempotence(entry_id);

-- ----------------------------
-- Audit log
-- ----------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER,
    action TEXT,
    user_id TEXT,
    payload TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    prev_hash TEXT,     -- optional tamper-evidence
    curr_hash TEXT      -- optional tamper-evidence
);

CREATE INDEX IF NOT EXISTS idx_audit_entry ON audit_log(entry_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);

-- ----------------------------
-- Closing entries registry
-- ----------------------------
CREATE TABLE IF NOT EXISTS closing_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
    entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE, -- nullable: planning before posting
    type TEXT CHECK(type IN ('monthly','yearly','reopen')) NOT NULL,
    created_at TEXT NOT NULL
);

-- ----------------------------
-- Helper views (optional)
-- ----------------------------
CREATE VIEW IF NOT EXISTS v_trial_balance AS
SELECT
    el.account_code,
    SUM(el.dare_cents) AS dare_cents_total,
    SUM(el.avere_cents) AS avere_cents_total
FROM entry_lines el
GROUP BY el.account_code;

CREATE VIEW IF NOT EXISTS v_entries_with_lines AS
SELECT
    e.id AS entry_id, e.date, e.protocol, e.protocol_series, e.protocol_no,
    el.account_code, el.dare_cents, el.avere_cents
FROM entries e
JOIN entry_lines el ON el.entry_id = e.id;

-- ----------------------------
-- Seed default annual period
-- ----------------------------
INSERT OR IGNORE INTO periods(year, month, start_date, end_date, status)
VALUES (CAST(strftime('%Y','now') AS INTEGER), NULL,
        strftime('%Y','now') || '-01-01',
        strftime('%Y','now') || '-12-31',
        'open');
