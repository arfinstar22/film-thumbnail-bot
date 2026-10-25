"""Aesthetic Telegram HTML Article Caption Generator.

Renders modern unified article post format:
- Header: Film title & year
- Badges: Rating, Genre, Quality
- Teaser: 1-line hook
- Native expandable blocks for Poster HD, Sinopsis Lengkap, and Detail Spesifikasi & Pemain.
Guaranteed to be valid HTML and strictly <= 1024 characters.
"""

import html
import os
import re
from typing import Any, Dict, List, Optional

from .hashtags import generate_smart_hashtags


class CaptionGenerator:
    """Generates clean Telegram HTML article post captions."""

    SUPPORTED_STYLES = ["article"]

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
            m = re.search(r"(\d+(?:\.\d+)?)", str(rating))
            if m:
                clean_rating = f"{m.group(1)}/10"
            elif str(rating).strip().lower() not in ("none", "n/a", "-", "", "0", "0.0"):
                clean_rating = str(rating).strip()

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

        tagline = (metadata.get("tagline") or "").strip()
        writer = (metadata.get("writer") or "").strip()
        studio = (metadata.get("studio") or "").strip()
        country = (metadata.get("production_countries") or "").strip()
        country_codes = metadata.get("country_codes") or []
        certification = (metadata.get("certification") or "").strip()
        original_title = (metadata.get("original_title") or "").strip()
        release_date = (metadata.get("release_date") or "").strip()
        runtime_min = metadata.get("runtime_minutes")

        return {
            "title": title,
            "year": year,
            "res": res,
            "res_disp": res_disp,
            "season": season,
            "episode": episode,
            "file_size": file_size,
            "duration": duration,
            "runtime_min": runtime_min,
            "rating": rating,
            "clean_rating": clean_rating,
            "genre": genre,
            "director": director,
            "writer": writer,
            "studio": studio,
            "country": country,
            "country_codes": country_codes,
            "certification": certification,
            "original_title": original_title,
            "release_date": release_date,
            "tagline": tagline,
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
            "collection": metadata.get("collection"),
            "wm": wm,
            "clean_wm": clean_wm,
            "channel_url": channel_url,
        }

    def generate(
        self,
        metadata: Dict[str, Any],
        custom_watermark: str = None,
        style: Optional[str] = None,
    ) -> str:
        """Always renders clean, modern interactive article post format."""
        f = self._extract_fields(metadata, custom_watermark, self.watermark)
        return self._generate_article(f)

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
        if f.get("tagline"):
            lines.append(f"✨ <i>&ldquo;{html.escape(f['tagline'])}&rdquo;</i>")

        # Badges row: Rating & Genre only (no duplicate resolution/duration)
        badges = []
        if f["clean_rating"]:
            badges.append(f"⭐ <b>{html.escape(f['clean_rating'])}</b>")
        else:
            badges.append("⭐ <b>Belum ada</b>")
        if f["genre"]:
            badges.append(f"🎭 <i>{html.escape(str(f['genre']))}</i>")
        if badges:
            lines.append(" • ".join(badges))

        lines.append("")

        # 1. Expandable Block: Poster & Banner HD
        poster_url = f.get("poster_url") or ""
        lines.append("<blockquote expandable>")
        lines.append("🖼️ <b>POSTER & BANNER HD</b>")
        if poster_url and (poster_url.startswith("http://") or poster_url.startswith("https://")):
            lines.append(f"👉 <a href=\"{html.escape(poster_url, quote=True)}\">Ketuk untuk Buka Gambar Resolusi Penuh HD ↗</a>")
        else:
            lines.append(f"👉 <a href=\"{html.escape(f['channel_url'], quote=True)}\">Buka Galeri Poster Resmi di Channel ↗</a>")
        lines.append("</blockquote>")
        lines.append("")

        # 2. Expandable Block: Sinopsis Lengkap
        synopsis = (f.get("synopsis") or "").strip()
        synopsis_idx = None
        if synopsis:
            synopsis_idx = len(lines)
            lines.append(f"<blockquote expandable>\n📖 <b>SINOPSIS LENGKAP:</b>\n{html.escape(synopsis)}\n</blockquote>")
            lines.append("")

        # 3. Expandable Block: Detail Spesifikasi & Pemain
        spec_lines = [
            "<blockquote expandable>",
            "ℹ️ <b>DETAIL SPESIFIKASI & PEMAIN:</b>",
            "📌 <b>Informasi Film:</b>",
        ]
        if f["year"]:
            spec_lines.append(f"🗓️ <b>Tahun :</b> {html.escape(str(f['year']))}")
        if f.get("original_title") and f["original_title"].lower() != f["title"].lower():
            spec_lines.append(f"🏷️ <b>Judul Asli :</b> {html.escape(f['original_title'])}")
        if f.get("release_date"):
            spec_lines.append(f"📅 <b>Rilis :</b> {html.escape(f['release_date'])}")
        if f["genre"]:
            spec_lines.append(f"🎭 <b>Genre :</b> {html.escape(str(f['genre']))}")
        if f["director"]:
            spec_lines.append(f"🎬 <b>Sutradara :</b> {html.escape(str(f['director']))}")
        if f.get("writer"):
            spec_lines.append(f"✍️ <b>Penulis :</b> {html.escape(f['writer'])}")
        if f["actors"]:
            spec_lines.append(f"👥 <b>Pemeran :</b> {html.escape(str(f['actors']))}")
        if f.get("country"):
            c_str = f["country"]
            if f.get("country_codes") and isinstance(f["country_codes"], list):
                flags = "".join([chr(127397 + ord(c[0].upper())) + chr(127397 + ord(c[1].upper())) for c in f["country_codes"][:2] if len(c) == 2 and c.isalpha()])
                if flags:
                    c_str = f"{flags} {c_str}"
            spec_lines.append(f"🌍 <b>Negara :</b> {html.escape(c_str)}")
        if f.get("studio"):
            spec_lines.append(f"🏢 <b>Studio :</b> {html.escape(f['studio'])}")
        if f.get("certification"):
            spec_lines.append(f"🔞 <b>Rating Usia :</b> {html.escape(f['certification'])}")
        if f["res_disp"]:
            spec_lines.append(f"🎞️ <b>Kualitas :</b> {html.escape(f['res_disp'])}")
        if f["src"]:
            spec_lines.append(f"📡 <b>Source :</b> {html.escape(str(f['src']))}")
        if f["vc"]:
            spec_lines.append(f"💿 <b>Video :</b> {html.escape(str(f['vc']))}")
        if f["rg"]:
            spec_lines.append(f"🏷️ <b>Release :</b> {html.escape(str(f['rg']))}")
        if f["file_size"]:
            spec_lines.append(f"📦 <b>Ukuran :</b> {html.escape(str(f['file_size']))}")
        if f["duration"]:
            spec_lines.append(f"⏱️ <b>Durasi :</b> {html.escape(str(f['duration']))}")
        elif f.get("runtime_min") and isinstance(f["runtime_min"], (int, float)) and f["runtime_min"] > 0:
            h = int(f["runtime_min"]) // 60
            m = int(f["runtime_min"]) % 60
            rt_full = f"{h}j {m}m ({int(f['runtime_min'])} menit)" if h else f"{int(f['runtime_min'])} menit"
            spec_lines.append(f"⏱️ <b>Durasi :</b> {html.escape(rt_full)}")
        if f["audio"]:
            spec_lines.append(f"🔊 <b>Audio :</b> {html.escape(str(f['audio']))}")
        if f["sub"]:
            spec_lines.append(f"💬 <b>Subtitle :</b> {html.escape(str(f['sub']))}")
        if f["wm"]:
            spec_lines.append(f"🍿 <b>Channel :</b> <a href=\"{html.escape(f['channel_url'], quote=True)}\">{html.escape(f['wm'])}</a>")
        spec_lines.append("</blockquote>")

        lines.extend(spec_lines)

        # 4. Expandable Block: Tonton Juga Film Lain
        if f["clean_wm"] and f["genre"]:
            try:
                from .cache import MetadataCache
                c = self.cache or MetadataCache()
                if hasattr(c, "get_similar_movies"):
                    sims = c.get_similar_movies(f["clean_wm"], genre=f["genre"], exclude_title=f["title"], limit=2)
                    if sims:
                        sim_lines = [
                            "",
                            "<blockquote expandable>",
                            "🍿 <b>TONTON JUGA FILM LAIN:</b>",
                        ]
                        for sm in sims:
                            sm_title = html.escape(sm.get("title") or "Film")
                            sm_year = f" ({sm['year']})" if sm.get("year") else ""
                            sm_mid = sm.get("message_id")
                            sim_lines.append(f'• <a href="https://t.me/{f["clean_wm"]}/{sm_mid}">🎬 {sm_title}{sm_year}</a>')
                        sim_lines.append("</blockquote>")
                        lines.extend(sim_lines)
            except Exception:
                pass

        # 5. Expandable Block: Urutan Nonton (Franchise Collection)
        collection = f.get("collection")
        if collection and isinstance(collection, dict) and len(collection.get("parts", [])) > 1:
            parts = collection.get("parts", [])
            col_name = collection.get("name") or "Universe"
            number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            col_lines = [
                "",
                "<blockquote expandable>",
                f"🗺️ <b>URUTAN NONTON: {html.escape(col_name).upper()}</b>",
            ]
            for idx, part in enumerate(parts):
                num = number_emojis[idx] if idx < len(number_emojis) else f"{idx + 1}."
                p_title = (part.get("title") or "Film").strip()
                p_year = part.get("year")
                p_year_str = f" ({p_year})" if p_year else ""

                is_current = (p_title.lower() == f["title"].lower().strip())
                if is_current:
                    col_lines.append(f"{num} <b>{html.escape(p_title)}{p_year_str}</b> 📍 <i>(Film Ini)</i>")
                else:
                    existing = self.cache.find_existing_movie(p_title, p_year, f["clean_wm"]) if (self.cache and f["clean_wm"]) else None
                    if existing and existing.get("message_id"):
                        col_lines.append(f'{num} <a href="https://t.me/{f["clean_wm"]}/{existing["message_id"]}">{html.escape(p_title)}{p_year_str}</a>')
                    else:
                        col_lines.append(f"{num} {html.escape(p_title)}{p_year_str}")
            col_lines.append("</blockquote>")
            lines.extend(col_lines)

        # 6. Smart Hashtags
        tags = generate_smart_hashtags(
            title=f["title"],
            year=f["year"],
            genre=f["genre"],
            actors=f["actors"]
        )
        if tags:
            lines.append("")
            lines.append(html.escape(tags))

        return self._clamp_caption(lines, synopsis, synopsis_idx)

    @staticmethod
    def _close_unclosed_tags(text: str) -> str:
        open_tags = re.findall(r'<([a-zA-Z0-9]+)(?:\s+[^>]*)?>', text)
        close_tags = re.findall(r'</([a-zA-Z0-9]+)>', text)
        void_tags = {'img', 'br', 'hr', 'input', 'meta', 'link'}
        stack = [t for t in open_tags if t not in void_tags]
        for c in close_tags:
            if c in stack:
                stack.remove(c)
        for tag in reversed(stack):
            text += f"</{tag}>"
        return text

    def _clamp_caption(self, lines: List[str], synopsis: str, synopsis_idx: Optional[int]) -> str:
        """Guarantees caption length strictly never exceeds Telegram's 1024 char limit while preserving valid HTML."""
        def _get_text(cur_lines: List[str]) -> str:
            cleaned = []
            prev_blank = False
            for l in cur_lines:
                is_blank = (l.strip() == "")
                if is_blank and prev_blank:
                    continue
                cleaned.append(l)
                prev_blank = is_blank
            return "\n".join(cleaned).strip()

        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        def _remove_block(cur_lines: List[str], marker: str) -> List[str]:
            out = []
            in_block = False
            for l in cur_lines:
                if marker in l:
                    in_block = True
                    if out and "<blockquote expandable>" in out[-1]:
                        out.pop()
                    if out and out[-1] == "":
                        out.pop()
                    continue
                if in_block:
                    if "</blockquote>" in l:
                        in_block = False
                    continue
                out.append(l)
            return out

        # 1. Drop optional 'TONTON JUGA FILM LAIN'
        lines = _remove_block(lines, "TONTON JUGA FILM LAIN")
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 2. Drop secondary spec keys from DETAIL SPESIFIKASI & PEMAIN
        secondary_keys = [
            "🏷️ <b>Judul Asli :</b>",
            "📅 <b>Rilis :</b>",
            "✍️ <b>Penulis :</b>",
            "🏢 <b>Studio :</b>",
            "🌍 <b>Negara :</b>",
            "🔞 <b>Rating Usia :</b>",
            "🏷️ <b>Release :</b>",
            "💿 <b>Video :</b>",
        ]
        lines = [l for l in lines if not any(k in l for k in secondary_keys)]
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 3. Trim URUTAN NONTON (keep current film + 1 sibling before and after)
        if any("URUTAN NONTON:" in l for l in lines):
            new_lines = []
            in_col = False
            col_parts = []
            for l in lines:
                if "URUTAN NONTON:" in l:
                    in_col = True
                    new_lines.append(l)
                    continue
                if in_col:
                    if "</blockquote>" in l:
                        in_col = False
                        curr_idx = next((i for i, p in enumerate(col_parts) if "(Film Ini)" in p), 0)
                        keep_indices = {curr_idx}
                        if curr_idx > 0:
                            keep_indices.add(curr_idx - 1)
                        if curr_idx + 1 < len(col_parts):
                            keep_indices.add(curr_idx + 1)
                        for i, p in enumerate(col_parts):
                            if i in keep_indices:
                                new_lines.append(p)
                        hidden_count = len(col_parts) - len(keep_indices)
                        if hidden_count > 0:
                            new_lines.append(f"• <i>...dan {hidden_count} film lainnya</i>")
                        new_lines.append(l)
                        continue
                    col_parts.append(l)
                    continue
                new_lines.append(l)
            lines = new_lines
            result_text = _get_text(lines)
            if len(result_text) <= 1024:
                return result_text

        # 4. Drop POSTER & BANNER HD block (video already includes thumbnail/media)
        lines = _remove_block(lines, "POSTER & BANNER HD")
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 5. Trim synopsis cleanly
        s_idx = next((i for i, l in enumerate(lines) if "SINOPSIS" in l), None)
        if synopsis and s_idx is not None and s_idx < len(lines):
            excess = len(result_text) - 1000
            avail = max(40, len(synopsis) - excess)
            trimmed = synopsis[:avail].rstrip() + "..."
            lines[s_idx] = f"<blockquote expandable>\n📖 <b>SINOPSIS LENGKAP:</b>\n{html.escape(trimmed)}\n</blockquote>"
            result_text = _get_text(lines)
            if len(result_text) <= 1024:
                return result_text

        # 6. Drop URUTAN NONTON completely if still too long
        lines = _remove_block(lines, "URUTAN NONTON:")
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 7. Drop hashtags
        lines = [l for l in lines if not l.strip().startswith("#")]
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 8. Drop synopsis completely
        lines = _remove_block(lines, "SINOPSIS")
        result_text = _get_text(lines)
        if len(result_text) <= 1024:
            return result_text

        # 9. Ultimate fallback: hard cut at 1000 characters and close HTML tags
        if len(result_text) > 1024:
            cut = result_text[:1000].rstrip() + "..."
            result_text = self._close_unclosed_tags(cut)

        return result_text
