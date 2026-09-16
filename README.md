# Film Thumbnail Bot 🎬

Bot Telegram untuk mengelola thumbnail film panjang (hingga 2GB):
- 🎬 **Ambil Frame Otomatis** (detik tengah film)
- ⏱ **Ambil Frame Manual** (tentukan menit/detik)
- 🖼 **Ganti Thumbnail Pakai Foto Sendiri**
- 🗑 **Hapus Thumbnail**

Menggunakan **FFmpeg copy-codec** (lossless, super cepat, tanpa re-encode video).

---

## 🛠️ Persiapan Awal (Semuanya Gratis)

### 1. Dapatkan Bot Token
1. Buka [@BotFather](https://t.me/BotFather) di Telegram
2. Ketik `/newbot`, beri nama bot
3. Simpan token yang diberikan (contoh: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Dapatkan API ID & API Hash (Wajib untuk Film >50MB)
1. Buka [my.telegram.org](https://my.telegram.org)
2. Login dengan nomor HP Telegram Anda
3. Pilih **API development tools**
4. Isi form singkat (app title & short name bebas)
5. Simpan `api_id` dan `api_hash`

---

## 🚀 Deploy ke Koyeb (Gratis, Persisten)

1. **Push source code ini ke GitHub Anda**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/USERNAME/film-thumbnail-bot.git
   git push -u origin main
   ```

2. **Daftar & Login di [Koyeb](https://app.koyeb.com)** (Free Tier).

3. **Buat App Baru**:
   - Pilih **GitHub** sebagai source
   - Pilih repositori bot Anda
   - Builder: Pilih **Dockerfile**
   - Instance size: **Nano / Micro (Free)**

4. **Isi Environment Variables**:
   - `BOT_TOKEN`: Token dari BotFather
   - `API_ID`: ID dari my.telegram.org
   - `API_HASH`: Hash dari my.telegram.org

5. Klik **Deploy**! Selesai.

---

## 💻 Menjalankan Secara Lokal (Opsional)

Jika ingin tes di komputer sendiri:

1. Copy `.env.example` ke `.env`:
   ```bash
   cp .env.example .env
   ```
2. Isi `BOT_TOKEN`, `API_ID`, dan `API_HASH` di `.env`.
3. Install FFmpeg di PC Anda (pastikan command `ffmpeg` ada di PATH).
4. Jalankan bot:
   ```bash
   pip install -r requirements.txt
   python -m bot.main
   ```

---

## ⚙️ Catatan Penting
- **Kecepatan**: Hanya memodifikasi container metadata, tidak merusak kualitas asli dan selesai dalam hitungan detik.
- **Batas Ukuran**: Maksimal 2GB (limit resmi Telegram Bot API).
- **Watermark**: Ditiadakan demi performa & menjaga kualitas 100% video asli.
