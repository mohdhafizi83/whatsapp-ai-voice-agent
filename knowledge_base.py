"""
Knowledge Base — RAG untuk Interview Mode

Menyimpan dan retrieve dokumen peribadi (CV, portfolio, personal notes)
guna vector search mudah.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger("voice-agent.knowledge")

class KnowledgeBase:
    """
    Simple knowledge base untuk interview agent.
    
    Menyimpan dokumen dalam SQLite dengan keyword indexing.
    RAG: Cari dokumen relevant → inject ke Gemini context.
    """

    def __init__(self):
        self.db_path = config.STORAGE_DIR / "knowledge.db"
        self._init_db()
        self._load_documents()

    def _init_db(self):
        """Create tables if not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE,
                content TEXT,
                category TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _load_documents(self):
        """Load documents from knowledge/ directory into DB."""
        knowledge_dir = config.KNOWLEDGE_DIR
        if not knowledge_dir.exists():
            logger.warning(f"Knowledge directory not found: {knowledge_dir}")
            return

        conn = sqlite3.connect(str(self.db_path))
        for md_file in knowledge_dir.glob("*.md"):
            title = md_file.stem
            content = md_file.read_text()
            
            conn.execute("""
                INSERT OR REPLACE INTO documents (title, content, category, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (title, content, md_file.name))
            logger.info(f"Loaded knowledge document: {title}")

        conn.commit()
        conn.close()

    def query(self, question: str, top_k: int = 3) -> str:
        """
        Cari dokumen relevant berdasarkan keyword matching.
        
        Simple approach: cari dokumen dengan keyword overlap terbanyak.
        Better approach: guna embedding + vector search (future enhancement).
        """
        words = set(question.lower().split())
        # Filter common words
        stop_words = {"yang", "dan", "di", "ke", "dengan", "untuk", "saya", "anda",
                      "ini", "itu", "apa", "ada", "dalam", "oleh", "pada", "tidak"}
        keywords = words - stop_words

        if not keywords:
            return ""

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT title, content FROM documents")
        
        scored = []
        for title, content in (cursor.fetchall() or []):
            content_lower = content.lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scored.append((score, title, content))

        conn.close()

        scored.sort(reverse=True)
        results = scored[:top_k]

        if not results:
            return ""

        # Format: Title + relevant content untuk context
        context_parts = []
        for _, title, content in results:
            # Ambil 500 chars pertama setiap dokumen
            context_parts.append(f"--- {title} ---\n{content[:1500]}")
        
        return "\n\n".join(context_parts)

    def reload(self):
        """Reload documents from filesystem."""
        self._load_documents()
        logger.info("Knowledge base reloaded")
