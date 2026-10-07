import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Union, Optional, Dict, Any

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChatJoinRequest
)
from pyrogram.enums import ParseMode

from .config import BOT_TOKEN, API_ID, API_HASH, SESSION_STRING, CHANNEL_WATERMARK, DEFAULT_REQUEST_LINK
from .services.video import photo_thumbnail
from .services.metadata.engine import MetadataEngine
from .services.metadata.catalog import format_pinned_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if SESSION_STRING:
    app = Client("thumb_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
else:
    app = Client("thumb_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

_jobs = {}
_engine = MetadataEngine()


async def _apply_expandable_caption(chat_id: Union[int, str], message_id: int, caption: str, reply_markup=None):
    """Enforce native Telegram expandable blockquote via Bot API HTTP endpoint."""
    if not caption or "<blockquote expandable>" not in caption:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageCaption"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "caption": caption,
        "parse_mode": "HTML"
    }

    if reply_markup and hasattr(reply_markup, "inline_keyboard"):
        kb = []
        for row in reply_markup.inline_keyboard:
            r = []
            for btn in row:
                b = {"text": btn.text}
                if getattr(btn, "url", None):
                    b["url"] = btn.url
                elif getattr(btn, "callback_data", None):
                    b["callback_data"] = btn.callback_data
                r.append(b)
            kb.append(r)
        payload["reply_markup"] = {"inline_keyboard": kb}

    def _sync_call():
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        await asyncio.to_thread(_sync_call)
    except Exception as e:
        logger.debug(f"Bot API expandable caption sync error: {e}")


def _get_user_watermark(chat_id: int) -> str:
    return _engine.cache.get_setting(f"watermark_{chat_id}", CHANNEL_WATERMARK)


def _get_user_divider(chat_id: int) -> str:
    return _engine.cache.get_setting(f"divider_{chat_id}", "default")


def normalize_telegram_link(val: str) -> str:
    val = val.strip()
    if val.lower() == "off":
        return "off"
    if val.lower() == "default":
        return DEFAULT_REQUEST_LINK

    m = re.match(r"^(?:https?://)?([a-zA-Z0-9_]+)\.t\.me(?:\?(.*))?$", val, re.I)
    if m:
        bot_name = m.group(1)
        query = f"?{m.group(2)}" if m.group(2) else ""
        return f"https://t.me/{bot_name}{query}"

    m2 = re.match(r"^(?:https?://)?t\.me/(.+)$", val, re.I)
    if m2:
        return f"https://t.me/{m2.group(1)}"

    if val.startswith("@"):
        return f"https://t.me/{val.lstrip('@')}"

    if not (val.startswith("http://") or val.startswith("https://")):
        return f"https://{val}"

    return val


def _get_user_request_link(chat_id: int) -> str:
    link = _engine.cache.get_setting(f"request_link_{chat_id}", "")
    if link:
        return link
    link = _engine.cache.get_setting("global_request_link", "")
    if link:
        return link
    return DEFAULT_REQUEST_LINK


async def _send_channel_divider(client: Client, chat_id: int, channel_id: str):
    divider = _get_user_divider(chat_id)
    if not divider or divider.lower() == "off":
        return

    try:
        sticker_target = divider
        if divider == "default":
            cached_fid = _engine.cache.get_setting("custom_divider_fid", "")
            if cached_fid:
                sticker_target = cached_fid
            else:
                asset_path = os.path.join(os.path.dirname(__file__), "assets", "divider_sticker.webp")
                if os.path.exists(asset_path):
                    sticker_target = asset_path
                else:
                    sticker_target = "CAACAgQAAxUAAWrFHuZw3PQKz0c--t8Vyxk1eNziAAKeOAACMY1GAAE6x0wralVnuR4E"

        sent_stk = await client.send_sticker(chat_id=channel_id, sticker=sticker_target)
        if divider == "default" and getattr(sent_stk, "sticker", None):
            _engine.cache.set_setting("custom_divider_fid", sent_stk.sticker.file_id)
    except Exception as e:
        logger.warning(f"Gagal mengirim stiker pemisah: {e}")


def format_size(bytes_val: int) -> str:
    if not bytes_val or bytes_val <= 0:
        return ""
    if bytes_val >= 1024**3:
        return f"{bytes_val / (1024**3):.2f} GB"
    return f"{bytes_val / (1024**2):.1f} MB"


def format_duration(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}j {m}m" if m > 0 else f"{h}j"
    return f"{m}m"


def extract_filename(media, msg: Message) -> str:
    name = getattr(media, "file_name", "") or ""
    if not name or name == "film.mp4":
        if msg.caption:
            lines = [l.strip() for l in msg.caption.split("\n") if l.strip()]
            for line in lines:
                if re.search(r"\.(mp4|mkv|avi|webm)\b", line, re.I) or re.search(r"\b(19\d\d|20\d\d)\b", line):
                    name = line
                    break
            if not name and lines:
                name = lines[0]
    return name or "Film"


def get_caption_kb(message_id: int, watermark: str):
    clean_wm = watermark.lstrip("@").strip()
    channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Posting ke Channel", callback_data=f"post:{message_id}"),
            InlineKeyboardButton("📢 Buka Channel", url=channel_url)
        ],
        [
            InlineKeyboardButton("✏️ Edit Caption", callback_data=f"edit:{message_id}"),
            InlineKeyboardButton("📋 Salin Teks", callback_data=f"copy:{message_id}")
        ],
        [
            InlineKeyboardButton("🔄 Format Ulang", callback_data=f"info:{message_id}")
        ]
    ])



@app.on_message(filters.command("start"))
async def start_cmd(client: Client, msg: Message):
    try:
        await client.set_bot_commands([
            BotCommand("start", "Panduan & info bot"),
            BotCommand("cari", "Cari film di database channel"),
            BotCommand("synckatalog", "Scan channel & update Pinned Catalog A-Z"),
            BotCommand("setwatermark", "Atur channel tujuan (@namachannel)"),
            BotCommand("setrequest", "Atur link tombol Request Film"),
            BotCommand("setdivider", "Atur stiker pemisah film di channel"),
            BotCommand("setsynopsis", "Aktif/matikan sinopsis film otomatis"),
            BotCommand("autojoin", "Aktif/matikan persetujuan join request otomatis")
        ])
    except Exception:
        pass

    wm = _get_user_watermark(msg.chat.id)
    divider = _get_user_divider(msg.chat.id)
    req_link = _get_user_request_link(msg.chat.id)
    syn_val = _engine.cache.get_setting(f"synopsis_{msg.chat.id}", "on")
    autojoin_val = _engine.cache.get_setting("global_autojoin", "on")
    div_status = "Logo Custom Film Indonesia" if divider == "default" else ("Mati (Off)" if divider == "off" else "Stiker Pilihan Anda")
    req_status = f"<code>{req_link}</code>" if req_link and req_link != "off" else ("Mati (Off)" if req_link == "off" else "<i>Belum diatur</i>")
    syn_status = "Aktif (On)" if syn_val != "off" else "Mati (Off)"
    autojoin_status = "Aktif (On)" if autojoin_val != "off" else "Mati (Off)"

    text = (
        "🎬 <b>FILM CLEANER & PUBLISHER BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang! Bot ini otomatis membersihkan watermark lama, mengekstrak rating & genre resmi, merapikan sinopsis lipat, dan menerbitkan langsung ke channel Telegram Anda.\n\n"
        "📌 <b>DAFTAR PERINTAH (COMMANDS):</b>\n\n"
        "• <code>/start</code>\n"
        "  Menampilkan menu bantuan dan daftar fitur ini.\n\n"
        "• <code>/cari &lt;judul film&gt;</code>\n"
        "  Mencari film di katalog channel dengan link tonton langsung.\n"
        "  ▫️ <i>Mode Inline:</i> Ketik <code>@bot &lt;judul&gt;</code> di chat mana pun!\n\n"
        "• <code>/synckatalog</code>\n"
        "  Scan riwayat channel, bersihkan film duplikat (hanya ambil post terbaru), dan perbarui Pinned Catalog A-Z di channel.\n\n"
        f"• <code>/setwatermark @namachannel</code>\n"
        f"  Mengatur channel tujuan dan link promosi watermark.\n"
        f"  <i>Channel aktif saat ini:</i> <b>{wm}</b>\n\n"
        "• <code>/setrequest https://t.me/linkanda</code>\n"
        "  Mengatur link tujuan tombol <b>[ 💬 Request Film ]</b> di channel.\n"
        "  ▫️ Ketik <code>/setrequest off</code> untuk menyembunyikan tombol request.\n"
        f"  <i>Link request saat ini:</i> {req_status}\n\n"
        "• <code>/setdivider</code>\n"
        "  Mengatur stiker pemisah antar film di channel:\n"
        "  ▫️ <b>Reply stiker apa saja</b> dengan <code>/setdivider</code> untuk pasang stiker itu.\n"
        "  ▫️ <code>/setdivider default</code> untuk kembali ke logo custom Film Indonesia.\n"
        "  ▫️ <code>/setdivider off</code> untuk mematikan stiker pemisah.\n"
        f"  <i>Stiker aktif saat ini:</i> <b>{div_status}</b>\n\n"
        "• <code>/setsynopsis on / off</code>\n"
        "  Mengatur sinopsis lipat otomatis dari ensiklopedia Wikipedia Indonesia.\n"
        f"  <i>Sinopsis saat ini:</i> <b>{syn_status}</b>\n\n"
        "• <code>/autojoin on / off</code>\n"
        "  Otomatis setujui member yang minta join ke channel private.\n"
        f"  <i>Auto-join saat ini:</i> <b>{autojoin_status}</b>\n\n"
        "⚡ <b>FITUR UTAMA:</b>\n"
        "• 🧹 <b>Pembersih Cerdas</b>: Menghapus teks uploader lama & noise secara otomatis.\n"
        "• ⭐ <b>Rating & Genre IMDb</b>: Deteksi otomatis rating dan genre film tanpa API key.\n"
        "• 🔍 <b>Pencarian Cepat & Inline</b>: Cari film lewat <code>/cari</code> atau ketik <code>@bot judul</code> di chat grup/PM.\n"
        "• 👥 <b>Auto-Approve Join Request</b>: Setujui member channel private otomatis & sambut dengan pesan ramah.\n"
        "• 📖 <b>Sinopsis Lipat Otomatis</b>: Ringkasan alur cerita akurat via kutipan lipat Telegram.\n"
        "• 🚀 <b>1-Klik Posting Channel</b>: Terbit ke channel dengan tombol 2x2 simetris (Gabung, Trailer, Request, Share).\n"
        "• 🎞️ <b>Stiker Pembatas</b>: Otomatis kirim stiker pemisah visual setelah setiap film di channel.\n"
        "• 📋 <b>Salin & Edit Teks</b>: Tombol cepat untuk copy caption atau edit teks manual.\n\n"
        "💡 <b>CARA PENGGUNAAN:</b>\n"
        "1. Kirim atau forward file video film ke bot ini.\n"
        "2. Tunggu 1 detik hingga bot merapikan caption dan metadata.\n"
        "3. Tekan tombol <b>🚀 Posting ke Channel</b> untuk menerbitkannya ke channel Anda!"
    )

    await msg.reply_text(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.command("setwatermark"))
async def set_watermark_cmd(client: Client, msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        curr = _get_user_watermark(msg.chat.id)
        await msg.reply_text(
            f"📌 <b>Watermark Channel Anda:</b> <code>{curr}</code>\n\n"
            "Untuk mengganti ke channel lain, kirim perintah:\n"
            "<code>/setwatermark @namachannelanda</code>",
            parse_mode=ParseMode.HTML
        )
        return

    new_wm = args[1].strip()
    if not new_wm.startswith("@"):
        new_wm = f"@{new_wm}"

    _engine.cache.set_setting(f"watermark_{msg.chat.id}", new_wm)
    await msg.reply_text(
        f"✅ <b>Watermark Channel Diperbarui!</b>\n\n"
        f"• Watermark baru: <b>{new_wm}</b>\n"
        f"• Tombol promosi otomatis: <b>https://t.me/{new_wm.lstrip('@')}</b>\n\n"
        f"Semua film berikutnya akan otomatis memakai watermark ini!",
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.command("setdivider"))
async def set_divider_cmd(client: Client, msg: Message):
    reply = msg.reply_to_message
    if reply and reply.sticker:
        new_fid = reply.sticker.file_id
        _engine.cache.set_setting(f"divider_{msg.chat.id}", new_fid)
        await msg.reply_text(
            "✅ <b>Stiker Pemisah Berhasil Diubah!</b>\n\n"
            "Stiker yang Anda reply sekarang akan otomatis dikirim sebagai pembatas setiap kali posting ke channel.",
            parse_mode=ParseMode.HTML
        )
        return

    args = msg.text.split(maxsplit=1)
    subcmd = args[1].strip().lower() if len(args) > 1 else ""

    if subcmd == "off":
        _engine.cache.set_setting(f"divider_{msg.chat.id}", "off")
        await msg.reply_text(
            "⏹️ <b>Stiker Pemisah Dimatikan!</b>\n\n"
            "Bot tidak akan mengirim stiker setelah film. Untuk mengaktifkan kembali, ketik <code>/setdivider default</code>.",
            parse_mode=ParseMode.HTML
        )
    elif subcmd == "default":
        _engine.cache.set_setting(f"divider_{msg.chat.id}", "default")
        await msg.reply_text(
            "✅ <b>Stiker Pemisah Di-reset ke Bawaan!</b>\n\n"
            "Menggunakan stiker logo sinema custom Film Indonesia.",
            parse_mode=ParseMode.HTML
        )
    else:
        curr = _get_user_divider(msg.chat.id)
        status_text = "Logo Custom Film Indonesia (Default)" if curr == "default" else ("Mati (Off)" if curr == "off" else "Stiker Kustom Pilihan Anda")
        await msg.reply_text(
            f"🎞️ <b>Pengaturan Stiker Pemisah Channel:</b>\n"
            f"• Status saat ini: <b>{status_text}</b>\n\n"
            f"<b>Cara Ganti Stiker:</b>\n"
            f"1. Kirim stiker apa saja ke chat ini.\n"
            f"2. <b>Reply (balas)</b> stiker tersebut dengan perintah <code>/setdivider</code>.\n\n"
            f"<b>Pilihan Lain:</b>\n"
            f"• <code>/setdivider default</code> (Kembalikan ke logo custom Film Indonesia)\n"
            f"• <code>/setdivider off</code> (Matikan stiker pemisah)",
            parse_mode=ParseMode.HTML
        )


@app.on_message(filters.command("setrequest"))
async def set_request_cmd(client: Client, msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        curr = _get_user_request_link(msg.chat.id)
        status_text = f"<code>{curr}</code>" if curr and curr != "off" else ("<i>Mati (Off)</i>" if curr == "off" else "<i>Belum diatur</i>")
        await msg.reply_text(
            f"💬 <b>Pengaturan Link Tombol Request Film:</b>\n"
            f"• Link saat ini: {status_text}\n\n"
            f"<b>Cara Mengatur Link:</b>\n"
            f"Ketik perintah beserta link tujuan:\n"
            f"<code>/setrequest https://t.me/film_indonesia1/123</code>\n"
            f"<i>(Bisa link postingan tersemat, grup obrolan, bot request, atau akun admin)</i>\n\n"
            f"<b>Pilihan Lain:</b>\n"
            f"• <code>/setrequest off</code> (Sembunyikan tombol request)",
            parse_mode=ParseMode.HTML
        )
        return

    raw_val = args[1].strip()
    val = normalize_telegram_link(raw_val)

    if val == "off":
        _engine.cache.set_setting(f"request_link_{msg.chat.id}", "off")
        _engine.cache.set_setting("global_request_link", "off")
        await msg.reply_text("⏹️ <b>Tombol Request Film dinonaktifkan dari channel.</b>", parse_mode=ParseMode.HTML)
        return

    _engine.cache.set_setting(f"request_link_{msg.chat.id}", val)
    _engine.cache.set_setting("global_request_link", val)
    await msg.reply_text(
        f"✅ <b>Link Request Film Berhasil Disimpan!</b>\n\n"
        f"• Link tujuan: <b>{val}</b>\n\n"
        f"Setiap kali Anda menekan <b>🚀 Posting ke Channel</b>, tombol <b>[ 💬 Request Film ]</b> akan otomatis tampil di baris ke-2 dan mengarah ke link ini!",
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.command("setsynopsis"))
async def set_synopsis_cmd(client: Client, msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        curr = _engine.cache.get_setting(f"synopsis_{msg.chat.id}", "on")
        status_text = "Aktif (On)" if curr != "off" else "Mati (Off)"
        await msg.reply_text(
            f"📖 <b>Pengaturan Sinopsis Otomatis:</b>\n"
            f"• Status saat ini: <b>{status_text}</b>\n\n"
            f"<b>Perintah:</b>\n"
            f"• <code>/setsynopsis on</code> (Aktifkan sinopsis lipat Wikipedia Indonesia)\n"
            f"• <code>/setsynopsis off</code> (Matikan fitur sinopsis)",
            parse_mode=ParseMode.HTML
        )
        return

    subcmd = args[1].strip().lower()
    if subcmd == "off":
        _engine.cache.set_setting(f"synopsis_{msg.chat.id}", "off")
        await msg.reply_text("⏹️ <b>Sinopsis lipat otomatis dinonaktifkan.</b>", parse_mode=ParseMode.HTML)
    else:
        _engine.cache.set_setting(f"synopsis_{msg.chat.id}", "on")
        await msg.reply_text("✅ <b>Sinopsis lipat otomatis diaktifkan!</b>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command(["cari", "search"]))
async def search_movie_cmd(client: Client, msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        bot_info = await client.get_me()
        bot_user = bot_info.username or "bot"
        await msg.reply_text(
            "🔍 <b>Pencarian Film</b>\n\n"
            "Ketik judul film yang ingin Anda cari:\n"
            "<code>/cari &lt;judul film&gt;</code>\n\n"
            "<i>Contoh:</i>\n"
            "• <code>/cari Dilan</code>\n"
            "• <code>/cari Gundala</code>\n\n"
            f"💡 <i>Tips: Anda juga bisa ketik langsung di chat grup/PM manapun:</i>\n"
            f"<code>@{bot_user} judul film</code>",
            parse_mode=ParseMode.HTML
        )
        return

    query = args[1].strip()
    results = _engine.cache.search_catalog(query, limit=8)

    if not results:
        await msg.reply_text(
            f"🔍 Tidak ditemukan film dengan kata kunci '<b>{query}</b>' di katalog channel.\n\n"
            "💡 Film akan otomatis tercatat di katalog saat Anda mempostingnya ke channel.",
            parse_mode=ParseMode.HTML
        )
        return

    text = f"🍿 <b>Hasil Pencarian untuk '<code>{query}</code>':</b>\n\n"
    buttons = []
    for idx, item in enumerate(results, 1):
        title = item["title"]
        year = f" ({item['year']})" if item.get("year") else ""
        rating = f"⭐ {item['rating']} | " if item.get("rating") else ""
        genre = f"🎭 {item['genre']}" if item.get("genre") else ""
        info_line = f"{rating}{genre}".strip(" | ")
        channel = item["channel_username"].lstrip("@")
        msg_id = item["message_id"]
        post_url = f"https://t.me/{channel}/{msg_id}"

        text += f"{idx}. 🎬 <b>{title}{year}</b>\n"
        if info_line:
            text += f"   {info_line}\n"
        text += f"   👉 <a href='{post_url}'>Tonton di Channel</a>\n\n"

        buttons.append([InlineKeyboardButton(f"🎬 {idx}. {title}{year}", url=post_url)])

    await msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(buttons[:5])
    )


@app.on_message(filters.command("autojoin"))
async def autojoin_cmd(client: Client, msg: Message):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        curr = _engine.cache.get_setting("global_autojoin", "on")
        status = "Aktif (On)" if curr != "off" else "Mati (Off)"
        await msg.reply_text(
            f"👥 <b>Auto-Approve Join Request:</b> <b>{status}</b>\n\n"
            "Fitur ini otomatis menyetujui member yang mengajukan join request ke channel private Anda dan mengirimkan pesan sambutan + tombol pencarian film ke PM mereka.\n\n"
            "<b>Perintah:</b>\n"
            "• <code>/autojoin on</code> (Aktifkan auto-approve)\n"
            "• <code>/autojoin off</code> (Matikan auto-approve)",
            parse_mode=ParseMode.HTML
        )
        return

    sub = args[1].strip().lower()
    if sub == "off":
        _engine.cache.set_setting("global_autojoin", "off")
        await msg.reply_text("⏹️ <b>Auto-approve join request dinonaktifkan.</b>", parse_mode=ParseMode.HTML)
    else:
        _engine.cache.set_setting("global_autojoin", "on")
        await msg.reply_text("✅ <b>Auto-approve join request diaktifkan!</b>", parse_mode=ParseMode.HTML)


def parse_movie_from_channel_message(msg: Message) -> Optional[Dict[str, Any]]:
    media = msg.video or msg.document
    if not media:
        return None

    if msg.document:
        mime = getattr(msg.document, "mime_type", "") or ""
        fname = getattr(msg.document, "file_name", "") or ""
        if not (mime.startswith("video/") or re.search(r"\.(mp4|mkv|avi|webm|mov)$", fname, re.I)):
            return None

    caption = msg.caption or ""
    plain = re.sub(r"<[^>]+>", "", caption) if caption else ""

    title, year, rating, genre, quality = None, None, None, None, None

    if plain:
        m_head = re.search(r"🎬\s*([^\n\(•]+)(?:\s*\((\d{4})\))?", plain)
        if m_head:
            title = m_head.group(1).strip()
            if m_head.group(2):
                try:
                    year = int(m_head.group(2))
                except ValueError:
                    pass

        if not year:
            m_year = re.search(r"(?:Tahun|🗓️)[^\d\n]*(\d{4})", plain, re.I)
            if m_year:
                try:
                    year = int(m_year.group(1))
                except ValueError:
                    pass

        m_rate = re.search(r"⭐[^\d\n]*([\d\.]+(?:/\d+)?)", plain)
        if m_rate:
            rating = m_rate.group(1).strip()

        m_genre = re.search(r"(?:🎭|Genre)[^\n:]*:\s*([^\n]+)", plain, re.I)
        if m_genre:
            genre = m_genre.group(1).strip()

        m_qual = re.search(r"(?:🎞️|Kualitas|Resolusi)[^\n:]*:\s*([^\n]+)", plain, re.I)
        if m_qual:
            quality = m_qual.group(1).strip()

    if not title:
        file_name = getattr(media, "file_name", "") or ""
        if file_name:
            parsed = _engine.parser.parse(file_name)
            title = parsed.get("title")
            if not year and parsed.get("year"):
                year = parsed.get("year")
            if not quality and parsed.get("resolution"):
                quality = parsed.get("resolution")

    if not title:
        return None

    return {
        "title": title,
        "year": year,
        "rating": rating,
        "genre": genre,
        "quality": quality,
        "message_id": msg.id,
        "caption": caption
    }


async def update_pinned_catalog(client: Client, channel_username: str, chat_id: Optional[int] = None) -> int:
    """Update or create the pinned alphabetical A-Z catalog in the channel.
    Automatically deduplicates movies, keeping only the latest post.
    """
    clean_channel = (channel_username or "").lstrip("@").strip()
    if not clean_channel:
        return 0

    movies = _engine.cache.get_deduplicated_catalog(clean_channel)
    bot_user = getattr(client, "me", None)
    if not bot_user:
        try:
            bot_user = await client.get_me()
        except Exception:
            pass
    bot_username = bot_user.username if bot_user else ""

    catalog_text = format_pinned_catalog(movies, clean_channel, bot_username)

    catalog_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Cari Koleksi Film", switch_inline_query_current_chat="")
        ]
    ])

    pinned_key = f"pinned_catalog_{clean_channel}"
    stored_msg_id = _engine.cache.get_setting(pinned_key, "")

    if stored_msg_id:
        try:
            msg_id_int = int(stored_msg_id)
            await client.edit_message_text(
                chat_id=channel_username,
                message_id=msg_id_int,
                text=catalog_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=catalog_kb
            )
            logger.info(f"Updated existing pinned catalog in {channel_username} (msg {msg_id_int})")
            return len(movies)
        except Exception as e:
            logger.warning(f"Could not edit pinned catalog msg {stored_msg_id}: {e}. Creating new pin...")

    try:
        new_msg = await client.send_message(
            chat_id=channel_username,
            text=catalog_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=catalog_kb
        )
        await client.pin_chat_message(
            chat_id=channel_username,
            message_id=new_msg.id,
            disable_notification=True
        )
        _engine.cache.set_setting(pinned_key, str(new_msg.id))
        logger.info(f"Created & pinned new catalog message in {channel_username} (msg {new_msg.id})")
        return len(movies)
    except Exception as e:
        logger.error(f"Failed to post/pin catalog in {channel_username}: {e}")
        return len(movies)


@app.on_message(filters.command(["synckatalog", "scanchannel"]))
async def sync_catalog_cmd(client: Client, msg: Message):
    chat_id = msg.chat.id
    wm = _get_user_watermark(chat_id)
    clean_wm = (wm or "").lstrip("@").strip()
    if not clean_wm:
        await msg.reply_text("❌ Channel watermark belum diatur. Gunakan <code>/setwatermark @namachannel</code> terlebih dahulu.")
        return

    status_msg = await msg.reply_text(
        f"⏳ <b>Memulai Pemindaian Channel @{clean_wm}...</b>\n\n"
        "• Membaca riwayat postingan film di channel...\n"
        "• Menyaring film duplikat (mengambil post paling terbaru)...\n"
        "• Memperbarui Pinned Catalog A-Z...",
        parse_mode=ParseMode.HTML
    )

    scanned_total = 0
    scanned_movies = 0

    try:
        async for ch_msg in client.get_chat_history(wm, limit=1000):
            scanned_total += 1
            info = parse_movie_from_channel_message(ch_msg)
            if info:
                scanned_movies += 1
                _engine.cache.save_movie_post(
                    title=info["title"],
                    year=info["year"],
                    rating=info["rating"],
                    genre=info["genre"],
                    quality=info["quality"],
                    channel_username=clean_wm,
                    message_id=info["message_id"],
                    caption=info["caption"]
                )

        unique_count = await update_pinned_catalog(client, wm, chat_id=chat_id)
        duplicates_removed = max(0, scanned_movies - unique_count)

        await status_msg.edit_text(
            f"✅ <b>Sinkronisasi & Pinned Catalog Selesai!</b>\n\n"
            f"📢 <b>Channel:</b> @{clean_wm}\n"
            f"📊 <b>Total Postingan Dipindai:</b> {scanned_total}\n"
            f"🎬 <b>Total Film Ditemukan:</b> {scanned_movies}\n"
            f"🧹 <b>Film Duplikat Dibersihkan:</b> {duplicates_removed} (diambil post terbaru)\n"
            f"📚 <b>Koleksi Unik di Pinned Catalog:</b> {unique_count} film\n\n"
            f"📌 <i>Pesan indeks katalog A-Z telah diperbarui dan di-pin di channel!</i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Sync catalog error")
        await status_msg.edit_text(
            f"❌ <b>Gagal Menyinkronkan Channel:</b>\n\n<code>{e}</code>\n\n"
            "<i>Pastikan bot sudah dijadikan Administrator di channel dengan izin Kirim & Pin Pesan!</i>",
            parse_mode=ParseMode.HTML
        )


@app.on_message(filters.video | filters.document)
async def receive_video(client: Client, msg: Message):
    media = msg.video or msg.document
    if not media:
        return

    chat_id = msg.chat.id
    wm = _get_user_watermark(chat_id)
    filename = extract_filename(media, msg)
    file_size_bytes = getattr(media, "file_size", 0) or 0
    file_size_str = format_size(file_size_bytes)
    duration_str = format_duration(getattr(media, "duration", 0))

    extra = {}
    if file_size_str:
        extra["fileSize"] = file_size_str
    if duration_str:
        extra["duration"] = duration_str

    syn_enabled = _engine.cache.get_setting(f"synopsis_{chat_id}", "on") != "off"
    result = await _engine.process(filename, extra=extra, watermark=wm, enable_synopsis=syn_enabled)
    caption = result["caption"]

    tmp = tempfile.mkdtemp()
    thumb_path = None
    try:
        if getattr(media, "thumbs", None):
            raw = os.path.join(tmp, "raw_auto")
            await client.download_media(media.thumbs[0].file_id, file_name=raw)
            thumb_path = os.path.join(tmp, "thumb.jpg")
            await photo_thumbnail(raw, thumb_path)
        else:
            thumb_path = os.path.join(tmp, "black.jpg")
            await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240",
                "-frames:v", "1", thumb_path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )

        sent = await client.send_video(
            chat_id=chat_id,
            video=media.file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            thumb=thumb_path,
            supports_streaming=True,
            reply_markup=get_caption_kb(msg.id, wm)
        )
        if sent:
            await _apply_expandable_caption(chat_id, sent.id, caption, get_caption_kb(msg.id, wm))

        _jobs[chat_id] = {
            "filename": filename,
            "sent_msg": sent,
            "caption_text": caption,
            "extra": extra,
            "watermark": wm,
            "metadata": result.get("metadata", {})
        }
    except Exception as e:
        logger.exception("Send video error")
        await msg.reply_text(f"❌ Gagal: {str(e)[:100]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.on_callback_query(filters.regex(r"^copy:"))
async def handle_copy_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)
    caption = job.get("caption_text") if job else (call.message.caption or "")

    if not caption:
        await call.answer("Caption tidak ditemukan.", show_alert=True)
        return

    await call.answer("Teks siap disalin!")
    await call.message.reply_text(
        f"📋 <b>Salin Caption (Klik teks di bawah untuk copy):</b>\n\n"
        f"<code>{caption}</code>",
        parse_mode=ParseMode.HTML
    )


@app.on_callback_query(filters.regex(r"^post:"))
async def handle_post_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)
    if not job:
        await call.answer("Job kadaluarsa.", show_alert=True)
        return

    wm = _get_user_watermark(chat_id)
    if not wm.startswith("@") or len(wm) <= 1:
        await call.answer("Channel belum diatur. Gunakan /setwatermark @namachannel", show_alert=True)
        return

    await call.answer("🚀 Mengirim ke channel...")
    try:
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}"

        meta = job.get("metadata", {})
        title_meta = meta.get("title") or "Film Ini"
        year_meta = meta.get("year")
        title_display = f"{title_meta} ({year_meta})" if year_meta else title_meta
        share_text = f"Nonton film {title_display} di {wm}!"
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(channel_url)}&text={urllib.parse.quote(share_text)}"

        trailer_query = f"Trailer {title_meta}" + (f" {year_meta}" if year_meta else "")
        trailer_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(trailer_query)}"

        row1 = [
            InlineKeyboardButton(f"📢 Gabung {wm}", url=channel_url),
            InlineKeyboardButton("🎬 Tonton Trailer", url=trailer_url)
        ]

        req_link = _get_user_request_link(chat_id)
        if req_link and req_link.lower() != "off":
            row2 = [
                InlineKeyboardButton("💬 Request Film", url=req_link),
                InlineKeyboardButton("🔄 Bagikan Film", url=share_url)
            ]
        else:
            row2 = [
                InlineKeyboardButton("🔄 Bagikan Film", url=share_url)
            ]

        channel_kb = InlineKeyboardMarkup([row1, row2])

        sent_channel = await client.send_video(
            chat_id=wm,
            video=job["sent_msg"].video.file_id,
            caption=job["caption_text"],
            parse_mode=ParseMode.HTML,
            supports_streaming=True,
            reply_markup=channel_kb
        )
        if sent_channel:
            await _apply_expandable_caption(wm, sent_channel.id, job["caption_text"], channel_kb)

        # Kirim stiker pemisah otomatis di bawah film
        await _send_channel_divider(client, chat_id, wm)

        # Simpan ke katalog pencarian film
        try:
            _engine.cache.save_movie_post(
                title=title_meta,
                year=year_meta,
                rating=meta.get("rating"),
                genre=meta.get("genre"),
                quality=meta.get("resolution") or meta.get("quality"),
                channel_username=clean_wm,
                message_id=sent_channel.id,
                caption=job["caption_text"]
            )
        except Exception as ce:
            logger.warning(f"Gagal mencatat ke katalog film: {ce}")

        # Update pinned catalog channel otomatis
        try:
            await update_pinned_catalog(client, wm)
        except Exception as pce:
            logger.warning(f"Gagal memperbarui pinned catalog: {pce}")

        await call.message.reply_text(
            f"✅ <b>Berhasil Diposting ke {wm}!</b>\n\n"
            f"• Film sudah terbit lengkap dengan tombol [ Gabung ], [ Trailer ], [ Request ], dan [ Bagikan ]\n"
            f"• Film otomatis masuk ke katalog pencarian (<code>/cari {title_meta}</code>)\n"
            f"• Pinned Catalog A-Z di channel otomatis diperbarui!\n"
            f"• Stiker pemisah otomatis terkirim di bawahnya sebagai pembatas!",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Post to channel error")
        err_msg = str(e)
        await call.message.reply_text(
            f"❌ <b>Gagal Posting ke {wm}:</b>\n\n"
            f"<code>{err_msg[:120]}</code>\n\n"
            f"💡 <b>Solusi:</b>\n"
            f"1. Buka channel <b>{wm}</b> Anda di Telegram.\n"
            f"2. Tambahkan bot ini sebagai <b>Administrator</b> (izin Post Messages).\n"
            f"3. Tekan lagi tombol <b>🚀 Posting ke Channel</b>!",
            parse_mode=ParseMode.HTML
        )


@app.on_callback_query(filters.regex(r"^info:"))
async def handle_info_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)

    if not job:
        await call.answer("Job kadaluarsa.", show_alert=True)
        return

    wm = _get_user_watermark(chat_id)
    await call.answer("🔄 Memformat ulang...")
    try:
        syn_enabled = _engine.cache.get_setting(f"synopsis_{chat_id}", "on") != "off"
        result = await _engine.process(job["filename"], extra=job.get("extra"), watermark=wm, enable_synopsis=syn_enabled)
        caption = result["caption"]
        job["caption_text"] = caption
        job["metadata"] = result.get("metadata", {})
        await call.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=get_caption_kb(call.message.id, wm)
        )
        await _apply_expandable_caption(chat_id, call.message.id, caption, get_caption_kb(call.message.id, wm))
        await call.answer("✅ Selesai diformat ulang!")
    except Exception as e:
        logger.exception("Info fetch error")
        await call.answer(f"❌ Gagal: {str(e)[:50]}")


@app.on_callback_query(filters.regex(r"^edit:"))
async def handle_edit_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)

    if not job:
        await call.answer("Job kadaluarsa.", show_alert=True)
        return

    caption = job.get("caption_text", "")
    if not caption:
        await call.answer("Belum ada caption.")
        return

    _jobs[chat_id]["state"] = "waiting_edit"
    _jobs[chat_id]["edit_timeout"] = time.time() + 300  # 5 menit

    await call.message.reply_text(
        "✏️ <b>Mode Edit Caption</b> (5 menit)\n\n"
        "Salin, edit bagian yang mau diubah, lalu kirim balik:\n\n"
        f"<code>{caption}</code>",
        parse_mode=ParseMode.HTML
    )
    await call.answer("Mode edit aktif (5 menit)")


@app.on_message(filters.text)
async def handle_edit_caption(client: Client, msg: Message):
    if msg.command:
        return
    chat_id = msg.chat.id
    job = _jobs.get(chat_id)

    if not job or job.get("state") != "waiting_edit":
        return

    if time.time() > job.get("edit_timeout", 0):
        _jobs[chat_id].pop("state", None)
        _jobs[chat_id].pop("edit_timeout", None)
        await msg.reply_text("⏰ Waktu edit habis (5 menit).")
        return

    new_caption = msg.text.strip()
    if not new_caption:
        await msg.reply_text("Caption kosong.")
        return

    try:
        sent_id = _jobs[chat_id]["sent_msg"].id
        wm = _get_user_watermark(chat_id)
        kb = get_caption_kb(sent_id, wm)
        await client.edit_message_caption(
            chat_id=chat_id,
            message_id=sent_id,
            caption=msg.text,
            parse_mode=ParseMode.HTML
        )
        await _apply_expandable_caption(chat_id, sent_id, msg.text, kb)
        _jobs[chat_id]["caption_text"] = msg.text
        _jobs[chat_id].pop("state", None)
        _jobs[chat_id].pop("edit_timeout", None)
        await msg.reply_text("✅ Caption berhasil diperbarui!")
    except Exception as e:
        logger.exception("Edit caption error")
        await msg.reply_text(f"❌ Gagal: {str(e)[:100]}")


@app.on_inline_query()
async def inline_search_handler(client: Client, query: InlineQuery):
    q = query.query.strip()
    results = _engine.cache.search_catalog(q, limit=15)

    articles = []
    for item in results:
        title = item["title"]
        year = f" ({item['year']})" if item.get("year") else ""
        full_title = f"{title}{year}"
        rating = f"⭐ {item['rating']}" if item.get("rating") else ""
        genre = f"🎭 {item['genre']}" if item.get("genre") else ""
        desc_parts = [p for p in [rating, genre] if p]
        description = " | ".join(desc_parts) or "Koleksi Film Channel"
        channel = item["channel_username"].lstrip("@")
        msg_id = item["message_id"]
        post_url = f"https://t.me/{channel}/{msg_id}"

        msg_content = (
            f"🎬 <b>{full_title}</b>\n\n"
            f"⭐ Rating: {item.get('rating') or '-'}\n"
            f"🎭 Genre: {item.get('genre') or '-'}\n"
            f"📢 Channel: @{channel}\n\n"
            f"👉 <a href='{post_url}'>Klik di sini untuk menonton film</a>"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🍿 Tonton Film di Channel", url=post_url)]
        ])

        articles.append(
            InlineQueryResultArticle(
                title=full_title,
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=msg_content,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                ),
                reply_markup=kb
            )
        )

    await query.answer(
        results=articles,
        cache_time=5,
        is_personal=True,
        switch_pm_text="🔍 Cari Film di Bot" if not articles else None,
        switch_pm_parameter="search" if not articles else None
    )


@app.on_chat_join_request()
async def auto_approve_join_request(client: Client, req: ChatJoinRequest):
    autojoin_status = _engine.cache.get_setting("global_autojoin", "on")
    if autojoin_status == "off":
        return

    try:
        await req.approve()
        logger.info(f"Auto-approved join request for user {req.from_user.id} in chat {req.chat.id}")
    except Exception as e:
        logger.error(f"Gagal menyetujui join request: {e}")
        return

    try:
        chat_title = req.chat.title or "Channel Film"
        user_name = req.from_user.first_name or "Sobat Film"
        welcome_text = (
            f"👋 Halo <b>{user_name}</b>!\n\n"
            f"✅ Permintaan bergabung Anda ke <b>{chat_title}</b> sudah disetujui otomatis.\n\n"
            f"🍿 Selamat menonton! Anda bisa mencari koleksi film langsung melalui tombol di bawah:"
        )

        buttons = []
        if req.chat.username:
            buttons.append([InlineKeyboardButton(f"🍿 Buka {chat_title}", url=f"https://t.me/{req.chat.username}")])
        buttons.append([InlineKeyboardButton("🔍 Cari Koleksi Film", switch_inline_query_current_chat="")])

        await client.send_message(
            chat_id=req.from_user.id,
            text=welcome_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.debug(f"Info PM user welcome join request: {e}")