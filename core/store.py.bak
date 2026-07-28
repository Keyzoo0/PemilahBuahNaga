"""SQLite penyimpan riwayat sortasi."""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "database" / "sorting.db"


class Store:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self.lock, self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS sortings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    ripeness TEXT,
                    confidence REAL,
                    action TEXT,
                    image TEXT
                )
            """)
            c.commit()

    def add(self, ripeness, confidence, action, image=None):
        with self.lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO sortings (created_at, ripeness, confidence, action, image) VALUES (?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ripeness, confidence, action, image),
            )
            c.commit()
            return cur.lastrowid

    def recent(self, limit=100):
        with self.lock, self._conn() as c:
            rows = c.execute("SELECT * FROM sortings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def delete(self, row_id):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM sortings WHERE id=?", (row_id,))
            c.commit()
            return True

    def clear_all(self):
        with self.lock, self._conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM sortings").fetchone()["n"]
            c.execute("DELETE FROM sortings")
            c.commit()
            return n

    def counts_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock, self._conn() as c:
            rows = c.execute(
                "SELECT ripeness, COUNT(*) n FROM sortings WHERE date(created_at)=? GROUP BY ripeness",
                (today,),
            ).fetchall()
            return {r["ripeness"]: r["n"] for r in rows}


store = Store()
