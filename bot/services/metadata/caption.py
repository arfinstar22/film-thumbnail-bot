import html
import os
import re
from typing import Dict, Any

class CaptionGenerator:
    def __init__(self, watermark: str = None):
        self.watermark = watermark or os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()

    def generate(self, metadata: Dict[str, Any], custom_watermark: str = None) -> str:
        title = (metadata.get("title") or "Film").strip()
        year = metadata.get("year")
        res = metadata.get("resolution")
        src = metadata.get("source")
        platform = metadata.get("platform")
        vc = metadata.get("videoCodec")
        ac = metadata.get("audioCodec")
        ach = metadata.get("audioChannels")
        rg = metadata.get("releaseGroup")
        season = metadata.get("season")
        episode = metadata.get("episode")
        file_size = metadata.get("fileSize")
        duration = metadata.get("duration")

        wm = (custom_watermark or self.watermark or "").strip()
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

        # Tampilan Header Judul & Tahun (+ Watermark)
        title_escaped = html.escape(title.upper())
        header = f"🎬 <b>{title_escaped}</b>"
        if season is not None and episode is not None:
            header += f" (S{season:02d}E{episode:02d})"
        elif year:
            header += f" ({year})"

        if wm:
            header += f" • <a href=\"{html.escape(channel_url, quote=True)}\"><b>{html.escape(wm)}</b></a>"

        lines = [
            header,
            "━━━━━━━━━━━━━━━━━━",
            "📌 <b>Informasi Film:</b>"
        ]

        if season is not None and episode is not None:
            lines.append(f"📺 <b>Episode :</b> Season {season:02d} • Episode {episode:02d}")

        if year:
            lines.append(f"🗓️ <b>Tahun :</b> {year}")

        rating = metadata.get("rating")
        if rating:
            lines.append(f"⭐ <b>Rating :</b> {html.escape(str(rating))}")

        genre = metadata.get("genre")
        if genre:
            lines.append(f"🎭 <b>Genre :</b> {html.escape(str(genre))}")

        director = metadata.get("director")
        if director:
            lines.append(f"🎬 <b>Sutradara :</b> {html.escape(str(director))}")

        actors = metadata.get("actors")
        if actors:
            lines.append(f"👥 <b>Pemeran :</b> {html.escape(str(actors))}")

        if res:
            res_display = {
                "2160p": "2160p • 4K UHD",
                "1440p": "1440p • 2K QHD",
                "1080p": "1080p • Full HD",
                "720p": "720p • HD",
                "480p": "480p • SD"
            }.get(res, res)
            lines.append(f"🎞️ <b>Kualitas :</b> {html.escape(res_display)}")

        if src:
            src_str = f"{src} ({platform})" if platform else src
            lines.append(f"📡 <b>Source :</b> {html.escape(src_str)}")

        if vc:
            lines.append(f"💿 <b>Video :</b> {html.escape(str(vc))}")

        audio_preset = metadata.get("audio")
        if audio_preset:
            lines.append(f"🔊 <b>Audio :</b> {html.escape(str(audio_preset))}")
        elif ac:
            audio_str = f"{ac} {ach}" if ach else ac
            lines.append(f"🔊 <b>Audio :</b> {html.escape(str(audio_str))}")

        sub = metadata.get("subtitle")
        if sub:
            lines.append(f"💬 <b>Subtitle :</b> {html.escape(str(sub))}")

        if rg:
            lines.append(f"🏷️ <b>Release :</b> {html.escape(str(rg))}")

        if file_size:
            lines.append(f"📦 <b>Ukuran :</b> {html.escape(str(file_size))}")

        if duration:
            lines.append(f"⏱️ <b>Durasi :</b> {html.escape(str(duration))}")

        lines.append("━━━━━━━━━━━━━━━━━━")

        synopsis = (metadata.get("synopsis") or "").strip()
        synopsis_idx = None
        if synopsis:
            lines.append("📖 <b>Sinopsis:</b>")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(synopsis)}</blockquote>")
            lines.append("━━━━━━━━━━━━━━━━━━")

        # Auto Hashtags
        hashtags = []
        if title:
            tag_title = re.sub(r"[^\w]", "", title)
            if tag_title and not tag_title.isdigit():
                hashtags.append(f"#{tag_title}")
        if year:
            hashtags.append(f"#Tahun{year}")
        if res:
            hashtags.append(f"#{res}")
        if src:
            tag_src = re.sub(r"[^\w]", "", src)
            hashtags.append(f"#{tag_src}")
        if clean_wm:
            tag_wm = re.sub(r"[^\w]", "", clean_wm)
            if tag_wm:
                hashtags.append(f"#{tag_wm}")

        hashtag_idx = None
        if hashtags:
            hashtag_idx = len(lines)
            lines.append(f"🔍 <i>{' '.join(hashtags)}</i>")
            lines.append("")

        if wm:
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{html.escape(channel_url, quote=True)}\">{html.escape(wm)}</a>")

        result_text = "\n".join(lines)

        # Telegram strict max 1024 characters check
        if len(result_text) > 980 and synopsis and synopsis_idx is not None:
            excess = len(result_text) - 980
            trimmed_len = max(40, len(synopsis) - excess - 15)
            trimmed = synopsis[:trimmed_len].rstrip() + "..."
            lines[synopsis_idx] = f"<blockquote expandable>{html.escape(trimmed)}</blockquote>"
            result_text = "\n".join(lines)

        # Final guarantee to never exceed 1024 characters
        if len(result_text) > 1020:
            if hashtag_idx is not None and hashtag_idx < len(lines):
                lines.pop(hashtag_idx)
                result_text = "\n".join([line for line in lines if line.strip() != "🔍 <i></i>"])
            if len(result_text) > 1020 and synopsis_idx is not None:
                short_syn = synopsis[:60].rstrip() + "..."
                lines[synopsis_idx] = f"<blockquote expandable>{html.escape(short_syn)}</blockquote>"
                result_text = "\n".join(lines)

        return result_text


