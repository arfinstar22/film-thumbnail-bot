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
from typing import Union, Optional, Dict, Any, List

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChatJoinRequest
)
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

from .config import BOT_TOKEN, API_ID, API_HASH, SESSION_STRING, CHANNEL_WATERMARK, DEFAULT_REQUEST_LINK
from .services.video import photo_thumbnail
from .services.metadata.engine import MetadataEngine
from .services.metadata.catalog import format_pinned_catalog, publish_or_update_telegraph_catalog

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
            BotCommand("autopost", "Atur mode posting: Otomatis atau Manual"),
            BotCommand("cari", "Cari film di database channel"),
            BotCommand("synckatalog", "Scan channel & update Pinned Catalog A-Z"),
            BotCommand("backup", "Backup katalog & file_id film ke file JSON"),
            BotCommand("restorechannel", "Restore/migrasi semua film ke channel baru"),
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
    autopost_val = _engine.cache.get_setting(f"autopost_{msg.chat.id}", "off")

    div_status = "Logo Custom Film Indonesia" if divider == "default" else ("Mati (Off)" if divider == "off" else "Stiker Pilihan Anda")
    req_status = f"<code>{req_link}</code>" if req_link and req_link != "off" else ("Mati (Off)" if req_link == "off" else "<i>Belum diatur</i>")
    syn_status = "Aktif (On)" if syn_val != "off" else "Mati (Off)"
    autojoin_status = "Aktif (On)" if autojoin_val != "off" else "Mati (Off)"
    autopost_status = "⚡ Otomatis (Langsung Terbit)" if autopost_val == "on" else "✋ Manual (Pratinjau Dulu)"

    text = (
        "🎬 <b>FILM CLEANER & PUBLISHER BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang! Bot ini otomatis membersihkan watermark lama, mengekstrak rating & genre resmi, merapikan sinopsis lipat, dan menerbitkan langsung ke channel Telegram Anda.\n\n"
        "📌 <b>DAFTAR PERINTAH (COMMANDS):</b>\n\n"
        "• <code>/start</code>\n"
        "  Menampilkan menu bantuan dan daftar fitur ini.\n\n"
        "• <code>/autopost</code>\n"
        "  Mengatur mode upload ke channel: Otomatis langsung kirim vs Manual pratinjau dulu.\n"
        f"  <i>Mode aktif saat ini:</i> <b>{autopost_status}</b>\n\n"
        "• <code>/cari &lt;judul film&gt;</code>\n"
        "  Mencari film di katalog channel dengan link tonton langsung.\n"
        "  ▫️ <i>Mode Inline:</i> Ketik <code>@bot &lt;judul&gt;</code> di chat mana pun!\n\n"
        "• <code>/synckatalog</code>\n"
        "  Scan riwayat channel, bersihkan film duplikat (hanya ambil post terbaru), dan perbarui Pinned Catalog A-Z di channel.\n\n"
        "• <code>/backup</code>\n"
        "  Mengekspor seluruh katalog film beserta file_id Telegram ke file JSON untuk cadangan darurat.\n\n"
        "• <code>/restorechannel @channel_baru</code>\n"
        "  Restore / migrasi otomatis semua film ke channel baru dengan jeda anti-spam.\n"
        "  ▫️ <i>Tips:</i> Reply file <code>katalog_backup.json</code> dengan <code>/restorechannel @channel_baru</code>.\n\n"
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


def get_autopost_kb(current_mode: str) -> InlineKeyboardMarkup:
    is_auto = (current_mode == "on")
    btn_auto_text = "✅ ⚡ Otomatis (Langsung Terbit)" if is_auto else "⚡ Otomatis (Langsung Terbit)"
    btn_manual_text = "✅ ✋ Manual (Pratinjau Dulu)" if not is_auto else "✋ Manual (Pratinjau Dulu)"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(btn_auto_text, callback_data="autopost:on")
        ],
        [
            InlineKeyboardButton(btn_manual_text, callback_data="autopost:off")
        ]
    ])


@app.on_message(filters.command(["autopost", "setautopost", "mode"]))
async def set_autopost_cmd(client: Client, msg: Message):
    chat_id = msg.chat.id
    args = msg.text.split(maxsplit=1)

    if len(args) > 1:
        subcmd = args[1].strip().lower()
        if subcmd in ["on", "auto", "otomatis", "1", "true"]:
            _engine.cache.set_setting(f"autopost_{chat_id}", "on")
            await msg.reply_text(
                "✅ <b>Mode Auto-Post DIAKTIFKAN!</b>\n\n"
                "Mulai sekarang, setiap kali Anda kirim atau forward video film ke bot ini:\n"
                "• Bot akan otomatis merapikan thumbnail & caption.\n"
                "• <b>Langsung otomatis diterbitkan ke channel</b> tanpa perlu klik tombol lagi!\n\n"
                "<i>Untuk kembali ke mode manual, ketik <code>/autopost off</code>.</i>",
                parse_mode=ParseMode.HTML
            )
            return
        elif subcmd in ["off", "manual", "0", "false"]:
            _engine.cache.set_setting(f"autopost_{chat_id}", "off")
            await msg.reply_text(
                "✋ <b>Mode Posting Diubah ke MANUAL!</b>\n\n"
                "Setiap kali Anda kirim/forward video ke bot:\n"
                "• Bot hanya akan mengirimkan pratinjau hasil rapi di chat ini.\n"
                "• Anda bisa memeriksa atau mengedit teks dulu sebelum menekan tombol <b>🚀 Posting ke Channel</b>.",
                parse_mode=ParseMode.HTML
            )
            return

    curr = _engine.cache.get_setting(f"autopost_{chat_id}", "off")
    wm = _get_user_watermark(chat_id)
    status_label = "⚡ Otomatis (Langsung Terbit ke Channel)" if curr == "on" else "✋ Manual (Pratinjau Dulu)"

    text = (
        "⚙️ <b>PENGATURAN MODE POSTING FILM:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• Status Saat Ini: <b>{status_label}</b>\n"
        f"• Channel Tujuan: <b>{wm}</b>\n\n"
        "<b>Pilihan Mode:</b>\n"
        "1. <b>⚡ Otomatis (Auto-Post)</b>:\n"
        "   Cocok jika Anda ingin upload massal / forward cepat. Media langsung diterbitkan ke channel secara instan.\n\n"
        "2. <b>✋ Manual</b>:\n"
        "   Bot memberi pratinjau di sini dulu. Anda bisa memeriksa atau mengedit teks sebelum memposting.\n\n"
        "👇 <b>Pilih mode posting di bawah:</b>"
    )

    await msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_autopost_kb(curr)
    )


@app.on_callback_query(filters.regex(r"^autopost:(on|off)$"))
async def handle_autopost_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    target_mode = call.matches[0].group(1)

    _engine.cache.set_setting(f"autopost_{chat_id}", target_mode)
    status_label = "⚡ Otomatis (Langsung Terbit ke Channel)" if target_mode == "on" else "✋ Manual (Pratinjau Dulu)"
    wm = _get_user_watermark(chat_id)

    await call.answer(f"Mode posting diubah ke: {status_label}")

    text = (
        "⚙️ <b>PENGATURAN MODE POSTING FILM:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• Status Saat Ini: <b>{status_label}</b>\n"
        f"• Channel Tujuan: <b>{wm}</b>\n\n"
        "<b>Pilihan Mode:</b>\n"
        "1. <b>⚡ Otomatis (Auto-Post)</b>:\n"
        "   Cocok jika Anda ingin upload massal / forward cepat. Media langsung diterbitkan ke channel secara instan.\n\n"
        "2. <b>✋ Manual</b>:\n"
        "   Bot memberi pratinjau di sini dulu. Anda bisa memeriksa atau mengedit teks sebelum memposting.\n\n"
        "👇 <b>Pilih mode posting di bawah:</b>"
    )

    try:
        await call.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_autopost_kb(target_mode)
        )
    except Exception:
        pass


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
            lines = [l.strip() for l in plain.split("\n") if l.strip() and not l.startswith("━")]
            if lines:
                first_line = lines[0]
                if not re.search(r"(channel|official|gabung|join|link)", first_line, re.I):
                    parsed_line = _engine.parser.parse(first_line)
                    if parsed_line.get("title"):
                        title = parsed_line["title"]
                        if not year and parsed_line.get("year"):
                            year = parsed_line["year"]
                        if not quality and parsed_line.get("resolution"):
                            quality = parsed_line["resolution"]

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
        "caption": caption,
        "file_id": getattr(media, "file_id", None)
    }


async def auto_hydrate_channel_catalog(
    client: Client,
    channel_username: str,
    scan_limit: int = 5000
) -> int:
    """Scans channel history in fast batches to populate the local database cache with all existing movies.
    Ensures that when a bot restarts or redeploys, it never loses older movies from the catalog.
    """
    clean_channel = (channel_username or "").lstrip("@").strip().lower()
    if not clean_channel:
        return 0

    max_id = 0
    try:
        probe = await client.send_message(channel_username, "🔄", disable_notification=True)
        max_id = probe.id
        await probe.delete()
    except Exception as pe:
        logger.warning(f"Could not probe max message id in {channel_username}: {pe}")
        stored_pin = _engine.cache.get_setting(f"pinned_catalog_{clean_channel}", "")
        max_id = int(stored_pin) if stored_pin and stored_pin.isdigit() else 2000

    start_id = max(1, max_id - scan_limit)
    batch_size = 100
    scanned_movies = 0

    for batch_start in range(start_id, max_id + 1, batch_size):
        batch_ids = list(range(batch_start, min(batch_start + batch_size, max_id + 1)))
        try:
            msgs = await client.get_messages(channel_username, message_ids=batch_ids)
            if not isinstance(msgs, list):
                msgs = [msgs]
            for ch_msg in msgs:
                if not ch_msg or getattr(ch_msg, "empty", False):
                    continue
                if getattr(ch_msg, "service", None) or getattr(ch_msg, "pinned_message", None):
                    continue
                msg_text = getattr(ch_msg, "text", "") or getattr(ch_msg, "caption", "") or ""
                if "KATALOG KOLEKSI FILM" in msg_text or "KATALOG & DAFTAR ISI" in msg_text:
                    continue

                info = parse_movie_from_channel_message(ch_msg)
                if info:
                    scanned_movies += 1
                    _engine.cache.save_movie_post(
                        title=info["title"],
                        year=info["year"],
                        rating=info["rating"],
                        genre=info["genre"],
                        quality=info["quality"],
                        channel_username=clean_channel,
                        message_id=info["message_id"],
                        caption=info["caption"],
                        file_id=info.get("file_id")
                    )
        except Exception as be:
            logger.debug(f"Hydration batch fetch error: {be}")
        await asyncio.sleep(0.02)

    _engine.cache.set_setting(f"synced_{clean_channel}", "yes")
    return scanned_movies


async def update_pinned_catalog(
    client: Client,
    channel_username: str,
    chat_id: Optional[int] = None,
    old_catalog_ids: Optional[List[int]] = None
) -> int:
    """Update or create the pinned alphabetical A-Z catalog in the channel.
    Guarantees that older duplicate catalog messages are deleted and unpinned,
    leaving strictly ONE clean pinned catalog in the channel.
    """
    clean_channel = (channel_username or "").lstrip("@").strip()
    if not clean_channel:
        return 0

    movies = _engine.cache.get_deduplicated_catalog(clean_channel)

    # AUTO-HYDRATION SAFEGUARD:
    # If cache has fewer than 50 movies or has never been hydrated on this container instance,
    # automatically scan channel history so we NEVER overwrite the catalog with just a few films!
    has_synced = _engine.cache.get_setting(f"synced_{clean_channel.lower()}", "no")
    if has_synced != "yes" or len(movies) < 50:
        logger.info(f"Channel @{clean_channel} has only {len(movies)} movies in local DB (synced={has_synced}). Auto-hydrating...")
        try:
            await auto_hydrate_channel_catalog(client, clean_channel)
            movies = _engine.cache.get_deduplicated_catalog(clean_channel)
            _engine.cache.set_setting(f"synced_{clean_channel.lower()}", "yes")
            logger.info(f"Auto-hydration completed for @{clean_channel}. Total movies: {len(movies)}")
        except Exception as he:
            logger.warning(f"Auto-hydration error in update_pinned_catalog: {he}")

    bot_user = getattr(client, "me", None)
    if not bot_user:
        try:
            bot_user = await client.get_me()
        except Exception:
            pass
    bot_username = bot_user.username if bot_user else ""

    # Publish / update Telegra.ph Instant View page
    telegraph_url = publish_or_update_telegraph_catalog(movies, clean_channel, _engine.cache, bot_username)

    catalog_text = format_pinned_catalog(movies, clean_channel, bot_username, telegraph_url)

    buttons = []
    if telegraph_url:
        buttons.append([
            InlineKeyboardButton(f"⚡ BUKA KATALOG LENGKAP ({len(movies)} Film)", url=telegraph_url)
        ])
    buttons.append([
        InlineKeyboardButton("🔍 Cari Koleksi Film", switch_inline_query_current_chat="")
    ])
    req_link = _get_user_request_link(chat_id) if chat_id else (_engine.cache.get_setting("global_request_link", "") or DEFAULT_REQUEST_LINK)
    if req_link and req_link != "off":
        buttons.append([
            InlineKeyboardButton("💬 Request Film", url=req_link)
        ])
    catalog_kb = InlineKeyboardMarkup(buttons)

    pinned_key = f"pinned_catalog_{clean_channel}"
    stored_msg_id_str = _engine.cache.get_setting(pinned_key, "")
    stored_msg_id = int(stored_msg_id_str) if stored_msg_id_str and stored_msg_id_str.isdigit() else None

    # Track all known older catalog message IDs
    all_old_ids = set()
    if old_catalog_ids:
        all_old_ids.update(old_catalog_ids)
    if stored_msg_id:
        all_old_ids.add(stored_msg_id)

    # Check Telegram channel pinned message directly
    current_pin_id = None
    try:
        chat_info = await client.get_chat(channel_username)
        if chat_info.pinned_message:
            current_pin_id = chat_info.pinned_message.id
            pin_text = getattr(chat_info.pinned_message, "text", "") or getattr(chat_info.pinned_message, "caption", "") or ""
            if "KATALOG" in pin_text or "BUKA KATALOG" in pin_text:
                all_old_ids.add(current_pin_id)
    except Exception as ce:
        logger.warning(f"Could not check chat pinned message: {ce}")

    # Determine target message ID to reuse
    target_msg_id = max(all_old_ids) if all_old_ids else None
    edited_successfully = False

    if target_msg_id:
        try:
            await client.edit_message_text(
                chat_id=channel_username,
                message_id=target_msg_id,
                text=catalog_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=catalog_kb
            )
            edited_successfully = True
            logger.info(f"Edited active catalog in {channel_username} (msg {target_msg_id})")
        except Exception as e:
            logger.warning(f"Could not edit catalog message {target_msg_id}: {e}")

    if not edited_successfully:
        try:
            new_msg = await client.send_message(
                chat_id=channel_username,
                text=catalog_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=catalog_kb
            )
            target_msg_id = new_msg.id
            logger.info(f"Created new catalog message in {channel_username} (msg {target_msg_id})")
        except Exception as e:
            logger.error(f"Failed to send catalog message in {channel_username}: {e}")
            return len(movies)

    _engine.cache.set_setting(pinned_key, str(target_msg_id))

    # DELETE all older duplicate catalog messages from channel completely!
    stray_ids = [mid for mid in all_old_ids if mid != target_msg_id]
    if stray_ids:
        try:
            await client.delete_messages(channel_username, stray_ids)
            logger.info(f"Deleted {len(stray_ids)} older duplicate catalog messages: {stray_ids}")
        except Exception as de:
            logger.warning(f"Could not delete older catalog messages: {de}")

    # Ensure strictly ONE pin: unpin all and pin target only
    try:
        await client.unpin_all_chat_messages(channel_username)
        pinned_res = await client.pin_chat_message(
            chat_id=channel_username,
            message_id=target_msg_id,
            disable_notification=True
        )
        if pinned_res and getattr(pinned_res, "id", None) and (getattr(pinned_res, "service", None) or getattr(pinned_res, "pinned_message", None)):
            try:
                await client.delete_messages(channel_username, [pinned_res.id])
            except Exception:
                pass

        # Cleanup any service notification messages in channel history
        try:
            serv_ids = []
            async for m in client.get_chat_history(channel_username, limit=10):
                if m and m.id != target_msg_id and (getattr(m, "service", None) or getattr(m, "pinned_message", None)):
                    serv_ids.append(m.id)
            if serv_ids:
                await client.delete_messages(channel_username, serv_ids)
                logger.info(f"Cleaned {len(serv_ids)} service messages in {channel_username}: {serv_ids}")
        except Exception:
            pass
    except Exception as pe:
        logger.warning(f"Pin management error in {channel_username}: {pe}")

    return len(movies)


@app.on_message(filters.command(["synckatalog", "scanchannel"]))
async def sync_catalog_cmd(client: Client, msg: Message):
    chat_id = msg.chat.id
    wm = _get_user_watermark(chat_id)
    clean_wm = (wm or "").lstrip("@").strip()
    if not clean_wm:
        await msg.reply_text("❌ Channel watermark belum diatur. Gunakan <code>/setwatermark @namachannel</code> terlebih dahulu.")
        return

    # Check optional scan limit (default 1000 messages)
    args = msg.text.split(maxsplit=1)
    scan_limit = 1000
    if len(args) > 1:
        arg_val = args[1].strip().lower()
        if arg_val == "all":
            scan_limit = 10000
        elif arg_val.isdigit():
            scan_limit = min(10000, max(50, int(arg_val)))

    status_msg = await msg.reply_text(
        f"⏳ <b>Memulai Pemindaian Channel @{clean_wm}...</b>\n\n"
        f"• Membaca riwayat hingga {scan_limit} postingan...\n"
        "• Menyaring film duplikat (mengambil post paling terbaru)...\n"
        "• Membersihkan pesan tersemat (pin) & notifikasi lama...\n"
        "• Memperbarui Pinned Catalog A-Z...",
        parse_mode=ParseMode.HTML
    )

    try:
        # Determine highest message ID in channel via silent probe message
        probe = await client.send_message(wm, "🔄 Sinkronisasi katalog...", disable_notification=True)
        max_id = probe.id
        await probe.delete()
    except Exception as pe:
        logger.warning(f"Could not probe max message id in {wm}: {pe}")
        stored_pin = _engine.cache.get_setting(f"pinned_catalog_{clean_wm}", "")
        max_id = int(stored_pin) if stored_pin and stored_pin.isdigit() else 500

    found_catalog_msg_ids = []
    found_service_msg_ids = []
    scanned_total = 0
    scanned_movies = 0
    start_id = max(1, max_id - scan_limit)
    batch_size = 100

    try:
        for batch_start in range(start_id, max_id, batch_size):
            batch_ids = list(range(batch_start, min(batch_start + batch_size, max_id)))
            try:
                msgs = await client.get_messages(wm, message_ids=batch_ids)
                if not isinstance(msgs, list):
                    msgs = [msgs]
                for ch_msg in msgs:
                    if not ch_msg or getattr(ch_msg, "empty", False):
                        if ch_msg and getattr(ch_msg, "id", None):
                            _engine.cache.delete_movie_posts([ch_msg.id])
                        continue

                    # Auto-detect service notification messages (e.g. "menyematkan...")
                    if getattr(ch_msg, "service", None) or getattr(ch_msg, "pinned_message", None):
                        found_service_msg_ids.append(ch_msg.id)
                        continue

                    msg_text = getattr(ch_msg, "text", "") or getattr(ch_msg, "caption", "") or ""
                    if "KATALOG KOLEKSI FILM" in msg_text or "KATALOG & DAFTAR ISI" in msg_text:
                        found_catalog_msg_ids.append(ch_msg.id)
                        continue

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
                            caption=info["caption"],
                            file_id=info.get("file_id")
                        )
            except Exception as be:
                logger.warning(f"Batch fetch error for ids {batch_ids[:2]}..: {be}")
            await asyncio.sleep(0.05)

        # Also scan recent chat history to catch all lingering service messages
        try:
            async for m in client.get_chat_history(wm, limit=50):
                if m and (getattr(m, "service", None) or getattr(m, "pinned_message", None)):
                    found_service_msg_ids.append(m.id)
        except Exception:
            pass

        # Delete any service notification messages found in channel
        if found_service_msg_ids:
            try:
                unique_serv_ids = list(set(found_service_msg_ids))
                await client.delete_messages(wm, unique_serv_ids)
                logger.info(f"Cleaned {len(unique_serv_ids)} old service messages from channel {wm}")
            except Exception as se:
                logger.warning(f"Could not delete old service messages: {se}")

        unique_count = await update_pinned_catalog(client, wm, chat_id=chat_id, old_catalog_ids=found_catalog_msg_ids)
        duplicates_removed = max(0, scanned_movies - unique_count)

        await status_msg.edit_text(
            f"✅ <b>Sinkronisasi & Pinned Catalog Selesai!</b>\n\n"
            f"📢 <b>Channel:</b> @{clean_wm}\n"
            f"📊 <b>Total Pesan Diperiksa:</b> {scanned_total}\n"
            f"🎬 <b>Total Film Ditemukan:</b> {scanned_movies}\n"
            f"🧹 <b>Film Duplikat Dibersihkan:</b> {duplicates_removed} (diambil post terbaru)\n"
            f"🗑️ <b>Pesan Lama Dihapus:</b> {len(found_catalog_msg_ids)} pin & {len(found_service_msg_ids)} notifikasi lama\n"
            f"📚 <b>Koleksi Unik di Pinned Catalog:</b> {unique_count} film\n\n"
            f"📌 <i>Pesan indeks katalog A-Z telah diperbarui dan di-pin bersih di channel!</i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("Sync catalog error")
        await status_msg.edit_text(
            f"❌ <b>Gagal Menyinkronkan Channel:</b>\n\n<code>{e}</code>\n\n"
            "<i>Pastikan bot sudah dijadikan Administrator di channel dengan izin Kirim & Pin Pesan!</i>",
            parse_mode=ParseMode.HTML
        )


async def publish_video_to_channel(
    client: Client,
    chat_id: int,
    video_file_id: str,
    caption_text: str,
    metadata: dict,
    watermark: str,
    update_pin: bool = True
) -> Optional[Message]:
    """Publishes a video post to the channel with buttons, divider sticker, cache update, and pinned catalog refresh."""
    clean_wm = watermark.lstrip("@").strip()
    channel_url = f"https://t.me/{clean_wm}"

    meta = metadata or {}
    title_meta = meta.get("title") or "Film Ini"
    year_meta = meta.get("year")
    title_display = f"{title_meta} ({year_meta})" if year_meta else title_meta
    share_text = f"Nonton film {title_display} di {watermark}!"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(channel_url)}&text={urllib.parse.quote(share_text)}"

    trailer_query = f"Trailer {title_meta}" + (f" {year_meta}" if year_meta else "")
    trailer_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(trailer_query)}"

    row1 = [
        InlineKeyboardButton(f"📢 Gabung {watermark}", url=channel_url),
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
        chat_id=watermark,
        video=video_file_id,
        caption=caption_text,
        parse_mode=ParseMode.HTML,
        supports_streaming=True,
        reply_markup=channel_kb
    )
    if sent_channel:
        await _apply_expandable_caption(watermark, sent_channel.id, caption_text, channel_kb)

    # Kirim stiker pemisah otomatis di bawah film
    await _send_channel_divider(client, chat_id, watermark)

    # Simpan ke katalog pencarian film beserta file_id cloud Telegram
    try:
        _engine.cache.save_movie_post(
            title=title_meta,
            year=year_meta,
            rating=meta.get("rating"),
            genre=meta.get("genre"),
            quality=meta.get("resolution") or meta.get("quality"),
            channel_username=clean_wm,
            message_id=sent_channel.id,
            caption=caption_text,
            file_id=video_file_id
        )
    except Exception as ce:
        logger.warning(f"Gagal mencatat ke katalog film: {ce}")

    # Update pinned catalog channel otomatis
    if update_pin:
        try:
            await update_pinned_catalog(client, watermark, chat_id=chat_id)
        except Exception as pce:
            logger.warning(f"Gagal memperbarui pinned catalog: {pce}")

    return sent_channel


@app.on_message(filters.command(["backup", "backupkatalog"]))
async def backup_catalog_cmd(client: Client, msg: Message):
    chat_id = msg.chat.id
    args = msg.text.split()[1:] if msg.text else []
    if args:
        target_wm = args[0]
    else:
        target_wm = _get_user_watermark(chat_id)

    clean_wm = (target_wm or "").lstrip("@").strip().lower()
    if not clean_wm:
        await msg.reply_text("❌ Channel belum diatur. Gunakan <code>/backup @namachannel</code>.", parse_mode=ParseMode.HTML)
        return

    status_msg = await msg.reply_text(
        f"⏳ <b>Mengekspor data katalog channel @{clean_wm}...</b>",
        parse_mode=ParseMode.HTML
    )

    try:
        movies = _engine.cache.get_deduplicated_catalog(clean_wm)
        if not movies:
            await auto_hydrate_channel_catalog(client, clean_wm)
            movies = _engine.cache.get_deduplicated_catalog(clean_wm)

        if not movies:
            await status_msg.edit_text(
                f"ℹ️ <b>Katalog Kosong:</b> Tidak ada data film untuk @{clean_wm}.\n"
                f"Ketik <code>/synckatalog</code> terlebih dahulu di channel aktif.",
                parse_mode=ParseMode.HTML
            )
            return

        json_str = _engine.cache.export_catalog_json(clean_wm)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
            tf.write(json_str)
            temp_path = tf.name

        doc_name = f"katalog_backup_{clean_wm}.json"
        caption = (
            f"💾 <b>BACKUP KATALOG KOLEKSI FILM</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Channel:</b> @{clean_wm}\n"
            f"🎬 <b>Total Film:</b> {len(movies)} judul\n"
            f"🔑 <b>Cloud File ID:</b> Tersimpan aman\n\n"
            f"💡 <b>PANDUAN RESTORE / PINDAH CHANNEL:</b>\n"
            f"Jika channel Anda diblokir atau ingin pindah ke channel baru, balas (reply) file JSON ini dengan perintah:\n"
            f"<code>/restorechannel @channel_baru</code>\n\n"
            f"<i>Bot akan otomatis memposting ulang seluruh film ke channel baru dengan jeda anti-spam 3.5 detik.</i>"
        )

        await client.send_document(
            chat_id=chat_id,
            document=temp_path,
            file_name=doc_name,
            caption=caption,
            parse_mode=ParseMode.HTML
        )
        await status_msg.delete()
        try:
            os.remove(temp_path)
        except Exception:
            pass
    except Exception as e:
        logger.exception("Backup export error")
        await status_msg.edit_text(f"❌ <b>Gagal membuat backup:</b> <code>{e}</code>", parse_mode=ParseMode.HTML)


@app.on_message(filters.command(["restorechannel", "migrasichannel", "restore"]))
async def restore_channel_cmd(client: Client, msg: Message):
    chat_id = msg.chat.id
    args = msg.text.split()[1:] if msg.text else []

    reply = msg.reply_to_message
    movies = []
    source_channel = ""
    target_channel = ""

    # Mode 1: User replies to a backup JSON file
    if reply and reply.document and (reply.document.file_name or "").endswith(".json"):
        if not args:
            await msg.reply_text(
                "⚠️ <b>Tentukan Channel Tujuan!</b>\n\n"
                "Balas file JSON backup dengan perintah:\n"
                "<code>/restorechannel @channel_baru</code>",
                parse_mode=ParseMode.HTML
            )
            return
        target_channel = args[0]
        status_msg = await msg.reply_text("📥 <b>Membaca file backup JSON...</b>", parse_mode=ParseMode.HTML)
        try:
            downloaded = await client.download_media(reply.document)
            with open(downloaded, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                os.remove(downloaded)
            except Exception:
                pass

            data = json.loads(content)
            movies = data.get("movies", [])
            source_channel = data.get("channel", "")
            # Sync into local DB for the new target channel as well
            clean_tgt = target_channel.lstrip("@").strip().lower()
            _engine.cache.import_catalog_json(content, target_channel=clean_tgt)
        except Exception as je:
            await status_msg.edit_text(f"❌ <b>File JSON tidak valid:</b> <code>{je}</code>", parse_mode=ParseMode.HTML)
            return
    else:
        # Mode 2: User restores from database
        if len(args) == 1:
            source_channel = _get_user_watermark(chat_id)
            target_channel = args[0]
        elif len(args) >= 2:
            source_channel = args[0]
            target_channel = args[1]
        else:
            await msg.reply_text(
                "📖 <b>CARA PENGGUNAAN RESTORE CHANNEL:</b>\n\n"
                "<b>Cara 1 (Rekomendasi dari File):</b>\n"
                "Reply file <code>katalog_backup.json</code> dengan perintah:\n"
                "<code>/restorechannel @channel_baru</code>\n\n"
                "<b>Cara 2 (Dari Database Bot):</b>\n"
                "<code>/restorechannel @channel_lama @channel_baru</code>\n\n"
                "⚠️ <i>Pastikan bot sudah dijadikan Administrator di channel baru sebelum memulai!</i>",
                parse_mode=ParseMode.HTML
            )
            return

        status_msg = await msg.reply_text("⏳ <b>Memeriksa data katalog film...</b>", parse_mode=ParseMode.HTML)
        clean_src = (source_channel or "").lstrip("@").strip().lower()
        movies = _engine.cache.get_deduplicated_catalog(clean_src)

    clean_target = (target_channel or "").lstrip("@").strip().lower()
    clean_src = (source_channel or "").lstrip("@").strip().lower()

    if not clean_target:
        await status_msg.edit_text("❌ Channel tujuan tidak valid!", parse_mode=ParseMode.HTML)
        return

    # Check bot permission in target channel
    try:
        test_msg = await client.send_message(f"@{clean_target}", "🔄 <i>Menguji hak akses bot untuk migrasi...</i>", parse_mode=ParseMode.HTML, disable_notification=True)
        await test_msg.delete()
    except Exception as pe:
        await status_msg.edit_text(
            f"❌ <b>Bot Tidak Bisa Mengakses Channel @{clean_target}:</b>\n\n"
            f"<code>{pe}</code>\n\n"
            f"Pastikan:\n"
            f"1. Bot sudah ditambahkan ke channel @{clean_target}.\n"
            f"2. Bot dijadikan <b>Administrator</b> dengan izin Kirim & Pin Pesan.",
            parse_mode=ParseMode.HTML
        )
        return

    # Filter movies with valid file_id
    valid_movies = [m for m in movies if m.get("file_id")]
    if not valid_movies:
        await status_msg.edit_text(
            f"❌ <b>Tidak Ada Film yang Bisa Diposting!</b>\n\n"
            f"Ditemukan {len(movies)} judul film, namun tidak ada yang memiliki <code>file_id</code> Telegram yang tersimpan.\n"
            f"<i>Lakukan sinkronisasi atau posting film agar bot dapat mencatat file_id video.</i>",
            parse_mode=ParseMode.HTML
        )
        return

    total_count = len(valid_movies)
    await status_msg.edit_text(
        f"🚀 <b>MEMULAI RESTORE KE CHANNEL BARU</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Channel Tujuan:</b> @{clean_target}\n"
        f"🎬 <b>Total Film Siap Diposting:</b> {total_count} judul\n"
        f"⏱️ <b>Jeda Anti-Spam:</b> 3.5 detik per film\n"
        f"🛡️ <b>Proteksi Spam Telegram:</b> Aktif\n\n"
        f"<i>Proses sedang berjalan. Mohon jangan hapus bot dari channel selama proses berlangsung...</i>",
        parse_mode=ParseMode.HTML
    )

    success_count = 0
    fail_count = 0

    for idx, m in enumerate(valid_movies, 1):
        m_title = m.get("title") or "Film"
        m_year = m.get("year")
        m_fid = m.get("file_id")
        caption = m.get("caption") or ""

        # Replace old watermark channel with new watermark channel in caption
        if clean_src and clean_src != clean_target:
            caption = re.sub(re.escape(f"@{clean_src}"), f"@{clean_target}", caption, flags=re.I)
            caption = re.sub(re.escape(f"t.me/{clean_src}"), f"t.me/{clean_target}", caption, flags=re.I)

        metadata = {
            "title": m_title,
            "year": m_year,
            "rating": m.get("rating"),
            "genre": m.get("genre"),
            "resolution": m.get("quality")
        }

        # Send with retry on FloodWait
        posted = False
        for attempt in range(3):
            try:
                sent = await publish_video_to_channel(
                    client=client,
                    chat_id=chat_id,
                    video_file_id=m_fid,
                    caption_text=caption,
                    metadata=metadata,
                    watermark=f"@{clean_target}",
                    update_pin=False  # Do not pin on every movie!
                )
                if sent:
                    success_count += 1
                    posted = True
                break
            except FloodWait as fw:
                wait_sec = fw.value + 3
                logger.warning(f"FloodWait during restore: waiting {wait_sec}s")
                try:
                    await status_msg.edit_text(
                        f"⏳ <b>Telegram Rate-Limit (FloodWait) Terdeteksi!</b>\n\n"
                        f"Menunggu jeda <b>{wait_sec} detik</b> secara otomatis agar aman dari spam...\n"
                        f"Progres saat ini: {idx-1}/{total_count} film.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
                await asyncio.sleep(wait_sec)
            except Exception as e:
                logger.error(f"Error publishing {m_title} during restore: {e}")
                break

        if not posted:
            fail_count += 1

        # Periodic status update in user PM every 5 movies or last movie
        if idx % 5 == 0 or idx == total_count:
            try:
                pct = int((idx / total_count) * 100)
                await status_msg.edit_text(
                    f"⏳ <b>Restoring Film ke @{clean_target}...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Progres:</b> {idx}/{total_count} ({pct}%)\n"
                    f"✅ <b>Berhasil:</b> {success_count} film\n"
                    f"❌ <b>Gagal:</b> {fail_count} film\n"
                    f"▶️ <b>Terakhir:</b> {m_title}" + (f" ({m_year})" if m_year else "") + "\n\n"
                    f"⏱️ <i>Jeda anti-spam 3.5 detik per posting...</i>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

        # JEDA ANTI-SPAM (delay between sending movie files to avoid spam limit)
        if idx < total_count:
            await asyncio.sleep(3.5)

    # Done posting all movies! Now create and pin the catalog ONCE on the new channel
    try:
        await status_msg.edit_text(
            f"📌 <b>Membuat & Menyematkan Pinned Catalog di Channel Baru...</b>\n\n"
            f"📢 <b>Channel:</b> @{clean_target}\n"
            f"🎬 <b>Total Film Terkirim:</b> {success_count}/{total_count}\n\n"
            f"<i>Menata indeks A-Z dan menerbitkan Telegra.ph...</i>",
            parse_mode=ParseMode.HTML
        )
        _engine.cache.set_setting(f"synced_{clean_target.lower()}", "yes")
        unique_pins = await update_pinned_catalog(client, f"@{clean_target}", chat_id=chat_id)
    except Exception as pe:
        logger.warning(f"Error updating pinned catalog after restore: {pe}")
        unique_pins = success_count

    await status_msg.edit_text(
        f"🎉 <b>RESTORE & MIGRASI CHANNEL SELESAI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Channel Baru:</b> @{clean_target}\n"
        f"✅ <b>Berhasil Diposting:</b> {success_count} film\n"
        f"❌ <b>Gagal:</b> {fail_count} film\n"
        f"📌 <b>Pinned Catalog:</b> Aktif ({unique_pins} film A-Z)\n"
        f"⚡ <b>Telegra.ph Instant View:</b> Siap digunakan\n\n"
        f"✨ <i>Channel baru Anda sekarang sudah lengkap berisi semua koleksi film dengan tombol interaktif, pemisah stiker, dan pinned catalog yang rapi!</i>",
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

        # Check Auto-Post setting
        autopost_enabled = _engine.cache.get_setting(f"autopost_{chat_id}", "off") == "on"
        if autopost_enabled:
            if not wm.startswith("@") or len(wm) <= 1:
                await msg.reply_text(
                    "⚠️ <b>Auto-Post aktif tetapi channel watermark belum diatur!</b>\n\n"
                    "Gunakan <code>/setwatermark @namachannel</code> agar bot bisa posting otomatis ke channel Anda.",
                    parse_mode=ParseMode.HTML
                )
            else:
                try:
                    sent_video_fid = sent.video.file_id if (sent and getattr(sent, "video", None)) else media.file_id
                    sent_channel = await publish_video_to_channel(
                        client=client,
                        chat_id=chat_id,
                        video_file_id=sent_video_fid,
                        caption_text=caption,
                        metadata=result.get("metadata", {}),
                        watermark=wm
                    )
                    clean_wm = wm.lstrip("@").strip()
                    title_name = result.get("metadata", {}).get("title") or filename
                    post_link = f"https://t.me/{clean_wm}/{sent_channel.id}" if sent_channel else f"https://t.me/{clean_wm}"
                    await msg.reply_text(
                        f"🚀 <b>Auto-Post: Berhasil Diposting ke Channel!</b>\n\n"
                        f"🎬 <b>Film:</b> {title_name}\n"
                        f"📢 <b>Channel:</b> {wm}\n\n"
                        f"• Tombol interaktif lengkap otomatis dibuat.\n"
                        f"• Pinned Catalog A-Z channel otomatis diperbarui.\n"
                        f"• Stiker pembatas channel otomatis dikirim.\n\n"
                        f"👉 <a href=\"{post_link}\">Lihat Postingan di {wm}</a>",
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except Exception as ape:
                    logger.exception("Auto-post error")
                    await msg.reply_text(
                        f"❌ <b>Gagal Auto-Post ke {wm}:</b>\n\n<code>{ape}</code>\n\n"
                        f"<i>Pastikan bot sudah dijadikan Administrator di channel dengan izin kirim pesan!</i>",
                        parse_mode=ParseMode.HTML
                    )
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
        meta = job.get("metadata", {})
        title_meta = meta.get("title") or "Film Ini"
        video_fid = job["sent_msg"].video.file_id if (job.get("sent_msg") and job["sent_msg"].video) else None
        if not video_fid:
            await call.message.reply_text("❌ Video tidak ditemukan dalam job.")
            return

        sent_channel = await publish_video_to_channel(
            client=client,
            chat_id=chat_id,
            video_file_id=video_fid,
            caption_text=job["caption_text"],
            metadata=meta,
            watermark=wm
        )

        clean_wm = wm.lstrip("@").strip()
        post_link = f"https://t.me/{clean_wm}/{sent_channel.id}" if sent_channel else f"https://t.me/{clean_wm}"

        await call.message.reply_text(
            f"✅ <b>Berhasil Diposting ke {wm}!</b>\n\n"
            f"• Film sudah terbit lengkap dengan tombol [ Gabung ], [ Trailer ], [ Request ], dan [ Bagikan ]\n"
            f"• Film otomatis masuk ke katalog pencarian (<code>/cari {title_meta}</code>)\n"
            f"• Pinned Catalog A-Z di channel otomatis diperbarui!\n"
            f"• Stiker pemisah otomatis terkirim di bawahnya sebagai pembatas!\n\n"
            f"👉 <a href=\"{post_link}\">Buka Postingan di Channel</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
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


@app.on_deleted_messages()
async def auto_sync_deleted_movies(client: Client, messages: List[Message]):
    """Automatically removes deleted movie posts from catalog and updates pinned message in real-time."""
    if not messages:
        return

    deleted_ids = [m.id for m in messages if getattr(m, "id", None)]
    if not deleted_ids:
        return

    try:
        affected_channels = _engine.cache.delete_movie_posts(deleted_ids)
        for channel in affected_channels:
            logger.info(f"Detected deleted movie in @{channel}, auto-updating pinned catalog...")
            await update_pinned_catalog(client, channel)
    except Exception as e:
        logger.error(f"Error handling deleted messages sync: {e}")


@app.on_message(filters.channel & (filters.service | filters.pinned_message))
async def auto_delete_channel_service_messages(client: Client, msg: Message):
    """Automatically delete service notification messages (e.g. 'channel menyematkan...') in channel chat."""
    try:
        await msg.delete()
        logger.info(f"Auto-deleted service notification message {msg.id} in channel {msg.chat.id}")
    except Exception as e:
        logger.debug(f"Could not auto-delete service message {msg.id}: {e}")


async def on_bot_startup(client: Client):
    """Background startup task: automatically hydrates the channel catalog and restores the pinned message."""
    try:
        await asyncio.sleep(3)
        clean_wm = (CHANNEL_WATERMARK or "@film_indonesia1").lstrip("@").strip().lower()
        if clean_wm:
            curr_movies = _engine.cache.get_deduplicated_catalog(clean_wm)
            has_synced = _engine.cache.get_setting(f"synced_{clean_wm}", "no")
            if has_synced != "yes" or len(curr_movies) < 50:
                logger.info(f"Bot startup: Auto-hydrating channel catalog for @{clean_wm}...")
                await auto_hydrate_channel_catalog(client, clean_wm)
                await update_pinned_catalog(client, clean_wm)
                logger.info(f"Bot startup: Catalog for @{clean_wm} successfully restored and pinned!")
    except Exception as e:
        logger.warning(f"Bot startup hydration error: {e}")