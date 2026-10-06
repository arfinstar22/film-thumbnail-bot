import asyncio
import logging
import os
import re
import shutil
import tempfile
import time

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode

from .config import BOT_TOKEN, API_ID, API_HASH
from .services.video import photo_thumbnail
from .services.metadata.engine import MetadataEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("thumb_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

_jobs = {}
_custom_thumbs = {}
_engine = MetadataEngine()


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


def get_caption_kb(message_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Caption", callback_data=f"edit:{message_id}")],
        [InlineKeyboardButton("🔄 Format Ulang", callback_data=f"info:{message_id}")]
    ])


@app.on_message(filters.command("start"))
async def start_cmd(client: Client, msg: Message):
    await msg.reply_text(
        "🎬 **Film AI & Watermark Cleaner Bot**\n\n"
        "✨ **Fitur Utama:**\n"
        "• 🖼️ **Thumbnail Bersih**: Hapus tulisan watermark pada cover video\n"
        "• 🤖 **Smart Parser**: Otomatis kenali Judul, Tahun, Kualitas, Source, Audio & Codec\n"
        "• 🧹 **Filter Homoglif**: Otomatis bersihkan watermark channel aneh (cth: `fαιвεяsgαтє`)\n"
        "• 🏷️ **Watermark Channel**: Otomatis tempel watermark channel di caption\n"
        "• 🎨 **Poster Kustom**: Kirim foto apa saja untuk dijadikan thumbnail video\n\n"
        "👉 **Kirim atau forward video film sekarang!**"
    )


@app.on_message(filters.photo)
async def handle_photo(client: Client, msg: Message):
    chat_id = msg.chat.id
    tmp = tempfile.mkdtemp()
    raw = os.path.join(tmp, "raw_poster.jpg")
    custom_thumb = os.path.join(tmp, "custom_poster.jpg")
    try:
        await client.download_media(msg.photo.file_id, file_name=raw)
        await photo_thumbnail(raw, custom_thumb)
        _custom_thumbs[chat_id] = custom_thumb
        await msg.reply_text(
            "🖼️ **Poster Kustom Tersimpan!**\n\n"
            "Forward video film sekarang, bot akan memakai poster ini sebagai thumbnail tanpa watermark!"
        )
    except Exception as e:
        logger.exception("Save custom poster error")
        await msg.reply_text(f"❌ Gagal simpan poster: {str(e)[:100]}")


@app.on_message(filters.video | filters.document)
async def receive_video(client: Client, msg: Message):
    media = msg.video or msg.document
    if not media:
        return

    chat_id = msg.chat.id
    filename = extract_filename(media, msg)
    file_size_str = format_size(getattr(media, "file_size", 0))
    duration_str = format_duration(getattr(media, "duration", 0))

    extra = {}
    if file_size_str:
        extra["fileSize"] = file_size_str
    if duration_str:
        extra["duration"] = duration_str

    # Parse metadata & buat caption instan tanpa AI
    result = await _engine.process(filename, extra=extra)
    caption = result["caption"]

    tmp = tempfile.mkdtemp()
    thumb_path = None
    try:
        # Cek apakah ada custom poster dari user
        if chat_id in _custom_thumbs and os.path.exists(_custom_thumbs[chat_id]):
            thumb_path = _custom_thumbs.pop(chat_id)
        elif getattr(media, "thumbs", None):
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
            thumb=thumb_path,
            supports_streaming=True,
            reply_markup=get_caption_kb(msg.id)
        )

        _jobs[chat_id] = {
            "filename": filename,
            "sent_msg": sent,
            "caption_text": caption,
            "extra": extra,
            "metadata": result.get("metadata", {})
        }
    except Exception as e:
        logger.exception("Send video error")
        await msg.reply_text(f"❌ Gagal: {str(e)[:100]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.on_callback_query(filters.regex(r"^info:"))
async def handle_info_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)

    if not job:
        await call.answer("Job kadaluarsa.")
        return

    await call.answer("🔄 Memformat ulang...")

    try:
        result = await _engine.process(job["filename"], extra=job.get("extra"))
        caption = result["caption"]
        job["caption_text"] = caption
        await call.message.edit_caption(caption=caption, reply_markup=get_caption_kb(call.message.id))
        await call.answer("✅ Selesai diformat ulang!")
    except Exception as e:
        logger.exception("Info fetch error")
        await call.answer(f"❌ Gagal: {str(e)[:50]}")


@app.on_callback_query(filters.regex(r"^edit:"))
async def handle_edit_callback(client: Client, call: CallbackQuery):
    chat_id = call.message.chat.id
    job = _jobs.get(chat_id)

    if not job:
        await call.answer("Job kadaluarsa.")
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