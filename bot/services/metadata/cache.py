import json
import logging
import os
import sqlite3
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MetadataCache:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "..", "films.db")
        self._local = threading.local()

    def _conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_cache (
                    query TEXT PRIMARY KEY,
                    caption TEXT
                )
            """)
            self._local.conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata_cache (
                    query TEXT PRIMARY KEY,
                    metadata TEXT
                )
            """)
            self._local.conn.commit()
        return self._local.conn

    def get_caption(self, query: str) -> Optional[str]:
        try:
            cur = self._conn().execute(
                "SELECT caption FROM ai_cache WHERE query = ?", (query.lower(),))
            row = cur.fetchone()
            if row:
                return row[0]
        except Exception:
            pass
        return None

    def save_caption(self, query: str, caption: str):
        try:
            self._conn().execute(
                "INSERT OR REPLACE INTO ai_cache (query, caption) VALUES (?, ?)",
                (query.lower(), caption))
            self._conn().commit()
        except Exception as e:
            logger.error(f"Cache save error: {e}")

    def get_metadata(self, query: str) -> Optional[dict]:
        try:
            row = self._conn().execute(
                "SELECT metadata FROM metadata_cache WHERE query = ?", (query.lower(),)).fetchone()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return None

    def save_metadata(self, query: str, metadata: dict):
        try:
            self._conn().execute(
                "INSERT OR REPLACE INTO metadata_cache (query, metadata) VALUES (?, ?)",
                (query.lower(), json.dumps(metadata)))
            self._conn().commit()
        except Exception as e:
            logger.error(f"Cache save error: {e}")

    def get_setting(self, key: str, default: str = "") -> str:
        try:
            self._conn().execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur = self._conn().execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
        except Exception as e:
            logger.error(f"Get setting error: {e}")
        return default

    def set_setting(self, key: str, value: str):
        try:
            self._conn().execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            self._conn().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            self._conn().commit()
        except Exception as e:
            logger.error(f"Set setting error: {e}")