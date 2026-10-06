from typing import Dict, Any

class CaptionGenerator:
    @staticmethod
    def generate(metadata: Dict[str, Any]) -> str:
        title = metadata.get("title") or "Film"
        year = metadata.get("year")
        res = metadata.get("resolution")
        src = metadata.get("source")
        vc = metadata.get("videoCodec")
        ac = metadata.get("audioCodec")
        ach = metadata.get("audioChannels")
        rg = metadata.get("releaseGroup")
        season = metadata.get("season")
        episode = metadata.get("episode")

        lines = [f"🎬 **{title}**"]

        if season is not None and episode is not None:
            lines.append(f"📺 **Episode** : S{season:02d}E{episode:02d}")

        if year:
            lines.append(f"📅 **Tahun** : {year}")
        if res:
            lines.append(f"🎞️ **Kualitas** : {res}")
        if src:
            lines.append(f"📡 **Source** : {src}")
        if vc:
            lines.append(f"💿 **Video** : {vc}")
        if ac:
            audio_str = f"{ac} {ach}" if ach else ac
            lines.append(f"🔊 **Audio** : {audio_str}")
        if rg:
            lines.append(f"🏷️ **Release** : {rg}")

        lines.append("")
        lines.append("@film_indonesia1")

        return "\n".join(lines)
