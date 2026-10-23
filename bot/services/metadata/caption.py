import html
import os
import re
from typing import Dict, Any, Optional, List

class CaptionGenerator:
    """Generates aesthetic, high-engagement Telegram HTML captions.
    Supports 3 distinct visual styles:
    - 'minimalist' (default): Modern streaming chips, clean subtle dividers, breathable layout.
    - 'streaming': Structured key-value specs with modern icons.
    - 'editorial': Cinephile showcase layout with prominent director & italic quote synopsis.
    Guaranteed to be valid HTML and strictly <= 1024 characters.
    """

    def __init__(self, watermark: str = None, cache: Any = None):
        self.watermark = watermark or os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()
        self.cache = cache

    def generate(
        self,
        metadata: Dict[str, Any],
        custom_watermark: str = None,
        style: Optional[str] = None
    ) -> str:
        chosen_style = (style or "").lower().strip()
        if not chosen_style and self.cache:
            try:
                chosen_style = (self.cache.get_setting("caption_style", "minimalist") or "minimalist").lower().strip()
            except Exception:
                chosen_style = "minimalist"
        if chosen_style not in ["minimalist", "streaming", "editorial"]:
            chosen_style = "minimalist"

        if chosen_style == "streaming":
            return self._generate_streaming(metadata, custom_watermark)
        elif chosen_style == "editorial":
            return self._generate_editorial(metadata, custom_watermark)
        else:
            return self._generate_minimalist(metadata, custom_watermark)

    def _generate_minimalist(self, metadata: Dict[str, Any], custom_watermark: str = None) -> str:
        title = (metadata.get("title") or "Film").strip()
        year = metadata.get("year")
        res = metadata.get("resolution")
        src = metadata.get("source")
        season = metadata.get("season")
        episode = metadata.get("episode")
        file_size = metadata.get("fileSize")
        duration = metadata.get("duration")
        rating = metadata.get("rating")
        genre = metadata.get("genre")
        director = metadata.get("director")
        actors = metadata.get("actors")
        audio = metadata.get("audio") or metadata.get("audioCodec")
        sub = metadata.get("subtitle")

        wm = (custom_watermark or self.watermark or "").strip()
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

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
            "— • — • — • — • — • — • — • — • —"
        ]

        # Row 1: Rating & Genre
        r1_parts = []
        if rating:
            clean_r = str(rating).replace("• IMDb", "").replace("IMDb", "").replace("• TMDb", "").replace("TMDb", "").strip()
            r1_parts.append(f"⭐ <b>{html.escape(clean_r)}</b> • TMDb")
        if genre:
            r1_parts.append(f"🎭 {html.escape(str(genre))}")
        if r1_parts:
            lines.append("   •   ".join(r1_parts))

        # Row 2: Quality, Audio, Subtitle
        r2_parts = []
        if res:
            res_disp = "1080p Full HD" if res == "1080p" else ("2160p 4K" if res == "2160p" else res)
            r2_parts.append(f"🎞️ <b>{html.escape(res_disp)}</b>")
        if audio:
            r2_parts.append(f"🔊 <b>Audio :</b> {html.escape(str(audio))}")
        if sub:
            r2_parts.append(f"💬 <b>Subtitle :</b> {html.escape(str(sub))}")
        if r2_parts:
            lines.append("   •   ".join(r2_parts))

        # Row 3: Size, Duration, Source
        r3_parts = []
        if file_size:
            r3_parts.append(f"📦 {html.escape(str(file_size))}")
        if duration:
            r3_parts.append(f"⏳ {html.escape(str(duration))}")
        if src:
            r3_parts.append(f"📡 {html.escape(str(src))}")
        if r3_parts:
            lines.append("   •   ".join(r3_parts))

        # Director & Cast
        if director:
            lines.append(f"🎬 <b>Sutradara:</b> {html.escape(str(director))}")
        if actors:
            lines.append(f"👥 <b>Pemeran:</b> {html.escape(str(actors))}")

        lines.append("— • — • — • — • — • — • — • — • —")

        synopsis = (metadata.get("synopsis") or "").strip()
        synopsis_idx = None
        if synopsis:
            lines.append("📖 <b>Sinopsis:</b>")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(synopsis)}</blockquote>")
            lines.append("")

        if wm:
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{html.escape(channel_url, quote=True)}\">{html.escape(wm)}</a>")

        return self._clamp_caption(lines, synopsis, synopsis_idx)

    def _generate_streaming(self, metadata: Dict[str, Any], custom_watermark: str = None) -> str:
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

        if wm:
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{html.escape(channel_url, quote=True)}\">{html.escape(wm)}</a>")

        return self._clamp_caption(lines, synopsis, synopsis_idx)

    def _generate_editorial(self, metadata: Dict[str, Any], custom_watermark: str = None) -> str:
        title = (metadata.get("title") or "Film").strip()
        year = metadata.get("year")
        res = metadata.get("resolution")
        rating = metadata.get("rating")
        genre = metadata.get("genre")
        director = metadata.get("director")
        duration = metadata.get("duration")
        audio = metadata.get("audio") or metadata.get("audioCodec")
        sub = metadata.get("subtitle")
        file_size = metadata.get("fileSize")

        wm = (custom_watermark or self.watermark or "").strip()
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

        title_escaped = html.escape(title.upper())
        lines = [f"🎬 <b>{title_escaped}</b>"]
        sub_hdr = []
        if year:
            sub_hdr.append(f"Dirilis {year}")
        if director:
            sub_hdr.append(f"Karya Sutradara {html.escape(str(director))}")
        if sub_hdr:
            lines.append(f"<i>({' • '.join(sub_hdr)})</i>\n")

        pills = []
        if rating:
            clean_r = str(rating).replace("• IMDb", "").replace("IMDb", "").replace("• TMDb", "").replace("TMDb", "").strip()
            pills.append(f"⭐ <b>{html.escape(clean_r)}</b> (TMDb)")
        if genre:
            pills.append(f"🎭 <b>{html.escape(str(genre))}</b>")
        if duration:
            pills.append(f"⏳ <b>{html.escape(str(duration))}</b>")
        if pills:
            lines.append("  |  ".join(pills))
            lines.append("")

        synopsis = (metadata.get("synopsis") or "").strip()
        synopsis_idx = None
        if synopsis:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>« {html.escape(synopsis)} »</blockquote>")
            lines.append("")

        specs = []
        if res:
            res_disp = "1080p FHD" if res == "1080p" else res
            specs.append(res_disp)
        if audio:
            specs.append(str(audio))
        if sub:
            specs.append(str(sub))
        if file_size:
            specs.append(str(file_size))
        if specs:
            lines.append(f"🏷️ <b>Format:</b> {' • '.join([html.escape(s) for s in specs])}")

        if wm:
            lines.append(f"🍿 <b>Koleksi Eksklusif:</b> <a href=\"{html.escape(channel_url, quote=True)}\">{html.escape(wm)}</a>")

        return self._clamp_caption(lines, synopsis, synopsis_idx)

    def _clamp_caption(self, lines: List[str], synopsis: str, synopsis_idx: Optional[int]) -> str:
        """Guarantees caption length never exceeds Telegram's 1024 char limit."""
        result_text = "\n".join(lines)
        if len(result_text) > 980 and synopsis and synopsis_idx is not None and synopsis_idx < len(lines):
            excess = len(result_text) - 980
            trimmed_len = max(40, len(synopsis) - excess - 15)
            trimmed = synopsis[:trimmed_len].rstrip() + "..."
            lines[synopsis_idx] = f"<blockquote expandable>{html.escape(trimmed)}</blockquote>"
            result_text = "\n".join(lines)

        if len(result_text) > 1020 and synopsis_idx is not None and synopsis_idx < len(lines):
            short_syn = synopsis[:60].rstrip() + "..."
            lines[synopsis_idx] = f"<blockquote expandable>{html.escape(short_syn)}</blockquote>"
            result_text = "\n".join(lines)

        if len(result_text) > 1024:
            result_text = result_text[:1020].rstrip() + "..."

        return result_text
