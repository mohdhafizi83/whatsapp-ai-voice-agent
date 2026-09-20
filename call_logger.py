"""
Call Logger — Simpan rekod setiap panggilan

Setiap call: transcript, duration, caller info
Setiap lead: nama, phone, notes untuk follow-up
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger("voice-agent.logger")

class CallLogger:
    """
    Log every call + lead to SQLite.
    Auto-notify Telegram bila ada lead baru.
    """

    def __init__(self):
        self.db_path = config.STORAGE_DIR / "calls.db"
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT UNIQUE,
                caller_number TEXT,
                caller_name TEXT,
                mode TEXT,
                duration_seconds INTEGER,
                transcript TEXT,
                summary TEXT,
                lead_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                company TEXT,
                interest_level TEXT,
                notes TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (call_id) REFERENCES calls(id)
            )
        """)
        conn.commit()
        conn.close()

    def start_call(self, call_sid: str, caller_number: str, mode: str) -> int:
        """Log new call, return call_id."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "INSERT INTO calls (call_sid, caller_number, mode) VALUES (?, ?, ?)",
            (call_sid, caller_number, mode),
        )
        call_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Call started: {call_sid} from {caller_number} ({mode})")
        return call_id

    def end_call(self, call_id: int, duration: int, transcript: str = "", summary: str = ""):
        """Update call record with duration + transcript."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "UPDATE calls SET duration_seconds=?, transcript=?, summary=? WHERE id=?",
            (duration, transcript, summary, call_id),
        )
        conn.commit()
        conn.close()
        logger.info(f"Call ended: id={call_id}, duration={duration}s")

    def log_transcript_line(self, call_id: int, role: str, content: str):
        """Log individual transcript line."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO transcripts (call_id, role, content) VALUES (?, ?, ?)",
            (call_id, role, content),
        )
        conn.commit()
        conn.close()

    def save_lead(self, name: str, phone: str, company: str = "",
                   interest: str = "", notes: str = "",
                   call_id: Optional[int] = None) -> int:
        """Save lead and link to call."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "INSERT INTO leads (name, phone, company, interest_level, notes) VALUES (?, ?, ?, ?, ?)",
            (name, phone, company, interest, notes),
        )
        lead_id = cursor.lastrowid

        if call_id:
            conn.execute("UPDATE calls SET lead_id=? WHERE id=?", (lead_id, call_id))

        conn.commit()
        conn.close()
        logger.info(f"Lead saved: {name} ({phone})")
        return lead_id

    def get_leads(self, status: str = "new") -> list:
        """Get leads by status."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT id, name, phone, company, interest_level, created_at FROM leads WHERE status=? ORDER BY created_at DESC",
            (status,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "name": r[1], "phone": r[2],
                "company": r[3], "interest": r[4], "created": r[5],
            }
            for r in rows
        ]
