# Rencana Implementasi: Tombol Clear-Cache, Reaksi Channel Otomatis, Manajemen Pengguna & Anti-Spam

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan tombol ke-5 "Bersihkan Memory Setelah Nonton" (tg://settings/data/storage/clear-cache) berwarna biru (primary) pada post channel, memberikan reaksi acak otomatis pada setiap post channel, serta menambahkan manajemen pengguna, blokir manual, dan auto anti-spam (banned 1 hari) dengan kekebalan mutlak bagi Admin Absolut.

**Architecture:** 
1. Tombol ke-5 ditambahkan pada `build_channel_post_keyboard` di baris ketiga dengan style `primary` (Bot API 8.0+ native Telegram blue) dan URL deep-link Telegram.
2. Helper reaksi `_send_random_channel_reaction` disematkan langsung di dalam `publish_video_to_channel` sehingga otomatis aktif untuk semua metode penerbitan channel (manual, auto-post, batch, penggantian duplikat) dengan fallback bertingkat (Bot API `setMessageReaction` -> Pyrogram).
3. Tabel `bot_users` diperluas dengan kolom status blokir dan ban temporer. Middleware Pyrogram `group=-1` mengamankan bot dari spamming (banned 24 jam) dan memblokir akses pengguna terlarang, dengan pengecualian mutlak untuk Admin Absolut (`is_owner`). Fitur admin `/users`, `/block`, `/unblock` menyediakan kontrol penuh.

**Tech Stack:** Python 3.12, Pyrogram, Telegram Bot API (sendRichMessage, setMessageReaction), SQLite3 (`bot/services/metadata/cache.py`), Pytest.

**Spec:** Permintaan pengguna (User Request):
1. Tombol ke-5 "Bersihkan Memory Setelah Nonton" link `tg://settings/data/storage/clear-cache` style primary (biru Telegram).
2. Bot memberikan reaksi acak otomatis setiap kali posting ke channel.
3. Admin dapat melihat daftar pengguna yang pernah berinteraksi/start, memblokir pengguna, dan anti-spam chat bertubi-tubi dengan banned 1 hari (tidak berlaku untuk Admin Absolut).

## Global Constraints
- Jangan mengubah format rich post card (harus tetap 1 single card terpadu).
- Jangan merusak atau mengubah logika Duplikat Auto-Replace (`handle_post_callback`).
- Jangan menyentuh logika Franchise / Collection Sync (`sync_collection_sibling_posts`) dan caching `video_fid_*` / `banner_fid_*`.
- Admin Absolut (`is_owner`: ID `1166479771`, username `@dxstar22`, `ABSOLUTE_ADMIN_USER_IDS`, `ABSOLUTE_ADMIN_USERNAMES`) memiliki kekebalan mutlak: tidak pernah terkena anti-spam dan tidak bisa diblokir.

## Review Focus
- Validasi URL tombol ke-5: `tg://settings/data/storage/clear-cache` harus tetap utuh dan style `primary` diterapkan.
- Penanganan kegagalan reaksi: kegagalan reaksi (misal channel mematikan reaksi) tidak boleh membatalkan atau merusak postingan video channel.
- Anti-spam false positive: threshold anti-spam harus pas (misal > 5 pesan dalam 3 detik) agar tidak memblokir user normal yang mengetik biasa.
- Auto-unban setelah 1 hari: expired ban harus otomatis terangkat setelah 24 jam tanpa perlu intervensi manual.
- Kekebalan Admin Absolut: Admin Absolut tetap bebas mengetik cepat dan tidak terpengaruh anti-spam/blokir.

---

### Task 1: Tombol ke-5 "Bersihkan Memory Setelah Nonton" (Primary Blue) pada Channel Keyboard

**Files:**
- Modify: `bot/handlers.py:825-873` (`build_channel_post_keyboard` & `_build_bot_api_reply_markup`)
- Modify: `tests/test_aesthetic_features.py:115-145`

**Interfaces:**
- Consumes: `InlineKeyboardButton`, `InlineKeyboardMarkup`, `_build_bot_api_reply_markup`
- Produces: `build_channel_post_keyboard` menghasilkan keyboard 3 baris (Baris 1: Gabung + Trailer, Baris 2: Request + Bagikan, Baris 3: Bersihkan Memory)

- [ ] **Step 1: Tulis test yang memvalidasi baris ke-3 tombol bersihkan memory**

```python
# tests/test_aesthetic_features.py
def test_channel_post_colorful_buttons(self):
    from bot.handlers import build_channel_post_keyboard, _build_bot_api_reply_markup

    kb = build_channel_post_keyboard(
        watermark="@film_indonesia1",
        title="Agak Laen",
        year=2024,
        trailer_url="https://youtube.com/watch?v=123",
        instant_view_url="https://telegra.ph/Agak-Laen-2024",
        request_link="https://t.me/filmin_bot?start=req"
    )
    texts = [[b.text for b in row] for row in kb.inline_keyboard]

    self.assertEqual(texts[0], ["📢 Gabung @film_indonesia1", "🎬 Tonton Trailer"])
    self.assertEqual(texts[1], ["💬 Request Film", "🔄 Bagikan Film"])
    self.assertEqual(texts[2], ["🧹 Bersihkan Memory Setelah Nonton"])

    bot_api_kb = _build_bot_api_reply_markup(kb)["inline_keyboard"]
    self.assertEqual(bot_api_kb[0][0]["style"], "success")   # Gabung: Green
    self.assertEqual(bot_api_kb[0][1]["style"], "danger")    # Trailer: Red
    self.assertEqual(bot_api_kb[1][0]["style"], "danger")    # Request: Red
    self.assertEqual(bot_api_kb[1][1]["style"], "success")   # Bagikan: Green
    self.assertEqual(bot_api_kb[2][0]["style"], "primary")   # Bersihkan: Blue
    self.assertEqual(bot_api_kb[2][0]["url"], "tg://settings/data/storage/clear-cache")
```

- [ ] **Step 2: Jalankan test dan pastikan gagal (merah)**

Run: `PYTHONPATH=. pytest tests/test_aesthetic_features.py -k test_channel_post_colorful_buttons`
Expected: FAIL (IndexError atau AssertionError karena baris ke-3 belum ada)

- [ ] **Step 3: Tambahkan tombol ke-5 di `bot/handlers.py`**

Modifikasi `build_channel_post_keyboard`:
```python
    btn_clear_cache = InlineKeyboardButton("🧹 Bersihkan Memory Setelah Nonton", url="tg://settings/data/storage/clear-cache")
    btn_clear_cache.style = "primary"

    rows = []
    if series_nav_row:
        rows.append(series_nav_row)
    rows.append([btn_join, btn_trailer])
    rows.append([btn_req, btn_share])
    rows.append([btn_clear_cache])
    return InlineKeyboardMarkup(rows)
```
Di `_build_bot_api_reply_markup`:
Tambahkan kata kunci `"memory"` dan `"cache"` pada auto-detect style primary sebagai fallback.

- [ ] **Step 4: Jalankan test dan pastikan lulus (hijau)**

Run: `PYTHONPATH=. pytest tests/test_aesthetic_features.py`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit perubahan Task 1**

```bash
git add bot/handlers.py tests/test_aesthetic_features.py
git commit -m "feat: add 5th button 'Bersihkan Memory Setelah Nonton' with primary blue style"
```

---

### Task 2: Reaksi Acak Otomatis (Random Reactions) Setiap Kali Bot Posting ke Channel

**Files:**
- Create: `tests/test_channel_reaction.py`
- Modify: `bot/handlers.py` (tambahkan fungsi `_send_random_channel_reaction` dan panggil di `publish_video_to_channel`)

**Interfaces:**
- Consumes: `BOT_TOKEN`, `watermark`, `sent_channel.id`, Telegram Bot API `setMessageReaction`
- Produces: `async_send_channel_reaction(bot_token: str, chat_id: Union[int, str], message_id: int, emoji: Optional[str] = None) -> bool`

- [ ] **Step 1: Tulis unit test untuk `async_send_channel_reaction`**

Buat `tests/test_channel_reaction.py`:
```python
import unittest
from unittest.mock import patch, MagicMock
from bot.handlers import _send_random_channel_reaction, CHANNEL_REACTION_EMOJIS

class TestChannelReaction(unittest.IsolatedAsyncioTestCase):
    async def test_send_random_channel_reaction_success(self):
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"ok": true, "result": true}'
            mock_url.return_value.__enter__.return_value = mock_resp
            
            res = await _send_random_channel_reaction(None, "@test_channel", 123)
            self.assertTrue(res)

    async def test_send_random_channel_reaction_safe_on_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("API Error")):
            res = await _send_random_channel_reaction(None, "@test_channel", 123)
            self.assertFalse(res)
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `PYTHONPATH=. pytest tests/test_channel_reaction.py`
Expected: FAIL (ImportError `_send_random_channel_reaction` belum ada)

- [ ] **Step 3: Implementasikan `_send_random_channel_reaction` di `bot/handlers.py`**

1. Definisikan daftar emoji:
   `CHANNEL_REACTION_EMOJIS = ["🔥", "🍿", "👍", "❤️", "🎉", "👏", "⚡", "😍", "🤩", "💯", "🎬", "✨"]`
2. Buat fungsi async `_send_random_channel_reaction(client, chat_id, message_id)`:
   - Pilih emoji acak dengan `random.choice(CHANNEL_REACTION_EMOJIS)`.
   - Lakukan HTTP POST ke `https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction`.
   - Jika gagal, fallback ke `client.send_reaction(chat_id, message_id, emoji)`.
   - Tangkap exception dengan aman (log warning, return False) agar tidak memengaruhi proses publish.
3. Panggil `await _send_random_channel_reaction(client, watermark, sent_channel.id)` di dalam `publish_video_to_channel` tepat setelah `sent_channel` berhasil diterbitkan.

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `PYTHONPATH=. pytest tests/test_channel_reaction.py`
Expected: PASS

- [ ] **Step 5: Commit perubahan Task 2**

```bash
git add bot/handlers.py tests/test_channel_reaction.py
git commit -m "feat: add automatic random reactions for newly published channel posts"
```

---

### Task 3: Skema Database & Model Cache untuk Manajemen Pengguna, Blokir, dan Ban Anti-Spam

**Files:**
- Modify: `bot/services/metadata/cache.py` (`_ensure_users_table`, `block_user`, `unblock_user`, `ban_user`, `is_user_banned`, `get_bot_users`)
- Create: `tests/test_user_management_and_antispam.py`

**Interfaces:**
- Consumes: SQLite `bot_users` table
- Produces:
  - `block_user(user_id: int, reason: str = "") -> bool`
  - `unblock_user(user_id: int) -> bool`
  - `ban_user(user_id: int, duration_seconds: int = 86400, reason: str = "") -> bool`
  - `is_user_banned(user_id: int) -> Tuple[bool, str, Optional[str]]`
  - `get_bot_users(page: int = 1, page_size: int = 10) -> Tuple[List[Dict[str, Any]], int]`

- [ ] **Step 1: Tulis test untuk database methods**

```python
# tests/test_user_management_and_antispam.py
import unittest
import tempfile
import os
from bot.services.metadata.cache import MetadataCache

class TestUserManagementCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.cache = MetadataCache(db_path=self.tmp.name)

    def tearDown(self):
        try:
            os.remove(self.tmp.name)
        except Exception:
            pass

    def test_block_and_unblock_user(self):
        self.cache.register_bot_user(12345, "testuser", "Test")
        self.assertFalse(self.cache.is_user_banned(12345)[0])

        self.cache.block_user(12345, reason="Banned by admin")
        is_banned, reason, _ = self.cache.is_user_banned(12345)
        self.assertTrue(is_banned)
        self.assertEqual(reason, "Banned by admin")

        self.cache.unblock_user(12345)
        self.assertFalse(self.cache.is_user_banned(12345)[0])

    def test_temporary_ban_and_auto_expiry(self):
        self.cache.register_bot_user(67890, "spammer", "Spam")
        # Ban for 1 second
        self.cache.ban_user(67890, duration_seconds=1, reason="Spam")
        is_banned, _, _ = self.cache.is_user_banned(67890)
        self.assertTrue(is_banned)

        # After sleep or manual expired check
        import time
        time.sleep(1.2)
        is_banned, _, _ = self.cache.is_user_banned(67890)
        self.assertFalse(is_banned)
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py -k "test_block_and_unblock_user or test_temporary_ban_and_auto_expiry"`
Expected: FAIL (AttributeError `block_user` not found)

- [ ] **Step 3: Implementasikan di `bot/services/metadata/cache.py`**

1. Perbarui `_ensure_users_table(conn)` untuk menambahkan kolom bila belum ada:
   - `is_blocked INTEGER DEFAULT 0`
   - `banned_until TIMESTAMP`
   - `ban_reason TEXT`
2. Implementasikan:
   - `block_user(user_id, reason)`
   - `unblock_user(user_id)`
   - `ban_user(user_id, duration_seconds=86400, reason="Spam chat terus-menerus")`
   - `is_user_banned(user_id)`: periksa apakah `is_blocked == 1` atau `banned_until > CURRENT_TIMESTAMP`. Jika `banned_until` sudah lewat, otomatis reset `banned_until = NULL`.
   - `get_bot_users(page=1, page_size=10)`: query daftar pengguna diurutkan berdasarkan `last_active DESC`, mengembalikan list dict dan total halaman.

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py`
Expected: PASS

- [ ] **Step 5: Commit perubahan Task 3**

```bash
git add bot/services/metadata/cache.py tests/test_user_management_and_antispam.py
git commit -m "feat: add user blocking, temporary ban, and pagination support in cache"
```

---

### Task 4: Middleware Anti-Spam (1 Hari Banned) & Interseptor Pesan / Callback

**Files:**
- Modify: `bot/handlers.py`
- Modify: `tests/test_user_management_and_antispam.py`

**Interfaces:**
- Consumes: `is_owner(user_id, username)`, `is_user_banned(user_id)`, `ban_user(user_id, 86400)`
- Produces:
  - `@app.on_message(group=-1)`: global activity recorder, antispam detector, ban checker
  - `@app.on_callback_query(group=-1)`: global callback ban checker

- [ ] **Step 1: Tulis unit test untuk Anti-Spam & Kekebalan Admin Absolut**

Tambahkan ke `tests/test_user_management_and_antispam.py`:
```python
    def test_absolute_admin_immunity(self):
        from bot.handlers import is_owner, _check_antispam_and_banned
        from bot.config import ABSOLUTE_ADMIN_USER_IDS
        admin_id = list(ABSOLUTE_ADMIN_USER_IDS)[0]
        
        # Absolute admin must always return True for is_owner
        self.assertTrue(is_owner(admin_id))
        
        # Spamming 10 times in a row should NEVER ban absolute admin
        for _ in range(10):
            blocked, msg = _check_antispam_and_banned(admin_id, "dxstar22", "Darfin")
            self.assertFalse(blocked)

    def test_regular_user_spam_triggers_ban(self):
        from bot.handlers import _check_antispam_and_banned, _user_message_timestamps
        user_id = 999999
        _user_message_timestamps.pop(user_id, None)
        
        # Normal messages
        blocked, _ = _check_antispam_and_banned(user_id, "normal", "User")
        self.assertFalse(blocked)

        # Trigger spam (more than 5 messages within 3 seconds)
        for _ in range(6):
            blocked, alert = _check_antispam_and_banned(user_id, "normal", "User")
            if blocked:
                break
        self.assertTrue(blocked)
        self.assertIn("1 hari", alert.lower())
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py -k "test_absolute_admin_immunity or test_regular_user_spam_triggers_ban"`
Expected: FAIL (ImportError `_check_antispam_and_banned` belum ada)

- [ ] **Step 3: Implementasikan fungsi proteksi spam dan handler group=-1**

Di `bot/handlers.py`:
1. Buat struktur data in-memory:
   `_user_message_timestamps: Dict[int, List[float]] = {}`
2. Buat fungsi helper teruji `_check_antispam_and_banned(user_id, username, first_name) -> Tuple[bool, str]`:
   - Registrasi pengguna: `_engine.cache.register_bot_user(user_id, username, first_name)`
   - Cek kekebalan: Jika `is_owner(user_id, username)`: return `(False, "")`.
   - Cek ban saat ini: `is_banned, reason, expires = _engine.cache.is_user_banned(user_id)`. Jika ya, return `(True, notice)`.
   - Cek frekuensi pesan (sliding window): jika > 5 pesan dalam 3 detik:
     - `_engine.cache.ban_user(user_id, duration_seconds=86400, reason="Spam chat terus-menerus")`
     - Return `(True, alert_spam_1_hari)`
   - Return `(False, "")`
3. Tambahkan `@app.on_message(group=-1)`:
   - Panggil `_check_antispam_and_banned`
   - Jika `blocked`: kirim balasan peringatan sekali lalu `message.stop_propagation()`.
4. Tambahkan `@app.on_callback_query(group=-1)`:
   - Cek jika user terblokir (dan bukan admin absolut): `query.answer("⛔ Akses Anda diblokir.", show_alert=True)` lalu `query.stop_propagation()`.

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py`
Expected: PASS

- [ ] **Step 5: Commit perubahan Task 4**

```bash
git add bot/handlers.py tests/test_user_management_and_antispam.py
git commit -m "feat: implement anti-spam 24h auto-ban and absolute admin immunity"
```

---

### Task 5: Dashboard Admin & Perintah Manajemen Pengguna (/users, /block, /unblock)

**Files:**
- Modify: `bot/handlers.py`
- Modify: `tests/test_user_management_and_antispam.py`

**Interfaces:**
- Consumes: `_engine.cache.get_bot_users`, `_engine.cache.block_user`, `_engine.cache.unblock_user`, `is_admin`, `is_owner`
- Produces:
  - Command `/users` / `/pengguna`: paginated interactive user list
  - Command `/block <user_id> [alasan]`
  - Command `/unblock <user_id>`
  - Callback queries: `adm_users:(\d+)`, `user_block:(\d+):(\d+)`, `user_unblock:(\d+):(\d+)`
  - Tombol `👥 Kelola Pengguna` di Admin Dashboard

- [ ] **Step 1: Tulis test untuk `/block`, `/unblock`, dan larangan memblokir Admin Absolut**

```python
# tests/test_user_management_and_antispam.py
    def test_cannot_block_absolute_admin(self):
        from bot.handlers import execute_admin_block_user
        from bot.config import ABSOLUTE_ADMIN_USER_IDS
        admin_id = list(ABSOLUTE_ADMIN_USER_IDS)[0]
        
        ok, msg = execute_admin_block_user(admin_id)
        self.assertFalse(ok)
        self.assertIn("Admin Absolut", msg)

    def test_can_block_and_unblock_regular_user(self):
        from bot.handlers import execute_admin_block_user, execute_admin_unblock_user
        user_id = 888111
        
        ok, msg = execute_admin_block_user(user_id, "Pelanggaran aturan")
        self.assertTrue(ok)
        
        ok, msg = execute_admin_unblock_user(user_id)
        self.assertTrue(ok)
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py -k "test_cannot_block_absolute_admin"`
Expected: FAIL (ImportError `execute_admin_block_user`)

- [ ] **Step 3: Implementasikan command dan callbacks di `bot/handlers.py`**

1. Buat helper `execute_admin_block_user(target_id, reason)` & `execute_admin_unblock_user(target_id)`:
   - Validasi: jika `is_owner(target_id)` -> Tolak dengan pesan "❌ Admin Absolut / Pemilik Bot tidak dapat diblokir!".
   - Jalankan `_engine.cache.block_user` / `unblock_user`.
2. Buat fungsi `build_users_page(page=1) -> Tuple[str, InlineKeyboardMarkup]`:
   - Ambil data pengguna dari `_engine.cache.get_bot_users(page, page_size=8)`.
   - Format teks: Nama, Username, ID, status (🟢 Aktif / 🔴 Diblokir Admin / ⏳ Banned Anti-Spam), waktu interaksi terakhir.
   - Buat tombol navigasi: `[◀️ Prev] [Hal X/Y] [Next ▶️]` serta tombol cepat `[🚫 Blokir/Buka]`.
3. Daftarkan `@app.on_message(filters.command(["users", "pengguna", "members"]))`:
   - Cek `is_admin(user_id, username)`.
   - Kirim `build_users_page(1)`.
4. Daftarkan `@app.on_message(filters.command(["block", "blokir", "ban"]))`:
   - Format: `/block <user_id> [alasan]`.
   - Jalankan `execute_admin_block_user` dan berikan konfirmasi.
5. Daftarkan `@app.on_message(filters.command(["unblock", "bukablokir", "unban"]))`:
   - Format: `/unblock <user_id>`.
   - Jalankan `execute_admin_unblock_user` dan berikan konfirmasi.
6. Daftarkan callback handler untuk `adm_users:(\d+)`, `user_block:(\d+):(\d+)`, `user_unblock:(\d+):(\d+)`.
7. Tambahkan tombol `👥 Kelola Pengguna` di keyboard dashboard admin (`send_admin_dashboard`).

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `PYTHONPATH=. pytest tests/test_user_management_and_antispam.py`
Expected: PASS

- [ ] **Step 5: Commit perubahan Task 5**

```bash
git add bot/handlers.py tests/test_user_management_and_antispam.py
git commit -m "feat: add /users list, /block, /unblock commands and dashboard integration"
```

---

### Task 6: Verifikasi End-to-End & Regresi Menyeluruh

**Files:**
- Run test suite: `tests/`

- [ ] **Step 1: Jalankan seluruh test suite project**

Run: `PYTHONPATH=. pytest`
Expected: Seluruh test (test_aesthetic_features, test_channel_reaction, test_user_management_and_antispam, test_rich_post, test_audit_verification, test_smart_request_and_quota, dll.) lulus 100% tanpa error.

- [ ] **Step 2: Verifikasi fitur kritis tidak terganggu**
- Verifikasi rich post format tetap single card (`test_rich_post.py`).
- Verifikasi duplikat auto-replace tidak berubah (`tests/test_audit_verification.py`).
- Verifikasi caching video file ID dan banner file ID tetap aman.

- [ ] **Step 3: Selesaikan dan dokumentasikan**
