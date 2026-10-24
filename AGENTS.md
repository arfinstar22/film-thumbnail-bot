# Project: Film Thumbnail Bot (Telegram)

## CRITICAL: DO NOT MODIFY THESE SECTIONS

### 1. Rich Post / sendRichMessage (`bot/services/metadata/rich_post.py`)
- `build_rich_article_payload()` builds the Telegram Bot API 10.1+ rich article post.
- `async_send_rich_article_post()` sends it via `sendRichMessage`.
- The rich post format is ONE SINGLE CARD with: video player, slideshow, expandable collapsible sections, and inline buttons.
- **JANGAN PISAHKAN** video dari card. Semua dalam satu rich article card.
- **JANGAN UBAH** format tampilan rich post tanpa izin eksplisit dari user.

### 2. Duplikat Auto-Replace (`bot/handlers.py`)
- `handle_post_callback()` (line ~6950): Saat user tekan "Posting ke Channel" dan film duplikat terdeteksi, post lama + stiker pembatas otomatis dihapus dari channel menggunakan `async_delete_channel_post()` (Bot API deleteMessage + Pyrogram fallback), lalu katalog di-update. Film baru menggantikan yang lama.
- Auto-post mode juga melakukan hal yang sama — tidak ada lagi "Auto-Post Ditahan Sementara".
- **Syarat Channel**: Bot wajib diberi hak Admin di channel dengan izin **"Hapus Pesan" (Delete Messages)** agar Telegram mengizinkan penghapusan post lama.
- Cari komentar `DUPLIKAT AUTO-REPLACE` di handlers.py.
- **JANGAN HAPUS** logika ini.

### 3. Franchise / Collection Sync (`sync_collection_sibling_posts`)
- Saat film baru diupload, semua film lain dalam franchise/collection yang sudah ada di channel otomatis di-update.
- Bagian "Urutan Nonton" pada post lama akan di-update: judul film baru yang tadinya teks biasa berubah jadi link biru menuju post baru.
- Video file ID dan banner URL di-cache agar tidak hilang saat edit.
- Cari komentar `FRANCHISE / COLLECTION SYNC` di handlers.py.
- **JANGAN SENTUH** `video_fid_*` dan `banner_fid_*` cache logic.

### 4. Video & Banner File ID Caching
- `video_fid_{title}_{year}` dan `banner_fid_{title}_{year}` disimpan di settings cache.
- Digunakan saat `sync_collection_sibling_posts` untuk memastikan video dan banner tidak hilang saat edit rich post.
- **JANGAN HAPUS** caching ini.

## Architecture Notes
- `bot/handlers.py`: All Telegram message/callback handlers, publishing, and sync logic.
- `bot/services/metadata/rich_post.py`: Rich article post payload builder and sender.
- `bot/services/metadata/cache.py`: SQLite-backed metadata cache (movie catalog, settings, search).
- `bot/services/metadata/caption.py`: Caption text generation.
