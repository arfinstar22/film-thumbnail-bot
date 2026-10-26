import asyncio
import datetime
import difflib
import json
import logging
import os
import re
import sqlite3
import threading
from typing import Dict, Any, Optional, List, Tuple

from .supabase_sync import SupabaseSyncService

logger = logging.getLogger(__name__)

WIB = datetime.timezone(datetime.timedelta(hours=7))


def normalize_movie_title_and_year(title: str, year: Optional[int] = None) -> Tuple[str, Optional[int], str]:
    raw_t = (title or "").strip()
    if not raw_t:
        return "", year, ""

    # Strip channel watermarks like • @channel or @channel
    t = re.sub(r"[•|]\s*@\w+", " ", raw_t)
    t = re.sub(r"@\w+", " ", t)

    # Strip common video file extensions
    t = re.sub(r"\.(mp4|mkv|avi|mov|webm|flv|ts)$", "", t, flags=re.I)

    # Strip common video/audio/release tags
    t = re.sub(r"\b(1080p|720p|480p|2160p|4k|uhd|fhd|hd|web[-_. ]?dl|bluray|bdrip|hdrip|dvdrip|x264|x265|hevc|aac|dts)\b", " ", t, flags=re.I)

    # 1. Check for release year in brackets/parentheses e.g. (2018) or [2019]
    ym_bracket = re.search(r"[\(\[]\s*(19\d\d|20\d\d)\s*[\)\]]", t)
    if ym_bracket:
        bracket_y = int(ym_bracket.group(1))
        if not year:
            year = bracket_y
        t = re.sub(r"[\(\[]\s*(?:19\d\d|20\d\d)\s*[\)\]]", " ", t)

    # 2. Extract 4-digit release year (1900-2099) if still not known
    year_matches = list(re.finditer(r"(?<!\d)(19\d\d|20\d\d)(?!\d)", t))
    if not year and year_matches:
        # In filenames like Dilan.1991.2019.720p, the release year is the LAST 4-digit token
        year = int(year_matches[-1].group(1))

    t_noyear = t
    # 3. Only remove the release year from the title if:
    #    - The specific release year is found
    #    - Removing it does NOT leave the title empty (e.g. movie titled '1917' or '1984')
    #    CRITICAL: Never strip numbers that are part of the title (e.g. '1990' in 'Dilan 1990' when release year is 2018)
    if year:
        cand = re.sub(rf"(?<!\d){year}(?!\d)", " ", t_noyear, count=1)
        if cand.strip():
            t_noyear = cand

    # Convert dot/underscore separators in filenames to spaces
    t_noyear = re.sub(r"[\._]+", " ", t_noyear)

    clean_disp = re.sub(r"\s+", " ", t_noyear).strip()
    # clean_key: alphanumeric lowercase without spaces or punctuation
    clean_key = re.sub(r"[^a-zA-Z0-9]", "", clean_disp).lower()
    return clean_disp, year, clean_key


def extract_movie_sequel_tag(title: str) -> Optional[str]:
    """Extracts sequel/part indicators such as 2, 3, II, III, part 2, chapter 2,
    or 4-digit distinct title numbers (e.g. 1990, 1991, 1983, 1995, 2049)."""
    t = (title or "").lower().strip()
    m = re.search(r"\b(?:part|chapter|vol|volume|season)\s*(\d+|[ivx]+)\b", t, re.I)
    if m:
        return m.group(1).lower()
    m2 = re.search(r"\b(2|3|4|5|6|7|8|9|ii|iii|iv|v|vi|vii|viii)\b", t, re.I)
    if m2:
        return m2.group(1).lower()
    m3 = re.search(r"(?<!\d)(19\d\d|20\d\d)(?!\d)", t)
    if m3:
        return m3.group(1).lower()
    return None


def is_invalid_movie_title(title: str, caption: str = "") -> bool:
    """Strictly checks if a title or caption corresponds to a non-movie post, announcement,
    pinned catalog header, or conversational chat sentence."""
    if not title:
        return True
    t_clean = (title or "").strip()
    t_lower = t_clean.lower()

    # 1. System catalog, pinned messages, announcements
    BAD_PATTERNS = (
        "pusat film indonesia",
        "katalog resmi",
        "katalog koleksi film",
        "katalog & daftar isi",
        "pembaruan tampilan",
        "pengumuman",
        "update tampilan",
        "aturan",
        "rules channel",
        "donasi",
        "buka katalog",
        "request film",
        "join channel",
        "link channel",
        "info resmi",
        "pemberitahuan",
        "informasi penting"
    )
    if any(k in t_lower for k in BAD_PATTERNS):
        return True

    # 2. Conversational sentence markers (must use word boundaries, never substring match)
    has_year = bool(re.search(r"\b(19\d\d|20\d\d)\b", t_clean))
    if not has_year:
        if re.search(r"\b(stay tuned|tunggu update|tunggu update selanjutnya)\b", t_lower):
            return True
        if re.search(r"\b(nih|yuk|dong)\b", t_lower) and re.search(r"\b(guys|kawan|min|admin|halo|tonton|nonton)\b", t_lower):
            return True

    # 3. Very long non-movie paragraphs without a release year
    if len(t_clean) > 85 and not has_year:
        return True

    # 4. Caption contains explicit catalog marker
    cap_lower = (caption or "").lower()
    if any(k in cap_lower for k in ("katalog resmi", "katalog koleksi film", "katalog & daftar isi", "pusat streaming & download")):
        return True

    return False


def calculate_search_relevance(
    query: str,
    title: str,
    year: Optional[int] = None,
    caption: str = "",
    genre: str = "",
    rating: Optional[str] = None
) -> Tuple[float, bool]:
    """Calculates a relevance score (0-100+) and whether the match is a fuzzy typo match."""
    q = (query or "").strip()
    if not q:
        return 0.0, False

    q_clean = re.sub(r"[^\w\s]", " ", q).lower().strip()
    t_clean = re.sub(r"[^\w\s]", " ", title or "").lower().strip()
    if not q_clean or not t_clean:
        return 0.0, False

    # Extract potential year from query (e.g. 'dilan 1990')
    q_year = None
    ym = re.search(r"\b(19\d\d|20\d\d)\b", q_clean)
    if ym:
        q_year = int(ym.group(1))

    t_noyear = re.sub(r"\b(19\d\d|20\d\d)\b", "", t_clean).strip()
    q_noyear = re.sub(r"\b(19\d\d|20\d\d)\b", "", q_clean).strip()

    candidates = []  # List[Tuple[float, bool]] where bool is is_exact

    # 1. Exact title match
    if q_clean == t_clean or (t_noyear and q_clean == t_noyear) or (q_noyear and q_noyear == t_noyear):
        candidates.append((100.0, True))

    # 2. Whole-word substring / containment match (MUST respect word boundaries)
    t_target = t_noyear if t_noyear else t_clean
    q_target = q_noyear if q_noyear else q_clean
    if re.search(r"\b" + re.escape(q_target) + r"\b", t_target):
        cov = len(q_target) / max(len(t_target), len(q_target))
        candidates.append((78.0 + cov * 18.0, True))
    elif re.search(r"\b" + re.escape(t_target) + r"\b", q_target):
        cov = len(t_target) / max(len(t_target), len(q_target))
        candidates.append((60.0 + cov * 15.0, True))

    # 3. Whole words match
    q_words = [w for w in q_clean.split() if len(w) > 1]
    t_words = [w for w in t_clean.split() if len(w) > 1]
    q_words_text = [w for w in q_words if not w.isdigit()]
    t_words_text = [w for w in t_words if not w.isdigit()]
    if q_words and t_words:
        matched = sum(1 for qw in q_words if qw in t_words)
        if matched == len(q_words):
            candidates.append((70.0 + (len(q_words) / len(t_words)) * 15.0, True))

    # 4. Fuzzy SequenceMatcher ratio (typo tolerance)
    ratio_full = difflib.SequenceMatcher(None, q_clean, t_clean).ratio()
    ratio_noyear = difflib.SequenceMatcher(None, q_noyear, t_noyear).ratio() if (q_noyear and t_noyear) else 0.0
    best_ratio = max(ratio_full, ratio_noyear)

    # Word-level fuzzy on text words only (ignore numbers/years)
    if q_words_text and t_words_text:
        if len(q_words_text) == 1:
            best_rw = max((difflib.SequenceMatcher(None, q_words_text[0], tw).ratio() for tw in t_words_text), default=0.0)
            if best_rw > best_ratio:
                best_ratio = max(best_ratio, best_rw * 0.88)
        else:
            word_scores = [
                max((difflib.SequenceMatcher(None, qw, tw).ratio() for tw in t_words_text), default=0.0)
                for qw in q_words_text
            ]
            avg_rw = sum(word_scores) / len(word_scores)
            if avg_rw > best_ratio:
                best_ratio = max(best_ratio, avg_rw * 0.92)

    if best_ratio >= 0.52:
        if q_words_text and t_words_text:
            has_text_sim = any(
                difflib.SequenceMatcher(None, qw, tw).ratio() >= 0.65
                for qw in q_words_text for tw in t_words_text
            )
            if has_text_sim:
                candidates.append((best_ratio * 70.0, False))
        elif not q_words_text and not t_words_text:
            candidates.append((best_ratio * 70.0, False))

    # 5. Caption / Genre / Cast match
    STOP_WORDS = {
        "ada", "ini", "itu", "dan", "di", "ke", "nya", "si", "film", "movie", "sinopsis",
        "nonton", "streaming", "full", "indo", "indonesia", "yang", "dari", "pada", "untuk",
        "dengan", "bisa", "akan", "atau", "oleh", "juga", "sudah", "dalam", "serta", "tidak",
        "sama", "sekali", "tentang", "menceritakan", "adalah", "seorang"
    }
    content_q_words = [w for w in q_words if w not in STOP_WORDS and len(w) > 2]
    cap_clean = (caption or "").lower()
    gen_clean = (genre or "").lower()
    if q_clean and len(q_clean) > 3 and (re.search(r"\b" + re.escape(q_clean) + r"\b", cap_clean) or q_clean in gen_clean):
        candidates.append((55.0, True))
    elif content_q_words:
        matched_content = [qw for qw in content_q_words if re.search(r"\b" + re.escape(qw) + r"\b", cap_clean)]
        if matched_content:
            cov = len(matched_content) / len(content_q_words)
            if cov >= 0.5:
                candidates.append((40.0 + cov * 15.0, False))

    if not candidates:
        return 0.0, False

    candidates.sort(key=lambda x: x[0], reverse=True)
    base_score, is_exact = candidates[0]
    is_fuzzy = not is_exact

    # Year boost / penalty
    if q_year and year:
        if str(q_year) in t_clean:
            pass  # Year is part of the title (e.g. 'Dilan 1990'), do not penalize
        elif q_year == year:
            base_score += 15.0
        elif abs(q_year - year) > 1:
            base_score -= 35.0

    # Rating boost (up to +5.0)
    if rating:
        try:
            rm = re.search(r"(\d+(?:\.\d+)?)", str(rating))
            if rm:
                r_val = float(rm.group(1))
                base_score += (min(r_val, 10.0) / 10.0) * 5.0
        except Exception:
            pass

    return base_score, is_fuzzy


class MetadataCache:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "..", "films.db")
        self._local = threading.local()
        self.cloud = SupabaseSyncService()

    def hydrate_from_cloud(self) -> Dict[str, int]:
        """Pulls persistent data from Supabase Cloud to local SQLite cache on startup."""
        if self.cloud.is_enabled:
            return self.cloud.hydrate_to_sqlite(self._conn())
        return {}

    def ping_supabase_keepalive(self) -> Dict[str, Any]:
        """Triggers keepalive ping to Supabase and updates local cache setting."""
        if not self.cloud.is_enabled:
            return {"success": False, "error": "Supabase sync not enabled (missing DATABASE_URL/SUPABASE_URL)"}
        res = self.cloud.ping_keepalive()
        if res.get("success"):
            self.set_setting("supabase_last_keepalive", res.get("timestamp", ""))
        return res

    async def async_ping_supabase_keepalive(self) -> Dict[str, Any]:
        """Non-blocking async keepalive ping to Supabase."""
        if not self.cloud.is_enabled:
            return {"success": False, "error": "Supabase sync not enabled (missing DATABASE_URL/SUPABASE_URL)"}
        res = await self.cloud.async_ping_keepalive()
        if res.get("success"):
            self.set_setting("supabase_last_keepalive", res.get("timestamp", ""))
        return res

    def get_supabase_last_keepalive(self) -> str:
        """Returns the timestamp of the last successful Supabase keepalive ping."""
        return self.get_setting("supabase_last_keepalive", "Belum pernah")

    def _conn(self):
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            try:
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA busy_timeout=10000")
            except Exception:
                pass
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
        # P0-3 FIX: retry anti "database is locked" (WAL + multi-thread).
        # Tidak mengubah key/value apapun — hanya tahan 3x percobaan.
        # video_fid_*/banner_fid_* logic di bawah TIDAK diubah (area terlarang).
        import time as _t
        last_err = None
        for attempt in range(3):
            try:
                self._conn().execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
                self._conn().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (str(key), str(value)))
                self._conn().commit()
                last_err = None
                break
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    _t.sleep(0.05 * (attempt + 1))
                    continue
                logger.error(f"Set setting error: {e}")
                break
        if last_err is not None:
            logger.error(f"Set setting error after retry: {last_err}")
        else:
            if self.cloud.is_enabled:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.cloud.async_save_setting(key, value))
                except RuntimeError:
                    pass

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
                season INTEGER,
                episode INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN file_id TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN season INTEGER")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN episode INTEGER")
        except Exception:
            pass
        # AKURASI FIX: kunci identitas TMDB agar judul tidak tertukar (Dilan 1990 vs 1991, 1917 vs 2019).
        # Kolom baru, migrasi aman via ALTER TABLE. Tidak ubah logika duplikat/sync yang terlarang.
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN tmdb_id INTEGER")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE movie_catalog ADD COLUMN original_title TEXT")
        except Exception:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_chan_msg ON movie_catalog (channel_username, message_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_series ON movie_catalog (channel_username, title, season, episode)")

    def save_movie_post(
        self,
        title: str,
        year: Optional[int] = None,
        rating: Optional[str] = None,
        genre: Optional[str] = None,
        quality: Optional[str] = None,
        channel_username: str = "film_indonesia1",
        message_id: int = 0,
        caption: str = "",
        file_id: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        original_title: Optional[str] = None
    ):
        clean_channel = (channel_username or "").lstrip("@").strip().lower()
        clean_title, year, _ = normalize_movie_title_and_year(title, year)
        if not clean_title or is_invalid_movie_title(clean_title, caption):
            try:
                conn = self._conn()
                self._ensure_catalog_table(conn)
                conn.execute("DELETE FROM movie_catalog WHERE LOWER(channel_username) = ? AND message_id = ?", (clean_channel, message_id))
                conn.commit()
            except Exception:
                pass
            return
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            cur = conn.execute("SELECT id, file_id, season, episode FROM movie_catalog WHERE LOWER(channel_username) = ? AND message_id = ?", (clean_channel, message_id))
            row = cur.fetchone()
            if row:
                conn.execute("""
                    UPDATE movie_catalog
                    SET title = ?, year = ?, rating = ?, genre = ?, quality = ?, caption = ?,
                        file_id = COALESCE(?, file_id),
                        season = COALESCE(?, season),
                        episode = COALESCE(?, episode),
                        tmdb_id = COALESCE(?, tmdb_id),
                        original_title = COALESCE(?, original_title)
                    WHERE id = ?
                """, (clean_title, year, rating, genre, quality, caption, file_id, season, episode, tmdb_id, original_title, row[0]))
                conn.commit()
            else:
                conn.execute("""
                    INSERT INTO movie_catalog (title, year, rating, genre, quality, channel_username, message_id, caption, file_id, season, episode, tmdb_id, original_title)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (clean_title, year, rating, genre, quality, clean_channel, message_id, caption, file_id, season, episode, tmdb_id, original_title))
                conn.commit()
        except Exception as e:
            logger.error(f"Save movie catalog error: {e}")
        else:
            if self.cloud.is_enabled:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.cloud.async_save_catalog({
                        "title": clean_title, "year": year, "rating": rating,
                        "genre": genre, "quality": quality, "channel_username": clean_channel,
                        "message_id": message_id, "caption": caption, "file_id": file_id,
                        "season": season, "episode": episode,
                        "tmdb_id": tmdb_id, "original_title": original_title
                    }))
                except RuntimeError:
                    pass

    def delete_movie_posts(self, message_ids: List[int], channel_username: Optional[str] = None) -> List[str]:
        """Delete records from movie_catalog by message_ids and return affected channel usernames."""
        if not message_ids:
            return []
        affected_channels = []
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            placeholders = ",".join("?" for _ in message_ids)
            clean_chan = (channel_username or "").lstrip("@").strip().lower()
            if clean_chan:
                cur = conn.execute(
                    f"SELECT DISTINCT channel_username FROM movie_catalog WHERE message_id IN ({placeholders}) AND LOWER(channel_username) = ?",
                    list(message_ids) + [clean_chan]
                )
                affected_channels = [r[0] for r in cur.fetchall() if r[0]]
                if affected_channels:
                    conn.execute(
                        f"DELETE FROM movie_catalog WHERE message_id IN ({placeholders}) AND LOWER(channel_username) = ?",
                        list(message_ids) + [clean_chan]
                    )
                    conn.commit()
            else:
                cur = conn.execute(f"SELECT DISTINCT channel_username FROM movie_catalog WHERE message_id IN ({placeholders})", list(message_ids))
                affected_channels = [r[0] for r in cur.fetchall() if r[0]]
                if affected_channels:
                    conn.execute(f"DELETE FROM movie_catalog WHERE message_id IN ({placeholders})", list(message_ids))
                    conn.commit()
            if affected_channels:
                logger.info(f"Deleted {len(message_ids)} message IDs from catalog, affected channels: {affected_channels}")
                if self.cloud.is_enabled:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.cloud.async_delete_catalog(
                            list(message_ids),
                            clean_chan or (affected_channels[0] if affected_channels else None)
                        ))
                    except RuntimeError:
                        pass
        except Exception as e:
            logger.error(f"Delete movie posts error: {e}")
        return affected_channels

    def delete_movie_by_title(self, title: str, channel_username: Optional[str] = None) -> List[str]:
        """Delete records from movie_catalog by movie title and return affected channel usernames."""
        clean_title = (title or "").strip()
        if not clean_title:
            return []
        affected_channels = []
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            clean_chan = (channel_username or "").lstrip("@").strip().lower()
            if clean_chan:
                cur = conn.execute(
                    "SELECT DISTINCT channel_username FROM movie_catalog WHERE LOWER(title) = LOWER(?) AND LOWER(channel_username) = ?",
                    (clean_title, clean_chan)
                )
                affected_channels = [r[0] for r in cur.fetchall() if r[0]]
                if affected_channels:
                    conn.execute(
                        "DELETE FROM movie_catalog WHERE LOWER(title) = LOWER(?) AND LOWER(channel_username) = ?",
                        (clean_title, clean_chan)
                    )
                    conn.commit()
            else:
                cur = conn.execute("SELECT DISTINCT channel_username FROM movie_catalog WHERE LOWER(title) = LOWER(?)", (clean_title,))
                affected_channels = [r[0] for r in cur.fetchall() if r[0]]
                if affected_channels:
                    conn.execute("DELETE FROM movie_catalog WHERE LOWER(title) = LOWER(?)", (clean_title,))
                    conn.commit()
            if affected_channels:
                logger.info(f"Deleted movie '{clean_title}' from catalog, affected channels: {affected_channels}")
                if self.cloud.is_enabled:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.cloud.async_delete_catalog_by_title(
                            clean_title,
                            clean_chan or (affected_channels[0] if affected_channels else None)
                        ))
                    except RuntimeError:
                        pass
        except Exception as e:
            logger.error(f"Delete movie by title error: {e}")
        return affected_channels

    def purge_invalid_catalog_entries(self, channel_username: Optional[str] = None) -> int:
        """Purges any non-movie entries (announcements, banners, catalog headers) from movie_catalog."""
        deleted_count = 0
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            clean_chan = (channel_username or "").lstrip("@").strip().lower()
            if clean_chan:
                cur = conn.execute("SELECT id, title, caption, message_id FROM movie_catalog WHERE LOWER(channel_username) = ?", (clean_chan,))
            else:
                cur = conn.execute("SELECT id, title, caption, message_id FROM movie_catalog")
            rows = cur.fetchall()
            to_delete_ids = []
            to_delete_msg_ids = []

            for r_id, t, cap, mid in rows:
                if is_invalid_movie_title(t, cap):
                    to_delete_ids.append(r_id)
                    if mid:
                        to_delete_msg_ids.append(mid)

            if to_delete_ids:
                placeholders = ",".join("?" for _ in to_delete_ids)
                conn.execute(f"DELETE FROM movie_catalog WHERE id IN ({placeholders})", to_delete_ids)
                conn.commit()
                deleted_count = len(to_delete_ids)
                logger.info(f"Purged {deleted_count} invalid non-movie entries from movie_catalog.")

                if self.cloud.is_enabled and to_delete_msg_ids:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.cloud.async_delete_catalog(to_delete_msg_ids, clean_chan or None))
                    except RuntimeError:
                        pass
        except Exception as e:
            logger.error(f"Error purging invalid catalog entries: {e}")
        return deleted_count

    def get_deduplicated_catalog(self, channel_username: str) -> List[Dict[str, Any]]:
        """Retrieve unique movies for a channel, automatically keeping only the latest post for duplicates."""
        raw_items = []
        clean_channel = (channel_username or "").lstrip("@").strip().lower()
        try:
            self.purge_invalid_catalog_entries(clean_channel)
            conn = self._conn()
            self._ensure_catalog_table(conn)
            cur = conn.execute("""
                SELECT title, year, rating, genre, quality, channel_username, message_id, caption, file_id, tmdb_id, original_title
                FROM movie_catalog
                WHERE LOWER(channel_username) = ?
                ORDER BY message_id DESC
            """, (clean_channel,))

            for row in cur.fetchall():
                if is_invalid_movie_title(row[0], row[7]):
                    continue
                raw_items.append({
                    "title": row[0],
                    "year": row[1],
                    "rating": row[2],
                    "genre": row[3],
                    "quality": row[4],
                    "channel_username": row[5],
                    "message_id": row[6],
                    "caption": row[7],
                    "file_id": row[8],
                    "tmdb_id": row[9] if len(row) > 9 else None,
                    "original_title": row[10] if len(row) > 10 else None
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

    def get_similar_movies(
        self,
        channel_username: str,
        genre: Optional[str] = None,
        exclude_title: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Find up to `limit` published movies from the same channel sharing similar genres."""
        if not channel_username or not genre:
            return []

        movies = self.get_deduplicated_catalog(channel_username)
        if not movies:
            return []

        genre_tokens = [g.strip().lower() for g in genre.replace("/", ",").split(",") if len(g.strip()) >= 3]
        if not genre_tokens:
            return []

        exclude_clean = (exclude_title or "").strip().lower()

        candidates = []
        for m in movies:
            m_title = (m.get("title") or "").strip()
            if not m_title or not m.get("message_id"):
                continue
            if exclude_clean and m_title.lower() == exclude_clean:
                continue

            m_genre = (m.get("genre") or "").lower()
            score = sum(1 for gt in genre_tokens if gt in m_genre)
            if score > 0:
                candidates.append((score, int(m.get("message_id", 0)), m))

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [c[2] for c in candidates[:limit]]

    def search_catalog(self, query: str = "", limit: int = 8, channel_username: Optional[str] = None) -> List[Dict[str, Any]]:
        raw_items = []
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            q = (query or "").strip()
            clean_chan = (channel_username or "").lstrip("@").strip().lower()

            if clean_chan:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption, file_id
                    FROM movie_catalog
                    WHERE LOWER(channel_username) = ?
                    ORDER BY message_id DESC
                """, (clean_chan,))
            else:
                cur = conn.execute("""
                    SELECT title, year, rating, genre, quality, channel_username, message_id, caption, file_id
                    FROM movie_catalog
                    ORDER BY message_id DESC
                """)

            for row in cur.fetchall():
                if is_invalid_movie_title(row[0], row[7]):
                    continue
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
            logger.error(f"Search catalog error: {e}")
            return []

        seen_keys = {}
        dedup_movies = []
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
                if not target.get("file_id") and item.get("file_id"):
                    target["file_id"] = item.get("file_id")
            else:
                item_copy = dict(item)
                item_copy["title"] = t
                item_copy["year"] = y
                seen_keys[key] = item_copy
                dedup_movies.append(item_copy)

        if not q:
            return dedup_movies[:limit]

        # Calculate relevance score with typo tolerance & ranking
        scored_results = []
        for item in dedup_movies:
            score, is_fuzzy = calculate_search_relevance(
                q,
                item.get("title", ""),
                year=item.get("year"),
                caption=item.get("caption", ""),
                genre=item.get("genre", ""),
                rating=item.get("rating")
            )
            if score >= 35.0:
                item_copy = dict(item)
                item_copy["_score"] = round(score, 2)
                item_copy["_is_fuzzy"] = is_fuzzy
                scored_results.append(item_copy)

        scored_results.sort(
            key=lambda x: (x.get("_score", 0.0), x.get("message_id", 0)),
            reverse=True
        )
        return scored_results[:limit]

    def search_catalog_with_suggestion(
        self,
        query: str = "",
        limit: int = 8,
        channel_username: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Searches the catalog and provides an auto-suggest ('did you mean') title if query had typos."""
        results = self.search_catalog(query, limit=limit, channel_username=channel_username)
        if not results:
            return [], None

        # Check if the top result is a fuzzy match (indicating user had a typo)
        if results[0].get("_is_fuzzy", False):
            best = results[0]
            cand = best.get("title", "")
            if best.get("year"):
                cand += f" ({best['year']})"
            return results, cand

        return results, None

    def get_movies_by_mood(
        self,
        mood: str,
        channel_username: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Filter channel catalog by mood/genre with rating and year ranking."""
        movies = self.get_deduplicated_catalog(channel_username)
        if not movies:
            return []

        mood_lower = (mood or "").lower().strip()
        mood_keywords_map = {
            "horror": ["horror", "horor", "thriller", "misteri", "mystery", "seram"],
            "comedy": ["comedy", "komedi", "lucu", "humor"],
            "action": ["action", "aksi", "petualangan", "adventure", "crime", "laga"],
            "romance": ["romance", "romantis", "drama", "cinta", "melodrama"],
            "family": ["animation", "animasi", "family", "keluarga", "anak"],
        }

        if mood_lower in ("random", "acak", "surprise"):
            import random
            sample_size = min(len(movies), limit)
            return random.sample(movies, sample_size)

        keywords = mood_keywords_map.get(mood_lower, [mood_lower])
        matched = []
        for m in movies:
            genre_str = (m.get("genre") or "").lower()
            caption_str = (m.get("caption") or "").lower()
            if any(k in genre_str or k in caption_str for k in keywords):
                matched.append(m)

        def _score_key(item):
            r_val = 0.0
            r_str = str(item.get("rating") or "")
            rm = re.search(r"(\d+(?:\.\d+)?)", r_str)
            if rm:
                try:
                    r_val = float(rm.group(1))
                except ValueError:
                    pass
            y_val = item.get("year") or 0
            return (r_val, y_val)

        matched.sort(key=_score_key, reverse=True)
        return matched[:limit]

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

    def find_existing_movie(
        self,
        title: str,
        year: Optional[int] = None,
        channel_username: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a movie already exists in the channel catalog.
        Strict duplicate detection rules:
        1. Year matching: If both target and catalog item have years, abs(target_year - item_year) must be <= 1.
           A movie from 2018 is NEVER a duplicate of a movie from 2026.
        2. Sequel/Part check: Titles with distinct sequel numbers (e.g. '2', 'II', 'part 2') are not duplicates.
        3. Exact match: Normalized keys match and years do not conflict.
        4. Typo / High-Fuzzy match:
           - String ratio >= 0.88
           - Word token overlap must not be disjoint, no unshared major words.
           - If both have years, years must be compatible.
        """
        norm_t, norm_y, norm_k = normalize_movie_title_and_year(title, year)
        if not norm_k:
            return None

        movies = self.get_deduplicated_catalog(channel_username)
        if not movies:
            return None

        target_words = set(w for w in norm_t.lower().split() if len(w) > 1)
        target_sequel = extract_movie_sequel_tag(norm_t)

        # Pass 1: Exact Key Match
        for m in movies:
            mt, my, mk = normalize_movie_title_and_year(m.get("title", ""), m.get("year"))
            if not mk:
                continue

            # Year incompatibility check
            if norm_y and my and abs(norm_y - my) > 1:
                continue

            # Sequel mismatch check
            item_sequel = extract_movie_sequel_tag(mt)
            if target_sequel != item_sequel:
                continue

            if mk == norm_k or mt.lower() == norm_t.lower():
                return m

        # Pass 2: High-confidence Typo / Fuzzy Match (Strict)
        best_cand = None
        best_ratio = 0.0

        for m in movies:
            mt, my, mk = normalize_movie_title_and_year(m.get("title", ""), m.get("year"))
            if not mk:
                continue

            # Year incompatibility check
            if norm_y and my and abs(norm_y - my) > 1:
                continue

            # Sequel mismatch check
            item_sequel = extract_movie_sequel_tag(mt)
            if target_sequel != item_sequel:
                continue

            # Word tokens
            cand_words = set(w for w in mt.lower().split() if len(w) > 1)
            if not target_words or not cand_words:
                continue

            # Check word overlap - words must not be completely disjoint
            intersection = target_words & cand_words
            overlap_ratio = len(intersection) / max(len(target_words), len(cand_words))

            # SequenceMatcher ratio between clean strings
            ratio = difflib.SequenceMatcher(None, norm_t.lower(), mt.lower()).ratio()

            is_valid_typo = False
            if ratio >= 0.88:
                if len(target_words) == 1 and len(cand_words) == 1:
                    is_valid_typo = True
                elif overlap_ratio >= 0.50:
                    is_valid_typo = True
                elif len(target_words) == len(cand_words) and ratio >= 0.90:
                    is_valid_typo = True

            if is_valid_typo and ratio > best_ratio:
                if norm_y and my and norm_y != my:
                    continue
                best_ratio = ratio
                best_cand = m

        if best_cand:
            return best_cand

        return None

    def check_duplicate_movie(self, channel_username: str, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Convenience alias for find_existing_movie."""
        return self.find_existing_movie(title=title, year=year, channel_username=channel_username)

    def get_catalog_stats(self, channel_username: str) -> Dict[str, Any]:
        """Compute comprehensive statistics about the channel movie collection."""
        from collections import Counter
        movies = self.get_deduplicated_catalog(channel_username)
        if not movies:
            return {"total": 0}

        total = len(movies)
        with_file_id = sum(1 for m in movies if m.get("file_id"))

        genre_counter = Counter()
        quality_counter = Counter()
        decade_counter = Counter()
        ratings = []

        for m in movies:
            # Genres
            g_str = m.get("genre") or ""
            if g_str:
                for g in re.split(r"[,/•]", g_str):
                    clean_g = g.strip().title()
                    if clean_g and clean_g.lower() not in ["n/a", "none", "-"]:
                        genre_counter[clean_g] += 1

            # Quality
            q_str = (m.get("quality") or "").upper().strip()
            if "1080" in q_str:
                quality_counter["1080p FHD"] += 1
            elif "720" in q_str:
                quality_counter["720p HD"] += 1
            elif "480" in q_str:
                quality_counter["480p SD"] += 1
            elif "4K" in q_str or "2160" in q_str:
                quality_counter["4K UHD"] += 1
            elif q_str:
                quality_counter[q_str] += 1
            else:
                quality_counter["Lainnya / Standar"] += 1

            # Decade
            y = m.get("year")
            if y and isinstance(y, int) and 1900 <= y <= 2035:
                if y >= 2020:
                    decade_counter["2020-an (Terbaru)"] += 1
                elif y >= 2010:
                    decade_counter["2010-an"] += 1
                elif y >= 2000:
                    decade_counter["2000-an"] += 1
                elif y >= 1990:
                    decade_counter["1990-an"] += 1
                else:
                    decade_counter["Klasik (Sebelum 1990)"] += 1
            else:
                decade_counter["Tahun Belum Terdata"] += 1

            # Rating
            r_str = m.get("rating") or ""
            if r_str:
                m_num = re.search(r"([\d\.]+)", str(r_str))
                if m_num:
                    try:
                        val = float(m_num.group(1))
                        if 1.0 <= val <= 10.0:
                            ratings.append((val, m))
                    except ValueError:
                        pass

        avg_rating = sum(r[0] for r in ratings) / len(ratings) if ratings else 0.0
        ratings.sort(key=lambda x: x[0], reverse=True)
        top_rated = [r[1] for r in ratings[:3]]

        return {
            "total": total,
            "with_file_id": with_file_id,
            "backup_ready_pct": int((with_file_id / total) * 100) if total > 0 else 0,
            "top_genres": genre_counter.most_common(5),
            "qualities": quality_counter.most_common(4),
            "decades": decade_counter.most_common(5),
            "avg_rating": round(avg_rating, 1),
            "rated_count": len(ratings),
            "top_rated": top_rated
        }

    # ------------------ MOVIE REQUEST SYSTEM ------------------
    def _ensure_requests_table(self, conn):
        conn.execute("""
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_req_status_title ON movie_requests (status, clean_title)")

    def add_movie_request(self, user_id: int, username: str, movie_title: str, channel_username: str, max_limit: int = 10) -> dict:
        conn = self._conn()
        self._ensure_requests_table(conn)
        clean_t = re.sub(r'[^a-zA-Z0-9]', '', movie_title).lower()
        clean_chan = (channel_username or "").lstrip("@").strip().lower()

        # Check if already requested by same user and still pending
        cur = conn.execute(
            "SELECT id FROM movie_requests WHERE user_id = ? AND clean_title = ? AND status = 'pending'",
            (user_id, clean_t)
        )
        row = cur.fetchone()
        if row:
            return {"success": True, "is_new": False, "title": movie_title, "id": row[0]}

        cur = conn.execute(
            """
            INSERT INTO movie_requests (user_id, username, movie_title, clean_title, channel_username)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username or "", movie_title.strip(), clean_t, clean_chan)
        )
        new_id = cur.lastrowid
        conn.commit()

        if self.cloud.is_enabled:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.cloud.async_save_request(user_id, username or "", movie_title.strip(), clean_t, clean_chan))
            except Exception:
                pass

        count_today = self.get_user_daily_request_count(user_id)
        remaining = max(0, max_limit - count_today)
        return {"success": True, "is_new": True, "title": movie_title, "id": new_id, "count_today": count_today, "remaining": remaining}

    def get_user_daily_request_count(self, user_id: int) -> int:
        """Returns number of movie requests submitted by the user today (WIB timezone, resets at 00:00 WIB)."""
        conn = self._conn()
        self._ensure_requests_table(conn)
        now_wib = datetime.datetime.now(WIB)
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day_wib.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.execute(
            "SELECT COUNT(*) FROM movie_requests WHERE user_id = ? AND created_at >= ?",
            (user_id, start_of_day_utc)
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def check_user_request_quota(self, user_id: int, max_limit: int = 10) -> Tuple[bool, int, int]:
        """Checks if the user has remaining daily movie request quota.
        Returns: (allowed: bool, count_today: int, remaining_quota: int)"""
        count_today = self.get_user_daily_request_count(user_id)
        allowed = count_today < max_limit
        remaining = max(0, max_limit - count_today)
        return allowed, count_today, remaining

    def get_pending_requests(self, channel_username: Optional[str] = None, limit: int = 50) -> List[dict]:
        conn = self._conn()
        self._ensure_requests_table(conn)
        if channel_username:
            clean_chan = channel_username.lstrip("@").strip().lower()
            query = """
                SELECT movie_title, clean_title, COUNT(*) as count, GROUP_CONCAT(username) as requesters, GROUP_CONCAT(user_id) as user_ids, GROUP_CONCAT(id) as req_ids, MIN(created_at) as earliest
                FROM movie_requests
                WHERE status = 'pending' AND (channel_username = ? OR channel_username = '')
                GROUP BY clean_title
                ORDER BY count DESC, earliest ASC
                LIMIT ?
            """
            cur = conn.execute(query, (clean_chan, limit))
        else:
            query = """
                SELECT movie_title, clean_title, COUNT(*) as count, GROUP_CONCAT(username) as requesters, GROUP_CONCAT(user_id) as user_ids, GROUP_CONCAT(id) as req_ids, MIN(created_at) as earliest
                FROM movie_requests
                WHERE status = 'pending'
                GROUP BY clean_title
                ORDER BY count DESC, earliest ASC
                LIMIT ?
            """
            cur = conn.execute(query, (limit,))

        results = []
        for row in cur.fetchall():
            results.append({
                "title": row[0],
                "clean_title": row[1],
                "count": row[2],
                "requesters": [r for r in (row[3] or "").split(",") if r],
                "user_ids": [int(uid) for uid in (row[4] or "").split(",") if uid.strip().lstrip("-").isdigit()],
                "ids": [int(rid) for rid in (row[5] or "").split(",") if rid.strip().isdigit()],
                "created_at": row[6]
            })
        return results

    def get_request_by_id(self, req_id: int) -> Optional[dict]:
        conn = self._conn()
        self._ensure_requests_table(conn)
        cur = conn.execute(
            "SELECT id, user_id, username, movie_title, clean_title, channel_username, status, created_at, fulfilled_at FROM movie_requests WHERE id = ?",
            (req_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "movie_title": row[3],
            "clean_title": row[4],
            "channel_username": row[5],
            "status": row[6],
            "created_at": row[7],
            "fulfilled_at": row[8]
        }

    def delete_request_by_id(self, req_id: int, delete_all_for_title: bool = True) -> int:
        conn = self._conn()
        self._ensure_requests_table(conn)
        req = self.get_request_by_id(req_id)
        if not req:
            return 0
        clean_t = req.get("clean_title")
        if delete_all_for_title and clean_t:
            cur = conn.execute("DELETE FROM movie_requests WHERE clean_title = ?", (clean_t,))
            count = cur.rowcount
        else:
            cur = conn.execute("DELETE FROM movie_requests WHERE id = ?", (req_id,))
            count = cur.rowcount
        conn.commit()

        if self.cloud.is_enabled and clean_t:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.cloud.async_delete_requests(clean_t))
            except Exception:
                pass
        return count

    def delete_requests_by_clean_title(self, clean_title: str) -> int:
        conn = self._conn()
        self._ensure_requests_table(conn)
        cur = conn.execute("DELETE FROM movie_requests WHERE clean_title = ?", (clean_title,))
        count = cur.rowcount
        conn.commit()
        if self.cloud.is_enabled:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.cloud.async_delete_requests(clean_title))
            except Exception:
                pass
        return count

    def clear_all_pending_requests(self, channel_username: Optional[str] = None) -> int:
        conn = self._conn()
        self._ensure_requests_table(conn)
        if channel_username:
            clean_chan = channel_username.lstrip("@").strip().lower()
            cur = conn.execute(
                "DELETE FROM movie_requests WHERE status = 'pending' AND (channel_username = ? OR channel_username = '')",
                (clean_chan,)
            )
        else:
            cur = conn.execute("DELETE FROM movie_requests WHERE status = 'pending'")
        count = cur.rowcount
        conn.commit()
        return count

    def answer_movie_requests(self, req_id: int, answer_note: str = "") -> List[dict]:
        """Marks pending requests for the same movie as answered and returns all affected requester info."""
        conn = self._conn()
        self._ensure_requests_table(conn)
        req = self.get_request_by_id(req_id)
        if not req:
            return []
        clean_t = req.get("clean_title")
        if not clean_t:
            return []

        cur = conn.execute(
            "SELECT id, user_id, username, movie_title, channel_username FROM movie_requests WHERE clean_title = ? AND status = 'pending'",
            (clean_t,)
        )
        matched_ids = []
        requesters = []
        for row in cur.fetchall():
            matched_ids.append(row[0])
            requesters.append({
                "id": row[0],
                "user_id": row[1],
                "username": row[2],
                "movie_title": row[3],
                "channel_username": row[4]
            })

        if matched_ids:
            placeholders = ",".join("?" * len(matched_ids))
            conn.execute(
                f"UPDATE movie_requests SET status = 'answered', fulfilled_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                matched_ids
            )
            conn.commit()

            if self.cloud.is_enabled:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.cloud.async_fulfill_requests(clean_t))
                except Exception:
                    pass

        return requesters

    def _is_matching_request(
        self,
        req_title: str,
        target_title: str,
        target_year: Optional[int] = None
    ) -> bool:
        """Strict matching: Year distance <= 1, sequel check, exact or high-confidence fuzzy."""
        target_t, target_y, target_k = normalize_movie_title_and_year(target_title, target_year)
        req_t, req_y, req_k = normalize_movie_title_and_year(req_title)
        if not target_k or not req_k:
            return False

        # 1. Year check: If both have explicit years, distance must be <= 1
        if target_y and req_y and abs(target_y - req_y) > 1:
            return False

        # 2. Sequel check: distinct sequels do not match
        target_seq = extract_movie_sequel_tag(target_t)
        req_seq = extract_movie_sequel_tag(req_t)
        if target_seq != req_seq:
            return False

        # 3. Exact normalized key match (e.g. rasuk vs rasuk)
        if target_k == req_k or target_t.lower() == req_t.lower():
            return True

        # 4. Fuzzy / word match:
        ratio = difflib.SequenceMatcher(None, target_t.lower(), req_t.lower()).ratio()
        if ratio >= 0.88:
            target_words = set(w for w in target_t.lower().split() if len(w) > 2)
            req_words = set(w for w in req_t.lower().split() if len(w) > 2)
            if target_words and req_words:
                unshared = req_words - target_words
                for uw in unshared:
                    if not any(difflib.SequenceMatcher(None, uw, tw).ratio() >= 0.80 for tw in target_words):
                        return False
            return True

        return False

    def find_matching_requests(self, movie_title: str, year: Optional[int] = None) -> List[dict]:
        """Find pending requests that match the given movie title without altering database status."""
        conn = self._conn()
        self._ensure_requests_table(conn)

        query = "SELECT id, user_id, username, movie_title FROM movie_requests WHERE status = 'pending'"
        cur = conn.execute(query)
        requesters = []

        for row in cur.fetchall():
            r_id, u_id, u_name, req_t = row
            if self._is_matching_request(req_t, movie_title, year):
                requesters.append({
                    "id": r_id,
                    "user_id": u_id,
                    "username": u_name,
                    "requested_title": req_t
                })

        return requesters

    def fulfill_movie_requests(
        self,
        movie_title: str,
        channel_username: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[dict]:
        conn = self._conn()
        self._ensure_requests_table(conn)

        query = "SELECT id, user_id, username, movie_title FROM movie_requests WHERE status = 'pending'"
        cur = conn.execute(query)
        matched_ids = []
        requesters = []

        for row in cur.fetchall():
            r_id, u_id, u_name, req_t = row
            if self._is_matching_request(req_t, movie_title, year):
                matched_ids.append(r_id)
                requesters.append({
                    "id": r_id,
                    "user_id": u_id,
                    "username": u_name,
                    "requested_title": req_t
                })

        if matched_ids:
            placeholders = ",".join("?" * len(matched_ids))
            conn.execute(
                f"UPDATE movie_requests SET status = 'fulfilled', fulfilled_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                matched_ids
            )
            conn.commit()

            clean_t = re.sub(r'[^a-zA-Z0-9]', '', movie_title).lower()
            if self.cloud.is_enabled and clean_t:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.cloud.async_fulfill_requests(clean_t))
                except Exception:
                    pass

        return requesters

    def clear_old_requests(self) -> int:
        conn = self._conn()
        self._ensure_requests_table(conn)
        cur = conn.execute("DELETE FROM movie_requests WHERE status IN ('fulfilled', 'answered', 'rejected')")
        count = cur.rowcount
        conn.commit()
        return count

    # ------------------ IN-PLACE POST UPDATE ------------------
    def find_movie_by_msg_id(self, channel_username: str, message_id: int) -> Optional[dict]:
        conn = self._conn()
        self._ensure_catalog_table(conn)
        clean_chan = channel_username.lstrip("@").strip().lower()
        cur = conn.execute(
            "SELECT id, title, year, rating, genre, quality, caption, file_id FROM movie_catalog WHERE channel_username = ? AND message_id = ?",
            (clean_chan, message_id)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "year": row[2],
            "rating": row[3],
            "genre": row[4],
            "quality": row[5],
            "caption": row[6],
            "file_id": row[7]
        }

    def update_movie_post_metadata(
        self,
        channel_username: str,
        message_id: int,
        title: Optional[str] = None,
        year: Optional[int] = None,
        rating: Optional[str] = None,
        genre: Optional[str] = None,
        quality: Optional[str] = None,
        caption: Optional[str] = None
    ) -> bool:
        conn = self._conn()
        self._ensure_catalog_table(conn)
        clean_chan = channel_username.lstrip("@").strip().lower()

        cur = conn.execute(
            "SELECT id, title, year, rating, genre, quality, caption FROM movie_catalog WHERE channel_username = ? AND message_id = ?",
            (clean_chan, message_id)
        )
        row = cur.fetchone()
        if not row:
            return False

        row_id, ex_title, ex_year, ex_rating, ex_genre, ex_quality, ex_caption = row
        new_title = title if title is not None else ex_title
        new_year = year if year is not None else ex_year
        new_rating = rating if rating is not None else ex_rating
        new_genre = genre if genre is not None else ex_genre
        new_quality = quality if quality is not None else ex_quality
        new_caption = caption if caption is not None else ex_caption

        conn.execute(
            """
            UPDATE movie_catalog
            SET title = ?, year = ?, rating = ?, genre = ?, quality = ?, caption = ?
            WHERE id = ?
            """,
            (new_title, new_year, new_rating, new_genre, new_quality, new_caption, row_id)
        )
        conn.commit()
        return True

    # ------------------ MULTI-CHANNEL SWITCHER ------------------
    def get_user_channels(self, chat_id: int, default_channel: str = "@film_indonesia1") -> List[str]:
        raw = self.get_setting(f"channels_{chat_id}", "")
        if raw:
            try:
                chans = json.loads(raw)
                if isinstance(chans, list) and chans:
                    return chans
            except Exception:
                pass
        curr_wm = self.get_setting(f"watermark_{chat_id}", default_channel)
        return [curr_wm] if curr_wm else [default_channel]

    def add_user_channel(self, chat_id: int, channel: str) -> List[str]:
        clean = ("@" + channel.lstrip("@")).strip().lower()
        chans = self.get_user_channels(chat_id)
        chans_lower = [c.lower() for c in chans]
        if clean not in chans_lower:
            chans.append(clean)
            self.set_setting(f"channels_{chat_id}", json.dumps(chans))
        return chans

    def remove_user_channel(self, chat_id: int, channel: str) -> List[str]:
        clean = ("@" + channel.lstrip("@")).strip().lower()
        chans = self.get_user_channels(chat_id)
        chans = [c for c in chans if c.lower() != clean]
        if not chans:
            chans = ["@film_indonesia1"]
        self.set_setting(f"channels_{chat_id}", json.dumps(chans))
        return chans

    # ------------------ SECRET VAULT ------------------
    def get_vault_channel(self, chat_id: int, default_val: str = "") -> str:
        return self.get_setting(f"vault_channel_{chat_id}", default_val)

    def set_vault_channel(self, chat_id: int, vault_channel: str):
        self.set_setting(f"vault_channel_{chat_id}", vault_channel.strip())

    # ------------------ ADMIN ACCESS CONTROL ------------------
    def get_admin_ids(self) -> List[int]:
        raw = self.get_setting("admin_user_ids", "")
        if raw:
            try:
                ids = json.loads(raw)
                if isinstance(ids, list):
                    return [int(x) for x in ids if str(x).lstrip("-").isdigit()]
            except Exception:
                pass
        return []

    def add_admin_id(self, user_id: int) -> List[int]:
        current = self.get_admin_ids()
        if user_id not in current:
            current.append(user_id)
            self.set_setting("admin_user_ids", json.dumps(current))
        return current

    def remove_admin_id(self, user_id: int) -> List[int]:
        current = self.get_admin_ids()
        current = [u for u in current if u != user_id]
        self.set_setting("admin_user_ids", json.dumps(current))
        return current

    # ------------------ SERIES & EPISODE NAVIGATION ------------------
    def get_series_episodes(
        self,
        channel_username: str,
        title: str,
        season: Optional[int] = None
    ) -> Dict[int, int]:
        """Returns a dict mapping episode_number -> message_id for a series in a channel."""
        clean_chan = (channel_username or "").lstrip("@").strip().lower()
        norm_t, _, norm_k = normalize_movie_title_and_year(title)
        episodes: Dict[int, int] = {}
        try:
            conn = self._conn()
            self._ensure_catalog_table(conn)
            if season is not None:
                cur = conn.execute("""
                    SELECT episode, message_id, title
                    FROM movie_catalog
                    WHERE LOWER(channel_username) = ? AND episode IS NOT NULL AND (season = ? OR season IS NULL)
                    ORDER BY episode ASC
                """, (clean_chan, season))
            else:
                cur = conn.execute("""
                    SELECT episode, message_id, title
                    FROM movie_catalog
                    WHERE LOWER(channel_username) = ? AND episode IS NOT NULL
                    ORDER BY episode ASC
                """, (clean_chan,))
            for ep, msg_id, row_t in cur.fetchall():
                if ep is None:
                    continue
                rt, _, rk = normalize_movie_title_and_year(row_t)
                if rk == norm_k or rt.lower() == norm_t.lower() or (norm_k and norm_k in rk) or (rk and rk in norm_k):
                    episodes[int(ep)] = int(msg_id)
        except Exception as e:
            logger.error(f"Get series episodes error: {e}")
        return episodes

    # ------------------ BOT USERS & BROADCAST ------------------
    def _ensure_users_table(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0,
                banned_until TIMESTAMP,
                ban_reason TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE bot_users ADD COLUMN is_blocked INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE bot_users ADD COLUMN banned_until TIMESTAMP")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE bot_users ADD COLUMN ban_reason TEXT")
        except Exception:
            pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON bot_users (last_active)")

    def register_bot_user(self, user_id: int, username: str = "", first_name: str = ""):
        if not user_id or not isinstance(user_id, int) or user_id <= 0:
            return
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            clean_uname = str(username or "").lstrip("@") if isinstance(username, str) else ""
            clean_fname = str(first_name or "") if isinstance(first_name, str) else ""
            conn.execute("""
                INSERT INTO bot_users (user_id, username, first_name, last_active)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = CASE WHEN excluded.username != '' THEN excluded.username ELSE bot_users.username END,
                    first_name = CASE WHEN excluded.first_name != '' THEN excluded.first_name ELSE bot_users.first_name END,
                    last_active = CURRENT_TIMESTAMP
            """, (user_id, clean_uname, clean_fname))
            conn.commit()
        except Exception as e:
            logger.error(f"Register bot user error: {e}")

    def get_all_bot_user_ids(self) -> List[int]:
        user_ids = set()
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            self._ensure_requests_table(conn)
            cur = conn.execute("SELECT user_id FROM bot_users WHERE user_id > 0")
            for row in cur.fetchall():
                if row[0]:
                    user_ids.add(int(row[0]))
            cur2 = conn.execute("SELECT DISTINCT user_id FROM movie_requests WHERE user_id > 0")
            for row in cur2.fetchall():
                if row[0]:
                    user_ids.add(int(row[0]))
        except Exception as e:
            logger.error(f"Get all bot users error: {e}")
        return sorted(list(user_ids))

    def get_bot_users_count(self) -> int:
        return len(self.get_all_bot_user_ids())

    def get_username_by_user_id(self, user_id: int) -> str:
        if not user_id:
            return ""
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            cur = conn.execute("SELECT username FROM bot_users WHERE user_id = ? LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0]).strip().lstrip("@")
        except Exception as e:
            logger.error(f"Get username error: {e}")
        return ""

    def get_user_id_by_username(self, username: str) -> Optional[int]:
        clean = (username or "").lstrip("@").strip().lower()
        if not clean:
            return None
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            cur = conn.execute("SELECT user_id FROM bot_users WHERE LOWER(username) = ? LIMIT 1", (clean,))
            row = cur.fetchone()
            if row and row[0]:
                return int(row[0])
        except Exception as e:
            logger.error(f"Get user_id error: {e}")
        return None

    def block_user(self, user_id: int, reason: str = "") -> bool:
        if not user_id or not isinstance(user_id, int) or user_id <= 0:
            return False
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            clean_reason = (reason or "").strip()
            conn.execute("""
                UPDATE bot_users
                SET is_blocked = 1, ban_reason = ?, banned_until = NULL
                WHERE user_id = ?
            """, (clean_reason, user_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Block user error: {e}")
            return False

    def unblock_user(self, user_id: int) -> bool:
        if not user_id or not isinstance(user_id, int) or user_id <= 0:
            return False
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            conn.execute("""
                UPDATE bot_users
                SET is_blocked = 0, banned_until = NULL, ban_reason = NULL
                WHERE user_id = ?
            """, (user_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Unblock user error: {e}")
            return False

    def ban_user(self, user_id: int, duration_seconds: int = 86400, reason: str = "Spam chat terus-menerus") -> bool:
        if not user_id or not isinstance(user_id, int) or user_id <= 0:
            return False
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            expiry_dt = now_utc + datetime.timedelta(seconds=duration_seconds)
            expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")
            clean_reason = (reason or "").strip()

            conn.execute("""
                UPDATE bot_users
                SET banned_until = ?, ban_reason = ?
                WHERE user_id = ?
            """, (expiry_str, clean_reason, user_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ban user error: {e}")
            return False

    def is_user_banned(self, user_id: int) -> Tuple[bool, str, Optional[str]]:
        """Checks if a user is currently blocked or banned.
        Returns: (is_banned: bool, reason: str, banned_until: Optional[str])
        """
        if not user_id or not isinstance(user_id, int) or user_id <= 0:
            return False, "", None
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            cur = conn.execute("""
                SELECT is_blocked, banned_until, ban_reason
                FROM bot_users
                WHERE user_id = ?
                LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return False, "", None

            is_blocked, banned_until, ban_reason = row[0], row[1], row[2]
            if is_blocked:
                return True, ban_reason or "Diblokir oleh Admin", None

            if banned_until:
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                try:
                    exp_dt = datetime.datetime.strptime(str(banned_until).strip(), "%Y-%m-%d %H:%M:%S")
                    exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
                except Exception:
                    try:
                        exp_dt = datetime.datetime.fromisoformat(str(banned_until).strip())
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
                    except Exception:
                        exp_dt = now_utc

                if now_utc < exp_dt:
                    return True, ban_reason or "Spam chat terus-menerus", str(banned_until)
                else:
                    conn.execute("""
                        UPDATE bot_users
                        SET banned_until = NULL, ban_reason = NULL
                        WHERE user_id = ?
                    """, (user_id,))
                    conn.commit()
                    return False, "", None

            return False, "", None
        except Exception as e:
            logger.error(f"Check is_user_banned error: {e}")
            return False, "", None

    def get_bot_users(self, page: int = 1, page_size: int = 10) -> Tuple[List[Dict[str, Any]], int]:
        """Returns paginated list of bot users with ban status."""
        users = []
        total_pages = 1
        try:
            conn = self._conn()
            self._ensure_users_table(conn)
            cur = conn.execute("SELECT COUNT(*) FROM bot_users WHERE user_id > 0")
            total_count = cur.fetchone()[0] or 0
            if total_count > 0:
                total_pages = max(1, (total_count + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            offset = (page - 1) * page_size

            cur = conn.execute("""
                SELECT user_id, username, first_name, created_at, last_active, is_blocked, banned_until, ban_reason
                FROM bot_users
                WHERE user_id > 0
                ORDER BY last_active DESC
                LIMIT ? OFFSET ?
            """, (page_size, offset))
            for row in cur.fetchall():
                users.append({
                    "user_id": int(row[0]),
                    "username": row[1] or "",
                    "first_name": row[2] or "",
                    "created_at": str(row[3] or ""),
                    "last_active": str(row[4] or ""),
                    "is_blocked": int(row[5] or 0),
                    "banned_until": str(row[6]) if row[6] else None,
                    "ban_reason": row[7] or ""
                })
        except Exception as e:
            logger.error(f"Get bot users error: {e}")
        return users, total_pages

    # ------------------ CONTENT PROTECTION ------------------
    def get_protect_content(self, chat_id: int) -> bool:
        val = self.get_setting(f"protect_{chat_id}", self.get_setting("protect_content", "off"))
        return val.strip().lower() == "on"

    def set_protect_content(self, chat_id: int, enabled: bool):
        val = "on" if enabled else "off"
        self.set_setting(f"protect_{chat_id}", val)
        self.set_setting("protect_content", val)

    # ------------------ FORCE-SUBSCRIBE (FSUB) ------------------
    def get_fsub_status(self) -> bool:
        val = self.get_setting("fsub_status", "on")
        return val.strip().lower() == "on"

    def set_fsub_status(self, enabled: bool):
        self.set_setting("fsub_status", "on" if enabled else "off")

    # ------------------ SCHEDULED POSTS (PRIME TIME) ------------------
    def _ensure_scheduled_table(self, conn):
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sched_status_time ON scheduled_posts (status, scheduled_timestamp)")

    def add_scheduled_post(
        self,
        chat_id: int,
        video_file_id: str,
        caption_text: str,
        metadata: dict,
        watermark: str,
        title: str,
        scheduled_timestamp: Optional[int] = None
    ) -> int:
        conn = self._conn()
        self._ensure_scheduled_table(conn)
        meta = metadata or {}
        clean_title = title or meta.get("title") or "Film"

        if not scheduled_timestamp:
            pending = self.get_pending_scheduled_posts()
            slots = get_next_prime_time_slots(len(pending) + 1)
            scheduled_timestamp = int(slots[-1].timestamp())

        cur = conn.execute("""
            INSERT INTO scheduled_posts (chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (chat_id, video_file_id, caption_text, json.dumps(meta), watermark, int(scheduled_timestamp), clean_title))
        conn.commit()
        row_id = cur.lastrowid
        self.reschedule_pending_posts()
        if self.cloud.is_enabled:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.cloud.async_save_scheduled_post({
                    "chat_id": chat_id, "video_file_id": video_file_id,
                    "caption_text": caption_text, "metadata_json": json.dumps(meta),
                    "watermark": watermark, "scheduled_timestamp": int(scheduled_timestamp),
                    "title": clean_title, "status": "pending"
                }))
            except RuntimeError:
                pass
        return row_id

    def get_pending_scheduled_posts(self) -> List[Dict[str, Any]]:
        conn = self._conn()
        self._ensure_scheduled_table(conn)
        cur = conn.execute("""
            SELECT id, chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, created_at
            FROM scheduled_posts
            WHERE status = 'pending'
            ORDER BY scheduled_timestamp ASC
        """)
        items = []
        for row in cur.fetchall():
            items.append({
                "id": row[0],
                "chat_id": row[1],
                "video_file_id": row[2],
                "caption_text": row[3],
                "metadata": json.loads(row[4]) if row[4] else {},
                "watermark": row[5],
                "scheduled_timestamp": row[6],
                "title": row[7],
                "created_at": row[8]
            })
        return items

    def get_due_scheduled_posts(self, current_timestamp: int) -> List[Dict[str, Any]]:
        conn = self._conn()
        self._ensure_scheduled_table(conn)
        cur = conn.execute("""
            SELECT id, chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title
            FROM scheduled_posts
            WHERE status = 'pending' AND scheduled_timestamp <= ?
            ORDER BY scheduled_timestamp ASC
        """, (current_timestamp,))
        items = []
        for row in cur.fetchall():
            items.append({
                "id": row[0],
                "chat_id": row[1],
                "video_file_id": row[2],
                "caption_text": row[3],
                "metadata": json.loads(row[4]) if row[4] else {},
                "watermark": row[5],
                "scheduled_timestamp": row[6],
                "title": row[7]
            })
        return items

    def mark_scheduled_post_done(self, post_id: int):
        conn = self._conn()
        self._ensure_scheduled_table(conn)
        conn.execute("UPDATE scheduled_posts SET status = 'completed' WHERE id = ?", (post_id,))
        conn.commit()

    def clear_all_scheduled_posts(self) -> int:
        conn = self._conn()
        self._ensure_scheduled_table(conn)
        cur = conn.execute("DELETE FROM scheduled_posts WHERE status = 'pending'")
        count = cur.rowcount
        conn.commit()
        return count

    def reschedule_pending_posts(self):
        pending = self.get_pending_scheduled_posts()
        if not pending:
            return
        slots = get_next_prime_time_slots(len(pending))
        conn = self._conn()
        for item, slot in zip(pending, slots):
            conn.execute("UPDATE scheduled_posts SET scheduled_timestamp = ? WHERE id = ?", (int(slot.timestamp()), item["id"]))
        conn.commit()

    def export_scheduled_posts_json(self) -> str:
        pending = self.get_pending_scheduled_posts()
        return json.dumps(pending, ensure_ascii=False, indent=2)

    def import_scheduled_posts_json(self, json_str: str) -> int:
        if not json_str or not json_str.strip():
            return 0
        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                return 0
        except Exception:
            return 0

        conn = self._conn()
        self._ensure_scheduled_table(conn)
        imported = 0
        for item in data:
            vfid = item.get("video_file_id") or item.get("file_id")
            if not vfid:
                continue
            cur = conn.execute("SELECT id FROM scheduled_posts WHERE video_file_id = ? AND status = 'pending'", (vfid,))
            if cur.fetchone():
                continue

            chat_id = item.get("chat_id", 0)
            caption = item.get("caption_text") or item.get("caption") or ""
            meta = item.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            wm = item.get("watermark") or item.get("channel_username") or ""
            ts = item.get("scheduled_timestamp")
            title = item.get("title") or (meta.get("title") if isinstance(meta, dict) else None) or "Film"

            conn.execute("""
                INSERT INTO scheduled_posts (chat_id, video_file_id, caption_text, metadata_json, watermark, scheduled_timestamp, title, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (chat_id, vfid, caption, json.dumps(meta), wm, int(ts) if ts else 0, title))
            imported += 1

        conn.commit()
        if imported > 0:
            self.reschedule_pending_posts()
        return imported


WIB = datetime.timezone(datetime.timedelta(hours=7))


def get_next_prime_time_slots(count: int, start_from: Optional[datetime.datetime] = None) -> List[datetime.datetime]:
    now = start_from or datetime.datetime.now(WIB)
    current_day = now.date()
    step_minutes = 30 if count > 6 else 60

    candidate_times = []
    for day_offset in range(14):
        target_date = current_day + datetime.timedelta(days=day_offset)
        # Sore: 16:00 to 18:59
        cur_t = datetime.datetime(target_date.year, target_date.month, target_date.day, 16, 0, tzinfo=WIB)
        end_afternoon = datetime.datetime(target_date.year, target_date.month, target_date.day, 18, 59, tzinfo=WIB)
        while cur_t <= end_afternoon:
            candidate_times.append(cur_t)
            cur_t += datetime.timedelta(minutes=step_minutes)

        # Malam: 20:00 to 22:59
        cur_t = datetime.datetime(target_date.year, target_date.month, target_date.day, 20, 0, tzinfo=WIB)
        end_night = datetime.datetime(target_date.year, target_date.month, target_date.day, 22, 59, tzinfo=WIB)
        while cur_t <= end_night:
            candidate_times.append(cur_t)
            cur_t += datetime.timedelta(minutes=step_minutes)

    valid_slots = [t for t in candidate_times if t > (now + datetime.timedelta(minutes=1))]
    return valid_slots[:count]