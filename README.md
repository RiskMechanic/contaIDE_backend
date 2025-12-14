# ContaIDEv2 – Accounting Backend

Enterprise‑grade accounting backend in Python + SQLite.  
Gestisce operazioni contabili (fatture, incassi, pagamenti, spese bancarie, storni, chiusure periodi) con audit log, idempotenza e protocolli incrementali.  
Progettato per essere **robusto, auditable e estendibile**.

---

## ✨ Features

- **Posting Engine**: unico punto di accesso al DB, garantisce bilanciamento dare/avere e audit chain.
- **Ledger Service**: API Python per fatture, incassi, pagamenti, storni.
- **Closures Service**: chiusure mensili/annuali, accruals, apertura nuovo esercizio.
- **Audit Service**: hash chain per tamper‑evidence.
- **Idempotenza**: evita doppie registrazioni con chiavi uniche.
- **Schema SQL**: vincoli, indici e trigger per integrità e sicurezza.
- **Test suite**: oltre 20 test automatici per invarianti e flussi completi.

---

## ⚙️ Requirements

- Python 3.11+ (testato anche su 3.14)
- SQLite (integrato)
- [pytest](https://docs.pytest.org/) per test

