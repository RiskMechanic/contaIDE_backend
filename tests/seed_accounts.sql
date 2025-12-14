-- seed_accounts.sql
-- Crea la tabella accounts se non esiste
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

-- Inserisci i conti minimi
INSERT OR IGNORE INTO accounts(code, name, statement_type, is_leaf)
VALUES
  ('1000','Cassa','ASSET',1),
  ('2000','Debiti','LIABILITY',1),
  ('4000','Ricavi','REVENUE',1),
  ('6000','Costi','EXPENSE',1),
  ('9999','Patrimonio netto','EQUITY',1);
