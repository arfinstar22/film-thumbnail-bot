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
3. Simpan token yang diberikan

### 2. Dapatkan API ID & API Hash (Wajib untuk Film >50MB)
1. Buka [my.telegram.org](https://my.telegram.org)
2. Login dengan nomor HP Telegram Anda
3. Pilih **API development tools**
4. Isi form singkat & simpan `api_id` dan `api_hash`

---

## 🚀 Deploy ke Render (Gratis)

1. **Push source code ini ke GitHub Anda**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/USERNAME/film-thumbnail-bot.git
   git push -u origin main
   ```

2. **Daftar & Login di [Render](https://render.com)** (Free Tier).

3. **Deploy via Blueprint**:
   - Di dashboard Render, klik **"New"** → **"Blueprint"**
   - Sambungkan ke repositori GitHub Anda
   - Render akan mendeteksi `render.yaml` secara otomatis
   - Masukkan environment variables:
     - `BOT_TOKEN`
     - `API_ID`
     - `API_HASH`
   - Klik **Apply**! Selesai.

> ⚠️ **Catatan Free Tier**: Instance sleep setelah 15 menit tidak ada trafik. Saat ada user kirim video, butuh ±30 detik cold start.

---

## 💻 Menjalankan Secara Lokal (Opsional)

1. Copy `.env.example` ke `.env`:
   ```bash
   cp .env.example .env
   ```
2. Isi `BOT_TOKEN`, `API_ID`, dan `API_HASH` di `.env`.
3. Jalankan dengan Docker:
   ```bash
   docker build -t thumbbot .
   docker run --env-file .env -p 8081:8081 thumbbot
   ```