import asyncio
import json
import shutil
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class FfmpegError(RuntimeError):
    pass


async def _run(cmd):
    """Run ffmpeg/ffprobe and raise FfmpegError on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfmpegError(
            f"FFmpeg gagal ({proc.returncode}): {stderr.decode(errors='replace')[-800:]}"
        )
    return stdout.decode(errors="replace")


def _parse_duration(stdout):
    try:
        data = json.loads(stdout)
        return float(data.get("format", {}).get("duration", "0"))
    except Exception:
        return 0.0


def _find_attached_pic(streams):
    """Cari index stream yang attached_pic."""
    for i, s in enumerate(streams or []):
        dis = s.get("disposition", {}) or {}
        if dis.get("attached_pic"):
            return i
    return None


async def probe_video(video_path: str):
    """Ambil duration (detik) dan index attached_pic dari video."""
    out = await _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=index,disposition_attached_pic",
            "-show_format",
            video_path,
        ]
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    attached_idx = _find_attached_pic(streams)
    duration = _parse_duration(out)
    return duration, attached_idx


async def extract_frame(video_path: str, timestamp: float | str, jpg_path: str):
    """Ekstrak frame dari video pada timestamp tertentu menjadi JPG (320px max)."""
    ts = timestamp if isinstance(timestamp, str) else str(int(timestamp))
    await _run(
        [
            FFMPEG,
            "-y",
            "-ss",
            ts,
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-vf",
            "scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease",
            "-q:v",
            "2",
            jpg_path,
        ]
    )


async def photo_thumbnail(src: str, jpg_path: str):
    """Upscale/optimize photo sebagai thumbnail (320px max)."""
    await _run(
        [
            FFMPEG,
            "-y",
            "-i",
            src,
            "-vf",
            "scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease",
            "-q:v",
            "2",
            jpg_path,
        ]
    )


async def embed_thumbnail(video_path: str, thumb_path: str, output_path: str):
    """Embed thumbnail ke video via copy codec (tidak re-encode/video lossless).
    Skip subtitle streams yang tidak didukung di MP4."""
    await _run(
        [
            FFMPEG,
            "-y",
            "-i",
            video_path,
            "-i",
            thumb_path,
            # Map hanya video, audio, dan thumbnail baru
            "-map", "0:v:0",  # video pertama
            "-map", "0:a?",   # semua audio (jika ada)
            "-map", "1:v:0",  # thumbnail sebagai attached pic
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            "-metadata:s:v:1", "comment=Cover (front)",
            output_path,
        ]
    )


async def strip_thumbnail(video_path: str, attached_idx: int | None, output_path: str):
    """Hapus attached_pic dari video (mkv cover) atau asalkan file tanpa cover.
    Skip subtitle streams yang tidak didukung di MP4."""
    if attached_idx is None:
        # Copy dengan map selective untuk skip subtitle
        await _run(
            [
                FFMPEG,
                "-y",
                "-i", video_path,
                "-map", "0:v:0",  # video
                "-map", "0:a?",   # audio
                "-c", "copy",
                output_path,
            ]
        )
        return
    await _run(
        [
            FFMPEG,
            "-y",
            "-i", video_path,
            "-map", "0:v:0",  # video (skip attached pic)
            "-map", "0:a?",   # audio
            "-c", "copy",
            output_path,
        ]
    )


async def parse_ts_to_seconds(t: str) -> float:
    """Parse timestamp 'HH:MM:SS' or 'MM:SS' or angka detik."""
    t = t.strip()
    t = t.replace(",", ".")
    if t.isdigit():
        return float(t)
    parts = t.split(":")
    try:
        p = [float(x) for x in parts]
    except ValueError:
        raise ValueError(f"Format timestamp tidak valid: {t}")
    if len(parts) == 3:
        return p[0] * 3600 + p[1] * 60 + p[2]
    if len(parts) == 2:
        return p[0] * 60 + p[1]
    if len(parts) == 1:
        return p[0]
    raise ValueError(f"Format timestamp tidak valid: {t}")