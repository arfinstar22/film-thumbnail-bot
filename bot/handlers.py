import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import MAX_FILE_BYTES
from .services.video import (
    embed_thumbnail,
    extract_frame,
    parse_ts_to_seconds,
    photo_thumbnail,
    probe_video,
    strip_thumbnail,
)
from .states import ThumbStates

router = Router()
logger = logging.getLogger(__name__)

# Simpan jobs sementara (in-memory)
_jobs = {}


def get_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🎬 Frame Otomatis (Tengah)", callback_data="act:auto"))
    b.row(InlineKeyboardButton(text="⏱ Tentukan Menit/Detik", callback_data="act:manual"))
    b.row(InlineKeyboardButton(text="🖼 Pakai Foto Sendiri", callback_data="act:photo"))
    b.row(InlineKeyboardButton(text="🗑 Hapus Thumbnail", callback_data="act:strip"))
    b.row(InlineKeyboardButton(text="❌ Batal", callback_data="act:cancel"))
    return b.as_markup()


@router.message(Command("start"))
async def start_cmd(msg: types.Message):
    await msg.answer("Kirim film/video untuk diedit thumbnail-nya.")


@router.message(F.video | F.document)
async def receive_video(msg: types.Message, state: FSMContext):
    media = msg.video or msg.document
    if media.file_size > MAX_FILE_BYTES:
        await msg.answer("❌ File terlalu besar. Maksimal 2GB.")
        return

    # Cek mime type
    mime = getattr(media, "mime_type", "video/mp4")
    if not mime.startswith("video/"):
        await msg.answer("❌ Itu bukan file video.")
        return

    # Simpan info job
    _jobs[msg.from_user.id] = {
        "file_id": media.file_id,
        "mime": mime,
        "name": getattr(media, "file_name", "video.mp4"),
        "msg_id": msg.message_id,
    }
    
    await state.set_state(ThumbStates.choosing_action)
    await msg.answer("Video diterima! Pilih aksi:", reply_markup=get_menu_kb())


@router.callback_query(F.data.startswith("act:"))
async def handle_action(callback: types.CallbackQuery, state: FSMContext):
    act = callback.data.split(":")[1]
    uid = callback.from_user.id
    
    if act == "cancel":
        _jobs.pop(uid, None)
        await state.clear()
        await callback.message.edit_text("Aksi dibatalkan.")
        return

    if uid not in _jobs:
        await callback.answer("Job hilang, kirim ulang video.")
        return

    if act == "auto":
        await process_video(callback, "auto")
    elif act == "manual":
        await state.set_state(ThumbStates.waiting_timestamp)
        await callback.message.edit_text("Masukkan waktu (contoh: 01:30 atau 90):")
    elif act == "photo":
        await state.set_state(ThumbStates.waiting_photo)
        await callback.message.edit_text("Kirim foto thumbnail:")
    elif act == "strip":
        await process_video(callback, "strip")


@router.message(ThumbStates.waiting_timestamp)
async def get_ts(msg: types.Message, state: FSMContext):
    try:
        ts = await parse_ts_to_seconds(msg.text)
        await state.clear()
        await process_video(msg, "manual", ts=ts)
    except Exception:
        await msg.answer("Format salah. Pakai MM:SS atau HH:MM:SS.")


@router.message(ThumbStates.waiting_photo, F.photo)
async def get_photo(msg: types.Message, state: FSMContext):
    # Simpan photo_id di job
    uid = msg.from_user.id
    _jobs[uid]["photo_id"] = msg.photo[-1].file_id
    await state.clear()
    await process_video(msg, "photo")


async def process_video(src: types.Message | types.CallbackQuery, mode: str, ts: float = 0):
    uid = src.from_user.id
    job = _jobs.get(uid)
    if not job: return
    
    # UI Feedback
    msg = src.message if isinstance(src, types.CallbackQuery) else src
    status_msg = await msg.answer("⏳ Mengunduh...")
    
    # Init Processing
    tmp = tempfile.mkdtemp()
    try:
        # Download
        bot: Bot = src.bot
        file_obj = await bot.get_file(job["file_id"])
        ext = ".mkv" if "matroska" in job["mime"] else ".mp4"
        in_path = os.path.join(tmp, "in" + ext)
        await bot.download(file_obj, destination=in_path)
        
        await status_msg.edit_text("⏳ Memproses...")
        
        out_path = os.path.join(tmp, "out" + ext)
        thumb_path = None
        
        # Action Logic
        if mode == "auto":
            dur, attached = await probe_video(in_path)
            ts = dur / 2 if dur > 0 else 60
            thumb_path = os.path.join(tmp, "thumb.jpg")
            await extract_frame(in_path, ts, thumb_path)
            await embed_thumbnail(in_path, thumb_path, out_path)
        elif mode == "manual":
            thumb_path = os.path.join(tmp, "thumb.jpg")
            await extract_frame(in_path, ts, thumb_path)
            await embed_thumbnail(in_path, thumb_path, out_path)
        elif mode == "photo":
            photo_obj = await bot.get_file(job["photo_id"])
            p_path = os.path.join(tmp, "photo.jpg")
            await bot.download(photo_obj, destination=p_path)
            thumb_path = os.path.join(tmp, "thumb.jpg")
            await photo_thumbnail(p_path, thumb_path)
            await embed_thumbnail(in_path, thumb_path, out_path)
        elif mode == "strip":
            dur, attached = await probe_video(in_path)
            await strip_thumbnail(in_path, attached, out_path)
            thumb_path = None
        
        # Sending Result
        await status_msg.edit_text("📤 Mengunggah...")
        
        final_thumb = FSInputFile(thumb_path) if thumb_path else None
        final_video = FSInputFile(out_path)
        
        if "video" in job["mime"]:
            await msg.answer_video(final_video, thumbnail=final_thumb, caption="Selesai!")
        else:
            await msg.answer_document(final_video, thumbnail=final_thumb, caption="Selesai!")
            
        await status_msg.delete()
        
    except Exception as e:
        logger.exception("Error process")
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _jobs.pop(uid, None)
