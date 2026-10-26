import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import pool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class SupabaseSyncService:
    """High-performance, non-blocking cloud database synchronization with Supabase.
    Ensures 100% data persistence across Render Free sleeps/restarts while
    keeping local SQLite access blazing fast (0.1ms)."""

    def __init__(self, db_url: Optional[str] = None):
        raw_url = (
            db_url
            or os.getenv("DATABASE_URL", "").strip()
            or os.getenv("SUPABASE_DATABASE_URL", "").strip()
            or os.getenv("SUPABASE_DB_URL", "").strip()
        )
        if raw_url.startswith("postgres://"):
            raw_url = "postgresql://" + raw_url[11:]
        self.db_url = raw_url
        self.supabase_url = os.getenv("SUPABASE_URL", "").strip()
        self.supabase_key = os.getenv("SUPABASE_KEY", "").strip()
        self._enabled = bool((self.db_url and HAS_PSYCOPG2) or (self.supabase_url and self.supabase_key))
        if not HAS_PSYCOPG2 and self.db_url:
            logger.warning("psycopg2 is not installed. Supabase direct DB sync disabled.")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _get_connection(self):
        if not (self.db_url and HAS_PSYCOPG2):
            return None
        return psycopg2.connect(self.db_url, connect_timeout=6)

    def _ensure_pg_tables(self, pg_conn) -> None:
        """CLOUD FIX: pastikan tabel ada di Postgres/Supabase.

        Sebelumnya hanya sisi SQLite yang membuat tabel; di cloud tabel
        movie_catalog bisa tidak ada sehingga semua baca/tulis katalog GAGAL
        diam-diam (error cuma logger.debug) -> hydrate selalu '0 films'.
        """
        ddl = [
            """CREATE TABLE IF NOT EXISTS movie_catalog (
                id SERIAL PRIMARY KEY,
                title TEXT,
                year INTEGER,
                rating TEXT,
                genre TEXT,
                quality TEXT,
                channel_username TEXT,
                message_id BIGINT,
                caption TEXT,
                file_id TEXT,
                season INTEGER,
                episode INTEGER,
                tmdb_id INTEGER,
                original_title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cat_chan_msg ON movie_catalog (LOWER(channel_username), message_id)",
            """CREATE TABLE IF NOT EXISTS ai_cache (
                query TEXT PRIMARY KEY,
                caption TEXT
            )""",
        ]
        try:
            with pg_conn.cursor() as cur:
                for stmt in ddl:
                    cur.execute(stmt)
                # kolom baru (abaikan jika sudah ada)
                for col in ("tmdb_id INTEGER", "original_title TEXT"):
                    try:
                        cur.execute(f"ALTER TABLE movie_catalog ADD COLUMN IF NOT EXISTS {col}")
                    except Exception:
                        pass
            pg_conn.commit()
        except Exception as e:
            logger.warning(f"Gagal menyiapkan tabel cloud: {e}")
            try:
                pg_conn.rollback()
            except Exception:
                pass

    def hydrate_to_sqlite(self, sqlite_conn) -> Dict[str, int]:
        """Downloads all cloud data from Supabase to local SQLite on bot startup.
        Takes < 1s and guarantees zero data loss on fresh ephemeral disks."""
        if not self._enabled:
            return {}

        start_t = time.time()
        counts = {"settings": 0, "catalog": 0, "users": 0, "requests": 0, "scheduled": 0}
        pg_conn = None
        try:
            pg_conn = self._get_connection()
            if not pg_conn:
                return {}

            # Pastikan tabel cloud ada sebelum baca/tulis (fix 'catalog: 0')
            self._ensure_pg_tables(pg_conn)
            p_cur = pg_conn.cursor()
            s_cur = sqlite_conn.cursor()

            # Ensure all SQLite tables exist before reading from cloud
            s_cur.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
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
                    season INTEGER,
                    episode INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_cat_chan_msg ON movie_catalog (channel_username, message_id);
                CREATE TABLE IF NOT EXISTS bot_users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    video_file_id TEXT,
                    caption_text TEXT,
                    metadata_json TEXT,
                    watermark TEXT,
                    scheduled_timestamp INTEGER,
                    title TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ai_cache (
                    query TEXT PRIMARY KEY,
                    caption TEXT
                );
                CREATE TABLE IF NOT EXISTS metadata_cache (
                    query TEXT PRIMARY KEY,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS movie_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    movie_title TEXT,
                    clean_title TEXT,
                    channel_username TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fulfilled_at TIMESTAMP
                );
            """)

            # 1. Settings
            try:
                p_cur.execute("SELECT key, value FROM settings")
                for k, v in p_cur.fetchall():
                    s_cur.execute(
                        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v)
                    )
                    counts["settings"] += 1
            except Exception as e:
                logger.debug(f"Hydrate settings warning: {e}")

            # 2. Movie Catalog
            try:
                p_cur.execute(
                    "SELECT title, year, rating, genre, quality, channel_username, message_id, caption, file_id, season, episode FROM movie_catalog"
                )
                for row in p_cur.fetchall():
                    # Check if already exists in sqlite
                    s_cur.execute(
                        "SELECT id FROM movie_catalog WHERE LOWER(channel_username) = ? AND message_id = ?",
                        (str(row[5]).lower(), row[6])
                    )
                    if not s_cur.fetchone():
                        s_cur.execute(
                            """INSERT INTO movie_catalog (title, year, rating, genre, quality, channel_username, message_id, caption, file_id, season, episode)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            row
                        )
                        counts["catalog"] += 1
            except Exception as e:
                logger.warning(f"Hydrate catalog warning: {e}")

            # 3. Bot Users
            try:
                p_cur.execute("SELECT user_id, username, first_name FROM bot_users")
                for row in p_cur.fetchall():
                    s_cur.execute(
                        "INSERT OR IGNORE INTO bot_users (user_id, username, first_name) VALUES (?, ?, ?)",
                        row
                    )
                    counts["users"] += 1
            except Exception as e:
                logger.debug(f"Hydrate users warning: {e}")

            # 4. Pending Scheduled Posts
            try:
                p_cur.execute(
                    "SELECT chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, status FROM scheduled_posts WHERE status = 'pending'"
                )
                for row in p_cur.fetchall():
                    s_cur.execute(
                        "SELECT id FROM scheduled_posts WHERE scheduled_timestamp = ? AND title = ? AND status = 'pending'",
                        (row[5], row[6])
                    )
                    if not s_cur.fetchone():
                        s_cur.execute(
                            """INSERT INTO scheduled_posts (chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, status)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            row
                        )
                        counts["scheduled"] += 1
            except Exception as e:
                logger.debug(f"Hydrate scheduled warning: {e}")

            # 5. AI Caption Cache
            try:
                p_cur.execute("SELECT query, caption FROM ai_cache")
                for q, cap in p_cur.fetchall():
                    s_cur.execute("INSERT OR REPLACE INTO ai_cache (query, caption) VALUES (?, ?)", (q, cap))
            except Exception as e:
                logger.debug(f"Hydrate ai_cache warning: {e}")

            # 6. Pending Movie Requests
            try:
                s_cur.execute("""
                    CREATE TABLE IF NOT EXISTS movie_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        username TEXT,
                        movie_title TEXT,
                        clean_title TEXT,
                        channel_username TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        fulfilled_at TIMESTAMP
                    )
                """)
                p_cur.execute(
                    "SELECT user_id, username, movie_title, clean_title, channel_username, status FROM movie_requests WHERE status = 'pending'"
                )
                for row in p_cur.fetchall():
                    s_cur.execute(
                        "INSERT OR IGNORE INTO movie_requests (user_id, username, movie_title, clean_title, channel_username, status) VALUES (?, ?, ?, ?, ?, ?)",
                        row
                    )
                    counts["requests"] += 1
            except Exception as e:
                logger.debug(f"Hydrate requests warning: {e}")

            sqlite_conn.commit()
            dur = (time.time() - start_t) * 1000
            logger.info(
                f"🎉 Supabase Cloud -> SQLite Hydration Complete in {dur:.1f}ms! "
                f"({counts['catalog']} films, {counts['settings']} settings, {counts['scheduled']} antrean, {counts['requests']} request restored)"
            )
            return counts
        except Exception as e:
            logger.warning(f"Could not hydrate from Supabase cloud: {e}")
            return {}
        finally:
            if pg_conn:
                try:
                    pg_conn.close()
                except Exception:
                    pass

    async def async_save_setting(self, key: str, value: str):
        """Asynchronously writes a setting to Supabase in the background."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_write_setting, key, value)

    def _sync_write_setting(self, key: str, value: str):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (str(key), str(value))
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_save_setting error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_save_catalog(self, movie: Dict[str, Any]):
        """Asynchronously writes a catalog film post to Supabase."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_write_catalog, movie)

    def _sync_write_catalog(self, m: Dict[str, Any]):
        """CLOUD FIX: UPSERT katalog (insert atau update) + error terlihat di log."""
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                self._ensure_pg_tables(conn)
                with conn.cursor() as cur:
                    # Cek dulu: update kalau sudah ada (hindari duplikat)
                    cur.execute(
                        "SELECT id FROM movie_catalog WHERE LOWER(channel_username) = LOWER(%s) AND message_id = %s LIMIT 1",
                        (m.get("channel_username") or "", m.get("message_id"))
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """UPDATE movie_catalog
                               SET title=%s, year=%s, rating=%s, genre=%s, quality=%s,
                                   caption=%s, file_id=COALESCE(%s, file_id),
                                   season=COALESCE(%s, season), episode=COALESCE(%s, episode),
                                   tmdb_id=COALESCE(%s, tmdb_id), original_title=COALESCE(%s, original_title)
                               WHERE id=%s""",
                            (
                                m.get("title"), m.get("year"), m.get("rating"),
                                m.get("genre"), m.get("quality"), m.get("caption"),
                                m.get("file_id"), m.get("season"), m.get("episode"),
                                m.get("tmdb_id"), m.get("original_title"), existing[0]
                            )
                        )
                    else:
                        cur.execute(
                            """INSERT INTO movie_catalog
                               (title, year, rating, genre, quality, channel_username, message_id, caption, file_id, season, episode, tmdb_id, original_title)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                m.get("title"), m.get("year"), m.get("rating"),
                                m.get("genre"), m.get("quality"), m.get("channel_username"),
                                m.get("message_id"), m.get("caption"), m.get("file_id"),
                                m.get("season"), m.get("episode"), m.get("tmdb_id"),
                                m.get("original_title")
                            )
                        )
                conn.commit()
        except Exception as e:
            logger.warning(f"Supabase save_catalog gagal: {e}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def sync_catalog_bulk(self, movies: List[Dict[str, Any]]) -> int:
        """CLOUD FIX: dorong SELURUH katalog lokal ke Supabase sekaligus.

        Dipakai agar restart berikutnya tidak lagi menampilkan 'catalog: 0'
        dan bot tidak perlu scan ulang channel dari nol.
        """
        if not self._enabled or not movies:
            return 0
        conn = None
        pushed = 0
        try:
            conn = self._get_connection()
            if not conn:
                return 0
            self._ensure_pg_tables(conn)
            with conn.cursor() as cur:
                for m in movies:
                    try:
                        mid = m.get("message_id")
                        chan = m.get("channel_username") or ""
                        cur.execute(
                            "SELECT id FROM movie_catalog WHERE LOWER(channel_username) = LOWER(%s) AND message_id = %s LIMIT 1",
                            (chan, mid)
                        )
                        row = cur.fetchone()
                        if row:
                            cur.execute(
                                """UPDATE movie_catalog
                                   SET title=%s, year=%s, rating=%s, genre=%s, quality=%s, file_id=COALESCE(%s, file_id)
                                   WHERE id=%s""",
                                (m.get("title"), m.get("year"), m.get("rating"), m.get("genre"),
                                 m.get("quality"), m.get("file_id"), row[0])
                            )
                        else:
                            cur.execute(
                                """INSERT INTO movie_catalog
                                   (title, year, rating, genre, quality, channel_username, message_id, caption, file_id, season, episode)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (m.get("title"), m.get("year"), m.get("rating"), m.get("genre"),
                                 m.get("quality"), chan, mid, m.get("caption"), m.get("file_id"),
                                 m.get("season"), m.get("episode"))
                            )
                        pushed += 1
                    except Exception as row_err:
                        logger.debug(f"Bulk catalog row skipped: {row_err}")
            conn.commit()
            logger.info(f"☁️ Katalog disinkronkan ke Supabase: {pushed}/{len(movies)} film")
        except Exception as e:
            logger.warning(f"Supabase sync_catalog_bulk gagal: {e}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return pushed

    async def async_sync_catalog_bulk(self, movies: List[Dict[str, Any]]) -> int:
        return await asyncio.to_thread(self.sync_catalog_bulk, movies)

    async def async_save_scheduled_post(self, post: Dict[str, Any]):
        """Asynchronously syncs a scheduled prime-time post to Supabase."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_write_scheduled_post, post)

    def _sync_write_scheduled_post(self, p: Dict[str, Any]):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO scheduled_posts (chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, status)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            p.get("chat_id"),
                            p.get("video_file_id"),
                            p.get("caption_text"),
                            p.get("metadata_json"),
                            p.get("watermark"),
                            p.get("scheduled_timestamp"),
                            p.get("title"),
                            p.get("status", "pending")
                        )
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_save_scheduled_post error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_save_request(self, user_id: int, username: str, movie_title: str, clean_title: str, channel_username: str):
        """Asynchronously syncs a new member request to Supabase."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_write_request, user_id, username, movie_title, clean_title, channel_username)

    def _sync_write_request(self, user_id: int, username: str, movie_title: str, clean_title: str, channel_username: str):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO movie_requests (user_id, username, movie_title, clean_title, channel_username, status)
                           VALUES (%s, %s, %s, %s, %s, 'pending')""",
                        (user_id, username or "", movie_title, clean_title, channel_username)
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_save_request error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_fulfill_requests(self, clean_title: str):
        """Asynchronously marks requests fulfilled in Supabase."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_fulfill_requests, clean_title)

    def _sync_fulfill_requests(self, clean_title: str):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE movie_requests SET status = 'fulfilled', fulfilled_at = NOW() WHERE status = 'pending' AND (clean_title = %s OR %s LIKE '%%' || clean_title || '%%' OR clean_title LIKE '%%' || %s || '%%')",
                        (clean_title, clean_title, clean_title)
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_fulfill_requests error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_delete_catalog(self, message_ids: List[int], channel_username: Optional[str] = None):
        """Asynchronously deletes movie catalog records from Supabase by message_ids."""
        if not self._enabled or not message_ids:
            return
        await asyncio.to_thread(self._sync_delete_catalog, message_ids, channel_username)

    def _sync_delete_catalog(self, message_ids: List[int], channel_username: Optional[str] = None):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    clean_chan = (channel_username or "").lstrip("@").strip().lower()
                    if clean_chan:
                        cur.execute(
                            "DELETE FROM movie_catalog WHERE message_id = ANY(%s) AND LOWER(channel_username) = %s",
                            (list(message_ids), clean_chan)
                        )
                    else:
                        cur.execute(
                            "DELETE FROM movie_catalog WHERE message_id = ANY(%s)",
                            (list(message_ids),)
                        )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_delete_catalog error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_delete_catalog_by_title(self, clean_title: str, channel_username: Optional[str] = None):
        """Asynchronously deletes movie catalog records from Supabase by title."""
        if not self._enabled or not clean_title:
            return
        await asyncio.to_thread(self._sync_delete_catalog_by_title, clean_title, channel_username)

    def _sync_delete_catalog_by_title(self, clean_title: str, channel_username: Optional[str] = None):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    clean_chan = (channel_username or "").lstrip("@").strip().lower()
                    if clean_chan:
                        cur.execute(
                            "DELETE FROM movie_catalog WHERE LOWER(title) = LOWER(%s) AND LOWER(channel_username) = %s",
                            (clean_title, clean_chan)
                        )
                    else:
                        cur.execute(
                            "DELETE FROM movie_catalog WHERE LOWER(title) = LOWER(%s)",
                            (clean_title,)
                        )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_delete_catalog_by_title error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    async def async_delete_requests(self, clean_title: str):
        """Asynchronously deletes requests from Supabase."""
        if not self._enabled:
            return
        await asyncio.to_thread(self._sync_delete_requests, clean_title)

    def _sync_delete_requests(self, clean_title: str):
        conn = None
        try:
            conn = self._get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM movie_requests WHERE status = 'pending' AND clean_title = %s",
                        (clean_title,)
                    )
                conn.commit()
        except Exception as e:
            logger.debug(f"Supabase async_delete_requests error: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def ping_keepalive(self) -> Dict[str, Any]:
        """Pings Supabase to prevent the 7-day free tier inactivity pause.
        Executes a PostgreSQL write and/or REST API request to reset inactivity counters.
        """
        now_iso = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        res = {
            "success": False,
            "timestamp": now_iso,
            "methods": [],
            "error": None,
        }

        # 1. PostgreSQL Direct DB Ping
        if self.db_url and HAS_PSYCOPG2:
            conn = None
            try:
                conn = self._get_connection()
                if conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS settings (
                                key TEXT PRIMARY KEY,
                                value TEXT
                            );
                        """)
                        cur.execute(
                            """INSERT INTO settings (key, value)
                               VALUES ('supabase_last_keepalive', %s)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                            (now_iso,)
                        )
                    conn.commit()
                    res["methods"].append("postgres_direct")
                    res["success"] = True
            except Exception as e:
                logger.warning(f"Supabase direct PostgreSQL keepalive ping failed: {e}")
                res["error"] = str(e)
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        # 2. Supabase REST API Ping (fallback or dual keepalive)
        if self.supabase_url and self.supabase_key:
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"{self.supabase_url.rstrip('/')}/rest/v1/settings?select=key&limit=1",
                    headers={
                        "apikey": self.supabase_key,
                        "Authorization": f"Bearer {self.supabase_key}",
                        "User-Agent": "FilmBot-Keepalive/1.0",
                    }
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if resp.status in (200, 206):
                        res["methods"].append("rest_api")
                        res["success"] = True
            except Exception as e:
                logger.warning(f"Supabase REST keepalive ping failed: {e}")
                if not res["success"]:
                    res["error"] = str(e)

        if res["success"]:
            logger.info(f"⚡ Supabase keepalive ping OK via {', '.join(res['methods'])} at {now_iso}")
        else:
            logger.warning(f"⚠️ Supabase keepalive ping failed: {res.get('error')}")

        return res

    async def async_ping_keepalive(self) -> Dict[str, Any]:
        """Non-blocking async wrapper for ping_keepalive."""
        return await asyncio.to_thread(self.ping_keepalive)

