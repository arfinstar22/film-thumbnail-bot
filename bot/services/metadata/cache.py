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

    def save_movie_post(
        self,
        title: str,
        year: Optional[int],
        rating: Optional[str],
        genre: Optional[str],
        quality: Optional[str],
        channel_username: str,
        message_id: int,
        caption: str
    ):
        try:
            conn = self._conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS movie_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    year INTEGER,
                    rating TEXT,
                    genre TEXT,
                    quality TEXT,
                    channel_username TEXT,
                    message_id INTEGER,
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                INSERT INTO movie_catalog (title, year, rating, genre, quality, channel_username, message_id, caption)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, year, rating, genre, quality, channel_username, message_id, caption))
            conn.commit()
        except Exception as e:
            logger.error(f"Save movie catalog error: {e}")

    def search_catalog(self, query: str = "", limit: int = 8):
        results = []
        try:
            conn = self._conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS movie_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    year INTEGER,
                    rating TEXT,
                    genre TEXT,
                    quality TEXT,
                    channel_username TEXT,
                    message_id INTEGER,
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            q = (query or "").strip()
            if q:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption
                    FROM movie_catalog
                    WHERE title LIKE ? OR caption LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (f"%{q}%", f"%{q}%", limit))
            else:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption
                    FROM movie_catalog
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))

            for row in cur.fetchall():
                results.append({
                    "title": row[0],
                    "year": row[1],
                    "rating": row[2],
                    "genre": row[3],
                    "quality": row[4],
                    "channel_username": row[5],
                    "message_id": row[6],
                    "caption": row[7]
                })
        except Exception as e:
            logger.error(f"Search catalog error: {e}")
        return results