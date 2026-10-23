import html
import os
import re
from typing import Dict, Any, Optional, List

class CaptionGenerator:
    """Generates aesthetic, high-engagement Telegram HTML captions.
    Supports 7 distinct visual styles:
    - 'compact': Super sleek, modern one-glance layout with zero clutter.
    - 'minimalist' (default): Modern streaming chips, clean subtle dividers.
    - 'cinema_vip': Luxury premiere ticket aesthetic with elegant dividers.
    - 'monochrome': Swiss typography / Apple TV pure editorial feel without emoji salad.
    - 'sinema_retro': Classic Indonesian cinema archive cards with clean pointers.
    - 'streaming': Structured key-value specs with modern icons.
    - 'editorial': Cinephile showcase layout with prominent director & italic quote synopsis.
    Guaranteed to be valid HTML and strictly <= 1024 characters.
    """

    SUPPORTED_STYLES = [
        "article",
        "compact",
        "minimalist",
        "cinema_vip",
        "monochrome",
        "sinema_retro",
        "streaming",
        "editorial"
    ]

    def __init__(self, watermark: str = None, cache: Any = None):
        self.watermark = watermark or os.getenv("CHANNEL_WATERMARK", "@film_indonesia1").strip()
        self.cache = cache

    @staticmethod
    def _extract_fields(metadata: Dict[str, Any], custom_watermark: Optional[str], fallback_wm: str) -> Dict[str, Any]:
        title = (metadata.get("title") or "Film").strip()
        year = metadata.get("year")
        res = metadata.get("resolution")
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
        src = metadata.get("source")
        platform = metadata.get("platform")
        vc = metadata.get("videoCodec")
        ac = metadata.get("audioCodec")
        ach = metadata.get("audioChannels")
        rg = metadata.get("releaseGroup")
        synopsis = (metadata.get("synopsis") or "").strip()
        poster_url = metadata.get("poster_url") or metadata.get("poster_path")

        clean_rating = ""
        if rating:
            clean_rating = str(rating).replace("• IMDb", "").replace("IMDb", "").replace("• TMDb", "").replace("TMDb", "").strip()

        res_disp = res or ""
        if res == "1080p":
            res_disp = "1080p Full HD"
        elif res == "2160p":
            res_disp = "2160p 4K UHD"
        elif res == "1440p":
            res_disp = "1440p 2K QHD"
        elif res == "720p":
            res_disp = "720p HD"
        elif res == "480p":
            res_disp = "480p SD"

        wm = (custom_watermark or fallback_wm or "").strip()
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

        return {
            "title": title,
            "year": year,
            "res": res,
            "res_disp": res_disp,
            "season": season,
            "episode": episode,
            "file_size": file_size,
            "duration": duration,
            "rating": rating,
            "clean_rating": clean_rating,
            "genre": genre,
            "director": director,
            "actors": actors,
            "audio": audio,
            "sub": sub,
            "src": src,
            "platform": platform,
            "vc": vc,
            "ac": ac,
            "ach": ach,
            "rg": rg,
            "synopsis": synopsis,
            "poster_url": poster_url,
            "wm": wm,
            "clean_wm": clean_wm,
            "channel_url": channel_url
        }

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

        if chosen_style not in self.SUPPORTED_STYLES:
            chosen_style = "minimalist"

        f = self._extract_fields(metadata, custom_watermark, self.watermark)

        if chosen_style == "article":
            return self._generate_article(f)
        elif chosen_style == "compact":
            return self._generate_compact(f)
        elif chosen_style == "cinema_vip":
            return self._generate_cinema_vip(f)
        elif chosen_style == "monochrome":
            return self._generate_monochrome(f)
        elif chosen_style == "sinema_retro":
            return self._generate_sinema_retro(f)
        elif chosen_style == "streaming":
            return self._generate_streaming(f)
        elif chosen_style == "editorial":
            return self._generate_editorial(f)
        else:
            return self._generate_minimalist(f)

    # ---------------- 0. ARTICLE (INTERACTIVE COLLAPSIBLE CARDS) ----------------
    def _generate_article(self, f: Dict[str, Any]) -> str:
        """Article post format:
        - Header: Title & year
        - Badges: Rating, Genre, Quality
        - Teaser: 1-line hook
        - Fold 1 (<blockquote expandable>): Poster film resmi & HD link
        - Fold 2 (<blockquote expandable>): Sinopsis lengkap
        - Fold 3 (<blockquote expandable>): Detail spesifikasi teknis & pemain
        """
        title_escaped = html.escape(f["title"].upper())
        header = f"🎬 <b>{title_escaped}</b>"
        if f["season"] is not None and f["episode"] is not None:
            header += f" (S{f['season']:02d}E{f['episode']:02d})"
        elif f["year"]:
            header += f" ({f['year']})"

        lines = [header]

        # Badges row: Rating, Genre, Resolution
        badges = []
        if f["clean_rating"]:
            badges.append(f"⭐ <b>{html.escape(f['clean_rating'])}/10</b>")
        if f["genre"]:
            badges.append(f"🎭 <i>{html.escape(str(f['genre']))}</i>")
        if f["res_disp"]:
            res_disp = "1080p FHD" if f["res"] == "1080p" else f["res_disp"]
            badges.append(f"🎞️ <code>{html.escape(res_disp)}</code>")
        if badges:
            lines.append(" • ".join(badges))

        # Short teaser/hook if synopsis exists
        synopsis = (f.get("synopsis") or "").strip()
        if synopsis:
            first_sentence = synopsis.split(".")[0].strip()
            if 15 <= len(first_sentence) <= 90:
                lines.append(f"<i>{html.escape(first_sentence)}..</i>")

        lines.append("")

        # 1. Expandable Block: Poster Resmi Film & Banner HD
        poster_url = f.get("poster_url") or ""
        lines.append("<blockquote expandable>")
        lines.append("🖼️ <b>POSTER RESMI & BANNER HD</b>")
        if poster_url and (poster_url.startswith("http://") or poster_url.startswith("https://")):
            lines.append(f"👉 <a href=\"{html.escape(poster_url, quote=True)}\">Ketuk untuk Buka Gambar Resolusi Penuh HD ↗</a>")
        else:
            lines.append(f"👉 <a href=\"{html.escape(f['channel_url'], quote=True)}\">Buka Galeri Poster Resmi di Channel ↗</a>")
        lines.append("</blockquote>")
        lines.append("")

        # 2. Expandable Block: Sinopsis Lengkap
        synopsis_idx = None
        if synopsis:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>\n📖 <b>SINOPSIS LENGKAP:</b>\n{html.escape(synopsis)}\n</blockquote>")
            lines.append("")

        # 3. Expandable Block: Detail Spesifikasi & Pemain
        spec_lines = [
            "<blockquote expandable>",
            "ℹ️ <b>DETAIL SPESIFIKASI & PEMAIN:</b>"
        ]
        if f["duration"]:
            spec_lines.append(f"• ⏳ <b>Durasi:</b> {html.escape(str(f['duration']))}")
        if f["res_disp"]:
            size_part = f" ({html.escape(str(f['file_size']))})" if f["file_size"] else ""
            spec_lines.append(f"• 🎞️ <b>Kualitas:</b> {html.escape(f['res_disp'])}{size_part}")
        elif f["file_size"]:
            spec_lines.append(f"• 📦 <b>Ukuran:</b> {html.escape(str(f['file_size']))}")
        if f["actors"]:
            spec_lines.append(f"• 👥 <b>Pemain:</b> {html.escape(str(f['actors']))}")
        if f["director"]:
            spec_lines.append(f"• 🎬 <b>Sutradara:</b> {html.escape(str(f['director']))}")
        if f["audio"]:
            spec_lines.append(f"• 🔊 <b>Audio:</b> {html.escape(str(f['audio']))}")
        if f["sub"]:
            spec_lines.append(f"• 💬 <b>Subtitle:</b> {html.escape(str(f['sub']))}")
        if f["wm"]:
            spec_lines.append(f"• 🍿 <b>Channel:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")
        spec_lines.append("</blockquote>")

        lines.extend(spec_lines)

        return self._clamp_caption(lines, synopsis, synopsis_idx)

    # ---------------- 1. COMPACT (ONE-GLANCE) ----------------
    def _generate_compact(self, f: Dict[str, Any]) -> str:
        """Ultra-clean one-glance card. Zero clutter, highest readability."""
        title_escaped = html.escape(f["title"].upper())
        header = f"🎬 <b>{title_escaped}</b>"
        if f["season"] is not None and f["episode"] is not None:
            header += f" (S{f['season']:02d}E{f['episode']:02d})"
        elif f["year"]:
            header += f" ({f['year']})"

        lines = [header]

        # Row 1: Rating, Genre, Duration
        r1 = []
        if f["clean_rating"]:
            r1.append(f"⭐ <b>{html.escape(f['clean_rating'])}</b>")
        if f["genre"]:
            r1.append(f"🎭 {html.escape(str(f['genre']))}")
        if f["duration"]:
            r1.append(f"⏳ {html.escape(str(f['duration']))}")
        if r1:
            lines.append("  •  ".join(r1))

        # Row 2: Resolution, Audio, Subtitle
        r2 = []
        if f["res_disp"]:
            lines_res = "1080p FHD" if f["res"] == "1080p" else f["res_disp"]
            r2.append(f"🎞️ <b>{html.escape(lines_res)}</b>")
        if f["audio"]:
            r2.append(f"🔊 {html.escape(str(f['audio']))}")
        if f["sub"]:
            r2.append(f"💬 {html.escape(str(f['sub']))}")
        if r2:
            lines.append("  •  ".join(r2))

        lines.append("")

        synopsis_idx = None
        if f["synopsis"]:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("")

        if f["wm"]:
            lines.append(f"🍿 <b>Nonton di</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\"><b>{html.escape(f['wm'])}</b></a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 2. CINEMA VIP PREMIERE ----------------
    def _generate_cinema_vip(self, f: Dict[str, Any]) -> str:
        """Luxury premiere ticket aesthetic with structured highlights."""
        title_escaped = html.escape(f["title"].upper())
        year_str = f" ({f['year']})" if f["year"] else ""
        if f["season"] is not None and f["episode"] is not None:
            year_str = f" (S{f['season']:02d}E{f['episode']:02d})"

        lines = [
            "🎟️ <b>PREMIERE EXCLUSIVE</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🎬 <b>{title_escaped}</b>{year_str}"
        ]

        hl = []
        if f["clean_rating"]:
            hl.append(f"⭐ <b>{html.escape(f['clean_rating'])}</b> TMDb")
        if f["genre"]:
            hl.append(f"🎭 {html.escape(str(f['genre']))}")
        if f["duration"]:
            hl.append(f"⏳ {html.escape(str(f['duration']))}")
        if hl:
            lines.append("  |  ".join(hl))

        lines.append("\n⚜️ <b>SPESIFIKASI TAYANG:</b>")
        if f["res_disp"]:
            lines.append(f"• Kualitas  : {html.escape(f['res_disp'])}")
        if f["audio"]:
            lines.append(f"• Audio     : {html.escape(str(f['audio']))}")
        if f["sub"]:
            lines.append(f"• Subtitle  : {html.escape(str(f['sub']))}")
        if f["director"]:
            lines.append(f"• Sutradara : {html.escape(str(f['director']))}")
        if f["file_size"]:
            lines.append(f"• Ukuran    : {html.escape(str(f['file_size']))}")

        lines.append("")
        synopsis_idx = None
        if f["synopsis"]:
            lines.append("📖 <b>SINOPSIS:</b>")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("")

        if f["wm"]:
            lines.append(f"👑 <b>Koleksi Resmi:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\"><b>{html.escape(f['wm'])}</b></a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 3. MONOCHROME / SWISS APPLE TV ----------------
    def _generate_monochrome(self, f: Dict[str, Any]) -> str:
        """Pure typographical layout inspired by Apple TV & MUBI. Zero emoji clutter."""
        title_escaped = html.escape(f["title"].upper())
        lines = [f"<b>{title_escaped}</b>"]

        sub_info = []
        if f["year"]:
            sub_info.append(str(f["year"]))
        if f["duration"]:
            sub_info.append(str(f["duration"]))
        if f["genre"]:
            sub_info.append(str(f["genre"]))
        if sub_info:
            lines.append("  •  ".join([html.escape(s) for s in sub_info]))

        lines.append("")

        spec_parts = []
        if f["clean_rating"]:
            spec_parts.append(f"★ <b>{html.escape(f['clean_rating'])}</b> TMDb")
        if f["res_disp"]:
            res_short = "1080p FHD" if f["res"] == "1080p" else f["res_disp"]
            spec_parts.append(html.escape(res_short))
        if f["audio"]:
            spec_parts.append(html.escape(str(f["audio"])))
        if f["sub"]:
            spec_parts.append(html.escape(str(f["sub"])))
        if spec_parts:
            lines.append("  |  ".join(spec_parts))
            lines.append("")

        synopsis_idx = None
        if f["synopsis"]:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("")

        if f["wm"]:
            lines.append(f"<b>Koleksi:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 4. SINEMA RETRO KLASIK ----------------
    def _generate_sinema_retro(self, f: Dict[str, Any]) -> str:
        """Indonesian cinema classic archive cards."""
        title_escaped = html.escape(f["title"].upper())
        year_str = f" ({f['year']})" if f["year"] else ""
        if f["season"] is not None and f["episode"] is not None:
            year_str = f" (S{f['season']:02d}E{f['episode']:02d})"

        lines = [
            "📽️ <b>SINEMA INDONESIA</b>",
            f"✦ <b>{title_escaped}</b>{year_str} ✦\n"
        ]

        if f["genre"]:
            lines.append(f"▸ Genre     : {html.escape(str(f['genre']))}")
        if f["clean_rating"]:
            lines.append(f"▸ Rating    : ⭐ <b>{html.escape(f['clean_rating'])}</b> / 10")
        if f["duration"]:
            lines.append(f"▸ Durasi    : {html.escape(str(f['duration']))}")

        fmt_list = []
        if f["res_disp"]:
            fmt_list.append("1080p" if f["res"] == "1080p" else f["res_disp"])
        if f["audio"]:
            fmt_list.append(str(f["audio"]))
        if f["sub"]:
            fmt_list.append(str(f["sub"]))
        if fmt_list:
            lines.append(f"▸ Format    : {' • '.join([html.escape(x) for x in fmt_list])}")

        if f["director"]:
            lines.append(f"▸ Sutradara : {html.escape(str(f['director']))}")

        lines.append("")
        synopsis_idx = None
        if f["synopsis"]:
            lines.append("❝ <i>Sinopsis Film</i> ❞")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("")

        if f["wm"]:
            lines.append(f"Arsip Resmi ▹ <a href=\"{html.escape(f['channel_url'], quote=True)}\"><b>{html.escape(f['wm'])}</b></a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 5. MINIMALIST (CHIPS) ----------------
    def _generate_minimalist(self, f: Dict[str, Any]) -> str:
        title_escaped = html.escape(f["title"].upper())
        header = f"🎬 <b>{title_escaped}</b>"
        if f["season"] is not None and f["episode"] is not None:
            header += f" (S{f['season']:02d}E{f['episode']:02d})"
        elif f["year"]:
            header += f" ({f['year']})"

        if f["wm"]:
            header += f" • <a href=\"{html.escape(f['channel_url'], quote=True)}\"><b>{html.escape(f['wm'])}</b></a>"

        lines = [
            header,
            "— • — • — • — • — • — • — • — • —"
        ]

        # Row 1: Rating & Genre
        r1_parts = []
        if f["clean_rating"]:
            r1_parts.append(f"⭐ <b>{html.escape(f['clean_rating'])}</b> • TMDb")
        if f["genre"]:
            r1_parts.append(f"🎭 {html.escape(str(f['genre']))}")
        if r1_parts:
            lines.append("   •   ".join(r1_parts))

        # Row 2: Quality, Audio, Subtitle
        r2_parts = []
        if f["res_disp"]:
            r2_parts.append(f"🎞️ <b>{html.escape(f['res_disp'])}</b>")
        if f["audio"]:
            r2_parts.append(f"🔊 <b>Audio :</b> {html.escape(str(f['audio']))}")
        if f["sub"]:
            r2_parts.append(f"💬 <b>Subtitle :</b> {html.escape(str(f['sub']))}")
        if r2_parts:
            lines.append("   •   ".join(r2_parts))

        # Row 3: Size, Duration, Source
        r3_parts = []
        if f["file_size"]:
            r3_parts.append(f"📦 {html.escape(str(f['file_size']))}")
        if f["duration"]:
            r3_parts.append(f"⏳ {html.escape(str(f['duration']))}")
        if f["src"]:
            r3_parts.append(f"📡 {html.escape(str(f['src']))}")
        if r3_parts:
            lines.append("   •   ".join(r3_parts))

        # Director & Cast
        if f["director"]:
            lines.append(f"🎬 <b>Sutradara:</b> {html.escape(str(f['director']))}")
        if f["actors"]:
            lines.append(f"👥 <b>Pemeran:</b> {html.escape(str(f['actors']))}")

        lines.append("— • — • — • — • — • — • — • — • —")

        synopsis_idx = None
        if f["synopsis"]:
            lines.append("📖 <b>Sinopsis:</b>")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("")

        if f["wm"]:
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 6. STREAMING (NETFLIX) ----------------
    def _generate_streaming(self, f: Dict[str, Any]) -> str:
        title_escaped = html.escape(f["title"].upper())
        header = f"🎬 <b>{title_escaped}</b>"
        if f["season"] is not None and f["episode"] is not None:
            header += f" (S{f['season']:02d}E{f['episode']:02d})"
        elif f["year"]:
            header += f" ({f['year']})"

        if f["wm"]:
            header += f" • <a href=\"{html.escape(f['channel_url'], quote=True)}\"><b>{html.escape(f['wm'])}</b></a>"

        lines = [
            header,
            "━━━━━━━━━━━━━━━━━━",
            "📌 <b>Informasi Film:</b>"
        ]

        if f["season"] is not None and f["episode"] is not None:
            lines.append(f"📺 <b>Episode :</b> Season {f['season']:02d} • Episode {f['episode']:02d}")

        if f["year"]:
            lines.append(f"🗓️ <b>Tahun :</b> {f['year']}")

        if f["rating"]:
            lines.append(f"⭐ <b>Rating :</b> {html.escape(str(f['rating']))}")

        if f["genre"]:
            lines.append(f"🎭 <b>Genre :</b> {html.escape(str(f['genre']))}")

        if f["director"]:
            lines.append(f"🎬 <b>Sutradara :</b> {html.escape(str(f['director']))}")

        if f["actors"]:
            lines.append(f"👥 <b>Pemeran :</b> {html.escape(str(f['actors']))}")

        if f["res_disp"]:
            lines.append(f"🎞️ <b>Kualitas :</b> {html.escape(f['res_disp'])}")

        if f["src"]:
            src_str = f"{f['src']} ({f['platform']})" if f["platform"] else f["src"]
            lines.append(f"📡 <b>Source :</b> {html.escape(src_str)}")

        if f["vc"]:
            lines.append(f"💿 <b>Video :</b> {html.escape(str(f['vc']))}")

        if f["audio"]:
            lines.append(f"🔊 <b>Audio :</b> {html.escape(str(f['audio']))}")
        elif f["ac"]:
            audio_str = f"{f['ac']} {f['ach']}" if f["ach"] else f["ac"]
            lines.append(f"🔊 <b>Audio :</b> {html.escape(str(audio_str))}")

        if f["sub"]:
            lines.append(f"💬 <b>Subtitle :</b> {html.escape(str(f['sub']))}")

        if f["rg"]:
            lines.append(f"🏷️ <b>Release :</b> {html.escape(str(f['rg']))}")

        if f["file_size"]:
            lines.append(f"📦 <b>Ukuran :</b> {html.escape(str(f['file_size']))}")

        if f["duration"]:
            lines.append(f"⏱️ <b>Durasi :</b> {html.escape(str(f['duration']))}")

        lines.append("━━━━━━━━━━━━━━━━━━")

        synopsis_idx = None
        if f["synopsis"]:
            lines.append("📖 <b>Sinopsis:</b>")
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>{html.escape(f['synopsis'])}</blockquote>")
            lines.append("━━━━━━━━━━━━━━━━━━")

        if f["wm"]:
            lines.append(f"🍿 <b>Channel Resmi:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    # ---------------- 7. EDITORIAL (CINEPHILE) ----------------
    def _generate_editorial(self, f: Dict[str, Any]) -> str:
        title_escaped = html.escape(f["title"].upper())
        lines = [f"🎬 <b>{title_escaped}</b>"]
        sub_hdr = []
        if f["year"]:
            sub_hdr.append(f"Dirilis {f['year']}")
        if f["director"]:
            sub_hdr.append(f"Karya Sutradara {html.escape(str(f['director']))}")
        if sub_hdr:
            lines.append(f"<i>({' • '.join(sub_hdr)})</i>\n")

        pills = []
        if f["clean_rating"]:
            pills.append(f"⭐ <b>{html.escape(f['clean_rating'])}</b> (TMDb)")
        if f["genre"]:
            pills.append(f"🎭 <b>{html.escape(str(f['genre']))}</b>")
        if f["duration"]:
            pills.append(f"⏳ <b>{html.escape(str(f['duration']))}</b>")
        if pills:
            lines.append("  |  ".join(pills))
            lines.append("")

        synopsis_idx = None
        if f["synopsis"]:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>« {html.escape(f['synopsis'])} »</blockquote>")
            lines.append("")

        specs = []
        if f["res_disp"]:
            res_disp = "1080p FHD" if f["res"] == "1080p" else f["res_disp"]
            specs.append(res_disp)
        if f["audio"]:
            specs.append(str(f["audio"]))
        if f["sub"]:
            specs.append(str(f["sub"]))
        if f["file_size"]:
            specs.append(str(f["file_size"]))
        if specs:
            lines.append(f"🏷️ <b>Format:</b> {' • '.join([html.escape(s) for s in specs])}")

        if f["wm"]:
            lines.append(f"🍿 <b>Koleksi Eksklusif:</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")

        return self._clamp_caption(lines, f["synopsis"], synopsis_idx)

    def _clamp_caption(self, lines: List[str], synopsis: str, synopsis_idx: Optional[int]) -> str:
        """Guarantees caption length never exceeds Telegram's 1024 char limit."""
        result_text = "\n".join(lines)
        if len(result_text) > 980 and synopsis and synopsis_idx is not None and synopsis_idx < len(lines):
            excess = len(result_text) - 980
            trimmed_len = max(40, len(synopsis) - excess - 15)
            trimmed = synopsis[:trimmed_len].rstrip() + "..."
            orig_block = lines[synopsis_idx]
            if "SINOPSIS LENGKAP:" in orig_block:
                lines[synopsis_idx] = f"<blockquote expandable>\n📖 <b>SINOPSIS LENGKAP:</b>\n{html.escape(trimmed)}\n</blockquote>"
            else:
                lines[synopsis_idx] = f"<blockquote expandable>{html.escape(trimmed)}</blockquote>"
            result_text = "\n".join(lines)

        if len(result_text) > 1020 and synopsis_idx is not None and synopsis_idx < len(lines):
            short_syn = synopsis[:60].rstrip() + "..."
            orig_block = lines[synopsis_idx]
            if "SINOPSIS LENGKAP:" in orig_block:
                lines[synopsis_idx] = f"<blockquote expandable>\n📖 <b>SINOPSIS LENGKAP:</b>\n{html.escape(short_syn)}\n</blockquote>"
            else:
                lines[synopsis_idx] = f"<blockquote expandable>{html.escape(short_syn)}</blockquote>"
            result_text = "\n".join(lines)

        if len(result_text) > 1024:
            result_text = result_text[:1020].rstrip() + "..."

        return result_text
