import asyncio
import logging
import os
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
_engine = MetadataEngine()


def get_caption_kb(message_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Cari Info Film", callback_data=f"info:{message_id}")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data=f"edit:{message_id}")]
    ])


@app.on_message(filters.command("start"))
async def start_cmd(client: Client, msg: Message):
    await msg.reply_text(
        "🎬 **Bot Film Pintar**\n\n"
        "Forward film ke sini, bot akan:\n"
        "- Thumbnail otomatis bawaan video\n"
        "- Info film otomatis via Smart Parser + AI\n\n"
        "Kirim video sekarang!"
    )


@app.on_message(filters.video | filters.document)
async def receive_video(client: Client, msg: Message):
    media = msg.video or msg.document
    if not media:
        return

    filename = getattr(media, "file_name", "film.mp4")
    tmp = tempfile.mkdtemp()
    try:
        if msg.video and msg.video.thumbs:
            raw = os.path.join(tmp, "raw_auto")
            await client.download_media(msg.video.thumbs[0].file_id, file_name=raw)
            thumb_path = os.path.join(tmp, "thumb.jpg")
            await photo_thumbnail(raw, thumb_path)
        else:
            thumb_path = os.path.join(tmp, "black.jpg")
            await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240",
                "-frames:v", "1", thumb_path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )

        # Kirim video tanpa caption dulu, nanti diupdate via callback info
        sent = await client.send_video(
            chat_id=msg.chat.id,
            video=media.file_id,
            thumb=thumb_path,
            supports_streaming=True,
            reply_markup=get_caption_kb(msg.id)
        )

        _jobs[msg.chat.id] = {
            "filename": filename,
            "sent_msg": sent,
            "caption_text": "",
            "metadata": {}
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

    await call.answer("🔍 Menganalisis film...")

    try:
        await call.message.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Sedang diproses...", callback_data="loading")]])
        )

        result = await _engine.process(job["filename"])
        caption = result["caption"]
        source = result["source"]
        logger.info("Caption generated via: %s", source)

        # Simpan caption & metadata ke job
        job["caption_text"] = caption
        if "metadata" in result:
            job["metadata"] = result["metadata"]

        await call.message.edit_caption(caption=caption, reply_markup=get_caption_kb(call.message.id))
    except Exception as e:
        logger.exception("Info fetch error")
        await call.message.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Gagal", callback_data="failed")]])
        )
        await client.send_message(chat_id, f"❌ {str(e)[:100]}")


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

    # Set state edit
    _jobs[chat_id]["state"] = "waiting_edit"
    _jobs[chat_id]["edit_timeout"] = time.time() + 300  # 5 menit

    # Kirim caption dalam code block biar gampang copy-edit
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

    # Cek timeout 5 menit
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
        # Update cache
        _jobs[chat_id]["caption_text"] = msg.text
        _jobs[chat_id].pop("state", None)
        _jobs[chat_id].pop("edit_timeout", None)
        await msg.reply_text("✅ Caption diperbarui!")
    except Exception as e:
        logger.exception("Edit caption error")
        await msg.reply_text(f"❌ Gagal: {str(e)[:100]}")


@app.on_callback_query(filters.regex(r"^loading"))
async def handle_loading_callback(client: Client, call: CallbackQuery):
    await call.answer("⏳ Sedang diproses...")