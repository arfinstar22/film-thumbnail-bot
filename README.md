# Film AI Bot 🎬🤖

Bot Telegram pintar untuk film panjang:
- 🎬 **Frame Otomatis**: thumbnail bawaan video (instan 1 detik, tanpa download 2GB)
- 🤖 **AI-Powered Caption**: otomatis cari Judul, Tahun, Genre, Rating & Sinopsis Bahasa Indonesia via Groq AI (Llama 3.1)
- 🏷 **Watermark Otomatis**: `@film_indonesia1` di setiap caption

---

## 🛠️ Setup (Lokal PC - Zorin OS / Linux)

### 1. Dapatkan Token & API Key (Semua GRATIS)

1. **Telegram Bot Token**: dari [@BotFather](https://t.me/BotFather)
2. **Telegram API ID & Hash**: dari [my.telegram.org](https://my.telegram.org)
3. **Groq API Key**: dari [console.groq.com/keys](https://console.groq.com/keys) (gratis, model Llama 3.1)

---

### 2. Isi File `.env`

Edit file `.env`:
```bash
nano .env
```

Isi seperti format ini:
```text
BOT_TOKEN=123456:ABC-DEF...
API_ID=12345678
API_HASH=abcdef123456...
GROQ_API_KEY=gsk_... (API Key dari console.groq.com)
```

---

### 3. Jalankan Bot (Lokal)

```bash
./run.sh
```

---

## ☁️ Deploy 24 Jam (Cloud Gratis Tanpa PC Lokal)

Bot ini sudah dilengkapi `Dockerfile` dan health check HTTP (`PORT`) otomatis sehingga dapat langsung dideploy ke platform cloud:

### Opsi 1: Koyeb (Rekomendasi - Gratis 24 Jam Tanpa Sleep)
1. Buka [koyeb.com](https://app.koyeb.com/) dan buat akun.
2. Klik **Create App** > pilih **GitHub**.
3. Pilih repo `film-thumbnail-bot`.
4. Pilih builder **Dockerfile**.
5. Di bagian **Environment Variables**, tambahkan:
   - `BOT_TOKEN`: Token bot Telegram dari @BotFather
   - `API_ID`: ID dari my.telegram.org
   - `API_HASH`: Hash dari my.telegram.org
   - `GROQ_API_KEY`: API Key Groq dari console.groq.com
   - `PORT`: `8000`
6. Klik **Deploy**. Bot akan online 24 jam nonstop!

### Opsi 2: Render (Free Web Service)
1. Buka [render.com](https://dashboard.render.com/) > **New** > **Blueprint** (atau **Web Service**).
2. Hubungkan repo `film-thumbnail-bot`.
3. Masukkan Environment Variables (`BOT_TOKEN`, `API_ID`, `API_HASH`, `GROQ_API_KEY`).
4. Klik **Apply / Deploy**.

### Opsi 3: VPS / Server Pribadi (Docker)
```bash
docker build -t film-bot .
docker run -d --restart always --name film-bot --env-file .env film-bot
```

---

## 🎯 Cara Pakai

1. Forward video/film ke bot di Telegram
2. Bot langsung kirim balik videonya (instan 1 detik) dengan tombol **"🤖 Cari Info Film via AI"**
3. Klik tombolnya → AI menganalisis nama file → mengedit caption video dengan info lengkap & sinopsis Bahasa Indonesia!

