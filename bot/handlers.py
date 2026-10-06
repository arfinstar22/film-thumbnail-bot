import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode

from .config import BOT_TOKEN, API_ID, API_HASH, CHANNEL_WATERMARK
from .services.video import photo_thumbnail
from .services.metadata.engine import MetadataEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("thumb_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

_jobs = {}
_engine = MetadataEngine()


def _get_user_watermark(chat_id: int) -> str:
    return _engine.cache.get_setting(f"watermark_{chat_id}", CHANNEL_WATERMARK)


def _get_user_divider(chat_id: int) -> str:
    return _engine.cache.get_setting(f"divider_{chat_id}", "default")


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
    wm = _get_user_watermark(msg.chat.id)
    await msg.reply_text(
        "🎬 <b>Film AI & Watermark Cleaner Bot</b>\n\n"
        "✨ <b>Fitur Lengkap:</b>\n"
        "• ⚡ <b>Proses Instan (1 Detik)</b>: Bersihkan watermark lama otomatis\n"
        "• 🎨 <b>Desain Caption Estetik</b>: Format divider premium, font tebal & emotikon rapi\n"
        "• 🏷️ <b>Auto Hashtag</b>: Tag pencarian otomatis (#Judul #Tahun #Kualitas)\n"
        f"• 📢 <b>Tombol Promosi Channel</b>: Tombol link langsung ke channel Anda (<b>{wm}</b>)\n"
        "• 📋 <b>1-Klik Salin Teks</b>: Salin caption instan tinggal tempel ke channel\n"
        "• ⚙️ <b>Ganti Watermark</b>: Ketik <code>/setwatermark @namachannel</code> kapan saja\n"
        "• 🎞️ <b>Stiker Pemisah Otomatis</b>: Ketik <code>/setdivider</code> untuk atur stiker pembatas channel\n\n"
        "👉 <b>Forward film ke sini sekarang!</b>",
        parse_mode=ParseMode.HTML
    )


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

    result = await _engine.process(filename, extra=extra, watermark=wm)
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

        channel_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"📢 Gabung {wm}", url=channel_url),
                InlineKeyboardButton("🔄 Bagikan Film", url=share_url)
            ]
        ])

        await client.send_video(
            chat_id=wm,
            video=job["sent_msg"].video.file_id,
            caption=job["caption_text"],
            parse_mode=ParseMode.HTML,
            supports_streaming=True,
            reply_markup=channel_kb
        )

        # Kirim stiker pemisah otomatis di bawah film
        await _send_channel_divider(client, chat_id, wm)

        await call.message.reply_text(
            f"✅ <b>Berhasil Diposting ke {wm}!</b>\n\n"
            f"• Film sudah terbit lengkap dengan tombol [ Gabung ] & [ Bagikan ]\n"
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
        result = await _engine.process(job["filename"], extra=job.get("extra"), watermark=wm)
        caption = result["caption"]
        job["caption_text"] = caption
        await call.message.edit_caption(
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=get_caption_kb(call.message.id, wm)
        )
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
        await client.edit_message_caption(
            chat_id=chat_id,
            message_id=_jobs[chat_id]["sent_msg"].id,
            caption=msg.text,
            parse_mode=ParseMode.HTML
        )
        _jobs[chat_id]["caption_text"] = msg.text
        _jobs[chat_id].pop("state", None)
        _jobs[chat_id].pop("edit_timeout", None)
        await msg.reply_text("✅ Caption berhasil diperbarui!")
    except Exception as e:
        logger.exception("Edit caption error")
        await msg.reply_text(f"❌ Gagal: {str(e)[:100]}")