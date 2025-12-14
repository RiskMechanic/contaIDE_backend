# audit_service.py
import json
import hashlib
from datetime import datetime, timezone
from typing import Optional

from db.db_manager import DBManager


def _payload_hash(payload: dict) -> str:
    """
    Calcola l'hash SHA256 di un payload canonico.
    """
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class AuditService:
    """
    Servizio centralizzato per audit log.
    - Scrive ogni operazione in audit_log
    - Mantiene catena di hash (prev_hash → curr_hash)
    - Supporta azioni generiche (POST, CLOSE_PERIOD, OPEN_PERIOD, ecc.)
    """

    def log_action(self, action: str, user_id: str, payload: dict, entry_id: Optional[int] = None):
        """
        Registra un'azione nel log di audit.
        :param action: tipo di azione (es. POST, CLOSE_PERIOD, OPEN_PERIOD)
        :param user_id: utente responsabile
        :param payload: dati canonici dell'operazione
        :param entry_id: opzionale, id della scrittura contabile
        """
        conn = DBManager.connect()
        cur = conn.cursor()

        # Aggiungi timestamp
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Calcola hash corrente
        curr_hash = _payload_hash(payload)

        # Recupera hash precedente
        prev_hash = None
        if entry_id:
            cur.execute(
                "SELECT curr_hash FROM audit_log WHERE entry_id = ? ORDER BY id DESC LIMIT 1",
                (entry_id,),
            )
            row = cur.fetchone()
            if row and row["curr_hash"]:
                prev_hash = row["curr_hash"]

        # Inserisci record
        cur.execute(
            """
            INSERT INTO audit_log (entry_id, action, user_id, payload, prev_hash, curr_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                action,
                user_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                prev_hash,
                curr_hash,
            ),
        )
        conn.commit()
        cur.close()

    def verify_chain(self, entry_id: int) -> bool:
        """
        Verifica integrità della catena di hash per un entry_id.
        Ritorna True se la catena è coerente, False se rotta.
        """
        rows = DBManager.fetch_all(
            "SELECT id, payload, curr_hash, prev_hash FROM audit_log WHERE entry_id = ? ORDER BY id ASC",
            (entry_id,),
        )
        prev_hash = None
        for row in rows:
            payload = json.loads(row["payload"])
            expected_hash = _payload_hash(payload)
            if expected_hash != row["curr_hash"]:
                return False
            if row["prev_hash"] != prev_hash:
                return False
            prev_hash = row["curr_hash"]
        return True
