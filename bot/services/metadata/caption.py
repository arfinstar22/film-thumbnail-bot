import os
import re
from typing import Dict, Any

class CaptionGenerator:
    def __init__(self, watermark: str = None):
        self.watermark = watermark or os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()

    def generate(self, metadata: Dict[str, Any]) -> str:
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

        lines = [f"🎬 **{title}**"]

        if season is not None and episode is not None:
            lines.append(f"📺 **Episode** : S{season:02d}E{episode:02d}")

        if year:
            lines.append(f"📅 **Tahun** : {year}")
        if res:
            lines.append(f"🎞️ **Kualitas** : {res}")
        if src:
            src_str = f"{src} ({platform})" if platform else src
            lines.append(f"📡 **Source** : {src_str}")
        if vc:
            lines.append(f"💿 **Video** : {vc}")
        if ac:
            audio_str = f"{ac} {ach}" if ach else ac
            lines.append(f"🔊 **Audio** : {audio_str}")
        if rg:
            lines.append(f"🏷️ **Release** : {rg}")
        if file_size:
            lines.append(f"📦 **Ukuran** : {file_size}")
        if duration:
            lines.append(f"⏱️ **Durasi** : {duration}")

        # Auto Hashtags untuk pencarian mudah di channel
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
            lines.append("")
            lines.append(" ".join(hashtags))

        if self.watermark:
            lines.append("")
            lines.append(self.watermark)

        return "\n".join(lines)
