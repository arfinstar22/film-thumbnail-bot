import os
import re
from typing import Dict, Any

class CaptionGenerator:
    def __init__(self, watermark: str = None):
        self.watermark = watermark or os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()

    def generate(self, metadata: Dict[str, Any], custom_watermark: str = None) -> str:
        title = metadata.get("title") or "Film"
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

        # Tampilan Header Judul & Tahun
        title_upper = title.upper()
        header = f"🎬 <b>{title_upper}</b>"
        if season is not None and episode is not None:
            header += f" (S{season:02d}E{episode:02d})"
        elif year:
            header += f" ({year})"

        lines = [
            header,
            "━━━━━━━━━━━━━━━━━━",
            "📌 <b>Informasi Film:</b>"
        ]

        if season is not None and episode is not None:
            lines.append(f"📺 <b>Episode :</b> Season {season:02d} • Episode {episode:02d}")

        if year:
            lines.append(f"🗓️ <b>Tahun :</b> {year}")

        if res:
            res_display = {
                "2160p": "2160p • 4K UHD",
                "1440p": "1440p • 2K QHD",
                "1080p": "1080p • Full HD",
                "720p": "720p • HD",
                "480p": "480p • SD"
            }.get(res, res)
            lines.append(f"🎞️ <b>Kualitas :</b> {res_display}")

        if src:
            src_str = f"{src} ({platform})" if platform else src
            lines.append(f"📡 <b>Source :</b> {src_str}")

        if vc:
            lines.append(f"💿 <b>Video :</b> {vc}")

        if ac:
            audio_str = f"{ac} {ach}" if ach else ac
            lines.append(f"🔊 <b>Audio :</b> {audio_str}")

        if rg:
            lines.append(f"🏷️ <b>Release :</b> {rg}")

        if file_size:
            lines.append(f"📦 <b>Ukuran :</b> {file_size}")

        if duration:
            lines.append(f"⏱️ <b>Durasi :</b> {duration}")

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

        if hashtags:
            lines.append(f"🔍 <i>{' '.join(hashtags)}</i>")
            lines.append("")

        wm = custom_watermark or self.watermark
        if wm:
            clean_wm = wm.lstrip("@").strip()
            channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{channel_url}\">{wm}</a>")
            lines.append("")
            lines.append(f"👉 <b><a href=\"{channel_url}\">[ KLIK UNTUK GABUNG CHANNEL ]</a></b>")


        return "\n".join(lines)

