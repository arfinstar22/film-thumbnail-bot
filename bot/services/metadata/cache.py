import json
import logging
import os
import re
import sqlite3
import threading
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def normalize_movie_title_and_year(title: str, year: Optional[int] = None):
    t = (title or "").strip()
    m = re.search(r'[\(\[]\s*(\d{4})\s*[\)\]]$', t)
    if m:
        if not year:
            try:
                year = int(m.group(1))
            except ValueError:
                pass
        t = t[:m.start()].strip()
    clean_key = re.sub(r'[^a-zA-Z0-9]', '', t).lower()
    return t, year, clean_key


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

    def _ensure_catalog_table(self, conn):
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
                file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN file_id TEXT")
        except Exception:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_chan_msg ON movie_catalog (channel_username, message_id)")

    def save_movie_post(
        self,
        title: str,
        year: Optional[int],
        rating: Optional[str],
        genre: Optional[str],
        quality: Optional[str],
        channel_username: str,
        message_id: int,
        caption: str,
        file_id: Optional[str] = None
    ):
        clean_channel = (channel_username or "").lstrip("@").strip().lower()
        clean_title, year, _ = normalize_movie_title_and_year(title, year)
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            cur = conn.execute("SELECT id, file_id FROM movie_catalog WHERE LOWER(channel_username) = ? AND message_id = ?", (clean_channel, message_id))
            row = cur.fetchone()
            if row:
                if file_id and not row[1]:
                    conn.execute("UPDATE movie_catalog SET file_id = ? WHERE id = ?", (file_id, row[0]))
                    conn.commit()
                return

            conn.execute("""
                INSERT INTO movie_catalog (title, year, rating, genre, quality, channel_username, message_id, caption, file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (clean_title, year, rating, genre, quality, clean_channel, message_id, caption, file_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Save movie catalog error: {e}")

    def delete_movie_posts(self, message_ids: List[int]) -> List[str]:
        """Delete records from movie_catalog by message_ids and return affected channel usernames."""
        if not message_ids:
            return []
        affected_channels = []
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            placeholders = ",".join("?" for _ in message_ids)
            cur = conn.execute(f"SELECT DISTINCT channel_username FROM movie_catalog WHERE message_id IN ({placeholders})", list(message_ids))
            affected_channels = [r[0] for r in cur.fetchall() if r[0]]
            if affected_channels:
                conn.execute(f"DELETE FROM movie_catalog WHERE message_id IN ({placeholders})", list(message_ids))
                conn.commit()
                logger.info(f"Deleted {len(message_ids)} message IDs from catalog, affected channels: {affected_channels}")
        except Exception as e:
            logger.error(f"Delete movie posts error: {e}")
        return affected_channels

    def get_deduplicated_catalog(self, channel_username: str) -> List[Dict[str, Any]]:
        """Retrieve unique movies for a channel, automatically keeping only the latest post for duplicates."""
        raw_items = []
        clean_channel = (channel_username or "").lstrip("@").strip().lower()
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            cur = conn.execute("""
                SELECT title, year, rating, genre, quality, channel_username, message_id, caption, file_id
                FROM movie_catalog
                WHERE LOWER(channel_username) = ?
                ORDER BY message_id DESC
            """, (clean_channel,))

            for row in cur.fetchall():
                raw_items.append({
                    "title": row[0],
                    "year": row[1],
                    "rating": row[2],
                    "genre": row[3],
                    "quality": row[4],
                    "channel_username": row[5],
                    "message_id": row[6],
                    "caption": row[7],
                    "file_id": row[8]
                })
        except Exception as e:
            logger.error(f"Get deduplicated catalog error: {e}")
            return []

        seen_keys = {}
        dedup_results = []
        for item in raw_items:
            t, y, key = normalize_movie_title_and_year(item["title"], item["year"])
            if not key:
                continue

            is_dup = False
            if key in seen_keys:
                prev_y = seen_keys[key].get("year")
                if not prev_y or not y or prev_y == y:
                    is_dup = True

            if is_dup:
                target = seen_keys[key]
                if not target.get("year") and y:
                    target["year"] = y
                if not target.get("rating") and item.get("rating"):
                    target["rating"] = item.get("rating")
                if not target.get("genre") and item.get("genre"):
                    target["genre"] = item.get("genre")
            else:
                item_copy = dict(item)
                item_copy["title"] = t
                item_copy["year"] = y
                seen_keys[key] = item_copy
                dedup_results.append(item_copy)

        dedup_results.sort(key=lambda x: (x.get("title") or "").lower())
        return dedup_results

    def search_catalog(self, query: str = "", limit: int = 8) -> List[Dict[str, Any]]:
        raw_items = []
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            q = (query or "").strip()
            if q:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption
                    FROM movie_catalog
                    WHERE title LIKE ? OR caption LIKE ?
                    ORDER BY message_id DESC
                    LIMIT ?
                """, (f"%{q}%", f"%{q}%", limit * 3))
            else:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption
                    FROM movie_catalog
                    ORDER BY message_id DESC
                    LIMIT ?
                """, (limit * 3,))

            for row in cur.fetchall():
                raw_items.append({
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
            return []

        seen_keys = {}
        dedup_results = []
        for item in raw_items:
            t, y, key = normalize_movie_title_and_year(item["title"], item["year"])
            if not key:
                continue
            is_dup = False
            if key in seen_keys:
                prev_y = seen_keys[key].get("year")
                if not prev_y or not y or prev_y == y:
                    is_dup = True
            if is_dup:
                target = seen_keys[key]
                if not target.get("year") and y:
                    target["year"] = y
                if not target.get("rating") and item.get("rating"):
                    target["rating"] = item.get("rating")
                if not target.get("genre") and item.get("genre"):
                    target["genre"] = item.get("genre")
            else:
                item_copy = dict(item)
                item_copy["title"] = t
                item_copy["year"] = y
                seen_keys[key] = item_copy
                dedup_results.append(item_copy)
                if len(dedup_results) >= limit:
                    break

        return dedup_results

    def export_catalog_json(self, channel_username: str) -> str:
        """Export all movies in catalog for a channel as a formatted JSON string."""
        movies = self.get_deduplicated_catalog(channel_username)
        return json.dumps({
            "channel": (channel_username or "").lstrip("@").strip().lower(),
            "total": len(movies),
            "movies": movies
        }, indent=2, ensure_ascii=False)

    def import_catalog_json(self, json_data: str, target_channel: Optional[str] = None) -> int:
        """Import a JSON backup into the local database."""
        try:
            data = json.loads(json_data)
            movie_list = data.get("movies", [])
            imported = 0
            default_chan = target_channel or data.get("channel", "film_indonesia1")
            for m in movie_list:
                chan = target_channel or m.get("channel_username") or default_chan
                self.save_movie_post(
                    title=m.get("title", "Film"),
                    year=m.get("year"),
                    rating=m.get("rating"),
                    genre=m.get("genre"),
                    quality=m.get("quality"),
                    channel_username=chan,
                    message_id=m.get("message_id") or 0,
                    caption=m.get("caption", ""),
                    file_id=m.get("file_id")
                )
                imported += 1
            return imported
        except Exception as e:
            logger.error(f"Import catalog JSON error: {e}")
            return 0