# services/reporting_service.py
from typing import Dict, Any, List
from db.db_manager import DBManager

class ReportingService:
    def trial_balance(self) -> List[Dict[str, Any]]:
        conn = DBManager.connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT account_code,
                   SUM(dare) AS dare_total,
                   SUM(avere) AS avere_total
            FROM entry_lines
            GROUP BY account_code
            ORDER BY account_code
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def account_ledger(self, account_code: str) -> List[Dict, Any]:
        conn = DBManager.connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT e.date, e.protocol, el.dare, el.avere
            FROM entry_lines el
            JOIN entries e ON e.id = el.entry_id
            WHERE el.account_code = ?
            ORDER BY e.date, e.id
        """, (account_code,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
