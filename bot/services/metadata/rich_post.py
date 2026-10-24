"""Telegram Bot API sendRichMessage (Bot API 10.1+) Rich Article Post Generator.

Implements native Telegram Rich Article cards:
- Single unified post containing video, slideshow gallery, collapsible details, and inline buttons.
- Video player embedded directly in the card.
- Native <tg-slideshow> carousel (swipe left/right between banner and poster).
- Native <details><summary> (tap to expand/collapse synopsis and tech specs).
- Native <h1-h6> typography hierarchy.
- Native <hr/> section dividers and <footer> channel branding.
- Full inline keyboard integration.
"""

import asyncio
import difflib
import html as html_mod
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from .hashtags import generate_smart_hashtags
from .synopsis import ensure_indonesian_text

logger = logging.getLogger(__name__)


def _country_code_to_flag(code: str) -> str:
    """Convert a 2-letter ISO country code to its Unicode flag emoji."""
    if isinstance(code, str) and len(code) == 2 and code.isalpha():
        return chr(127397 + ord(code[0].upper())) + chr(127397 + ord(code[1].upper()))
    return ""


def _format_money(amount: Union[int, float]) -> str:
    """Format monetary amount to compact string (e.g., $15M, $1.2B)."""
    try:
        val = float(amount)
        if val <= 0:
            return ""
        if val >= 1_000_000_000:
            return f"${val / 1_000_000_000:.1f}B".replace(".0B", "B")
        if val >= 1_000_000:
            return f"${val / 1_000_000:.1f}M".replace(".0M", "M")
        if val >= 1_000:
            return f"${val / 1_000:.0f}K"
        return f"${val:,.0f}"
    except Exception:
        return ""


def _format_indonesian_date(date_str: str) -> str:
    """Format YYYY-MM-DD date string to Indonesian formatted date."""
    if not date_str:
        return ""
    months = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(date_str).strip())
    if m:
        year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12:
            return f"{day} {months[month - 1]} {year}"
    return str(date_str).strip()


GENRE_EMOJIS = {
    "action": "💥",
    "aksi": "💥",
    "adventure": "🗺️",
    "petualangan": "🗺️",
    "animation": "🎨",
    "animasi": "🎨",
    "comedy": "🤣",
    "komedi": "🤣",
    "crime": "🕵️",
    "kriminal": "🕵️",
    "documentary": "📹",
    "dokumenter": "📹",
    "drama": "🎭",
    "family": "👨‍👩‍👧",
    "keluarga": "👨‍👩‍👧",
    "fantasy": "🧙",
    "fantasi": "🧙",
    "history": "📜",
    "sejarah": "📜",
    "horror": "😱",
    "horor": "😱",
    "music": "🎵",
    "musik": "🎵",
    "mystery": "🔍",
    "misteri": "🔍",
    "romance": "💖",
    "romantis": "💖",
    "science fiction": "🚀",
    "sci-fi": "🚀",
    "fiksi ilmiah": "🚀",
    "thriller": "🔪",
    "tv movie": "📺",
    "film tv": "📺",
    "war": "⚔️",
    "perang": "⚔️",
    "western": "🤠",
}


def _format_genre_with_emojis(genre_str: str) -> str:
    """Format genre string with matching emoji for the primary genre."""
    if not genre_str:
        return ""
    g_s = str(genre_str).strip()
    if any(ord(c) > 127 for c in g_s[:3]):
        return g_s
    first_part = g_s.split(",")[0].strip().lower()
    for k, emo in GENRE_EMOJIS.items():
        if k in first_part:
            return f"{emo} {g_s}"
    return f"🎭 {g_s}"


def build_rich_article_payload(
    chat_id: Union[int, str],
    metadata: Dict[str, Any],
    watermark: str,
    video_file_id: Optional[str] = None,
    banner_file_id_or_url: Optional[str] = None,
    poster_file_id_or_url: Optional[str] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
    protect_content: bool = False,
    disable_notification: bool = False,
) -> Dict[str, Any]:
    """Build the complete JSON payload for Telegram Bot API `sendRichMessage`.

    Returns a dict ready to be JSON-encoded and sent to /sendRichMessage.
    """
    title = (metadata.get("title") or "Film").strip()
    year = metadata.get("year")
    season = metadata.get("season")
    episode = metadata.get("episode")
    rating = metadata.get("rating")
    genre = metadata.get("genre")
    resolution = metadata.get("resolution")
    duration = metadata.get("duration")
    file_size = metadata.get("fileSize")
    audio = metadata.get("audio") or metadata.get("audioCodec")
    subtitle = metadata.get("subtitle")
    director = metadata.get("director")
    actors = metadata.get("actors")
    synopsis = (metadata.get("synopsis") or "").strip()
    if synopsis:
        synopsis = ensure_indonesian_text(synopsis)
    source = metadata.get("source")
    video_codec = metadata.get("videoCodec")
    audio_codec = metadata.get("audioCodec")
    audio_channels = metadata.get("audioChannels")
    release_group = metadata.get("releaseGroup")

    tagline = (metadata.get("tagline") or "").strip()
    original_title = (metadata.get("original_title") or "").strip()
    prod_countries = (metadata.get("production_countries") or "").strip()
    country_codes = metadata.get("country_codes") or []
    spoken_langs = (metadata.get("spoken_languages") or "").strip()
    runtime_min = metadata.get("runtime_minutes")
    budget = metadata.get("budget") or 0
    revenue = metadata.get("revenue") or 0
    popularity = metadata.get("popularity") or 0.0
    release_date = (metadata.get("release_date") or "").strip()
    certification = (metadata.get("certification") or "").strip()
    writer = (metadata.get("writer") or "").strip()
    studio = (metadata.get("studio") or "").strip()
    awards = (metadata.get("awards") or "").strip()
    rotten_tomatoes = (metadata.get("rotten_tomatoes") or "").strip()
    metascore = (metadata.get("metascore") or "").strip()
    watch_providers = metadata.get("watch_providers") or []
    gallery_images = metadata.get("gallery_images") or []

    clean_wm = (watermark or "").lstrip("@").strip()
    channel_display = f"@{clean_wm}" if clean_wm else "@filmindochannel"

    # Title display
    title_disp = html_mod.escape(title.upper())
    if season is not None and episode is not None:
        title_disp += f" (S{int(season):02d}E{int(episode):02d})"
    elif year:
        title_disp += f" ({year})"

    html_parts: List[str] = []
    media_items: List[Dict[str, Any]] = []

    # 1. VIDEO (Film Player at top of card)
    if video_file_id:
        html_parts.append('<video src="tg://video?id=film_video"></video>')
        media_items.append({
            "id": "film_video",
            "media": {
                "type": "video",
                "media": video_file_id
            }
        })

    # 2. HEADING (Film Title & Tagline)
    html_parts.append(f"<h1>🎬 {title_disp}</h1>")
    if tagline:
        html_parts.append(f"<p>✨ <i>&ldquo;{html_mod.escape(tagline)}&rdquo;</i></p>")

    # 3. SLIDESHOW (Banner, Poster & Stills swipeable gallery — max 3 distinct images)
    slideshow_imgs: List[str] = []
    all_gallery: List[str] = []
    if banner_file_id_or_url:
        all_gallery.append(banner_file_id_or_url)
    if poster_file_id_or_url and poster_file_id_or_url not in all_gallery:
        all_gallery.append(poster_file_id_or_url)

    known_primary = set()
    if banner_file_id_or_url:
        known_primary.add(banner_file_id_or_url)
        if metadata.get("backdrop_url"):
            known_primary.add(metadata.get("backdrop_url"))
    if poster_file_id_or_url:
        known_primary.add(poster_file_id_or_url)
        if metadata.get("poster_url"):
            known_primary.add(metadata.get("poster_url"))

    for g_url in gallery_images:
        if g_url and g_url not in all_gallery and g_url not in known_primary and len(all_gallery) < 3:
            all_gallery.append(g_url)

    for idx, img_src in enumerate(all_gallery):
        img_id = "banner_img" if idx == 0 else ("poster_img" if idx == 1 else f"gallery_img_{idx + 1}")
        slideshow_imgs.append(f'<img src="tg://photo?id={img_id}"/>')
        media_items.append({
            "id": img_id,
            "media": {
                "type": "photo",
                "media": img_src
            }
        })

    if slideshow_imgs:
        if len(slideshow_imgs) > 1:
            imgs_content = f"<tg-slideshow>\n{''.join(slideshow_imgs)}\n</tg-slideshow>"
            summary_label = f"🖼️ Poster &amp; Banner HD ({len(slideshow_imgs)} gambar)"
        else:
            imgs_content = slideshow_imgs[0]
            summary_label = "🖼️ Poster &amp; Banner HD"
        html_parts.append(
            f"<details>\n"
            f"<summary>{summary_label}</summary>\n"
            f"{imgs_content}\n"
            f"</details>"
        )

    # Fallback retrieve rating/genre/extra fields if missing from cache
    if title:
        try:
            from .cache import MetadataCache
            _c = MetadataCache()
            clean_t = re.sub(r"[^\w\s]", "", title).strip()
            c_key = f"rating_v2_{clean_t.lower()}_{year}" if year else f"rating_v2_{clean_t.lower()}"
            cached_raw = _c.get_setting(c_key, "")
            if cached_raw:
                c_data = json.loads(cached_raw)
                if not rating and c_data.get("rating"):
                    rating = c_data["rating"]
                if not genre and c_data.get("genre"):
                    genre = c_data["genre"]
                if not director and c_data.get("director"):
                    director = c_data["director"]
                if not actors and c_data.get("actors"):
                    actors = c_data["actors"]
                if not tagline and c_data.get("tagline"):
                    tagline = c_data["tagline"]
                if not original_title and c_data.get("original_title"):
                    original_title = c_data["original_title"]
                if not prod_countries and c_data.get("production_countries"):
                    prod_countries = c_data["production_countries"]
                if not country_codes and c_data.get("country_codes"):
                    country_codes = c_data["country_codes"]
                if not spoken_langs and c_data.get("spoken_languages"):
                    spoken_langs = c_data["spoken_languages"]
                if not runtime_min and c_data.get("runtime_minutes"):
                    runtime_min = c_data["runtime_minutes"]
                if not budget and c_data.get("budget"):
                    budget = c_data["budget"]
                if not revenue and c_data.get("revenue"):
                    revenue = c_data["revenue"]
                if not popularity and c_data.get("popularity"):
                    popularity = c_data["popularity"]
                if not release_date and c_data.get("release_date"):
                    release_date = c_data["release_date"]
                if not certification and c_data.get("certification"):
                    certification = c_data["certification"]
                if not writer and c_data.get("writer"):
                    writer = c_data["writer"]
                if not studio and c_data.get("studio"):
                    studio = c_data["studio"]
                if not awards and c_data.get("awards"):
                    awards = c_data["awards"]
                if not rotten_tomatoes and c_data.get("rotten_tomatoes"):
                    rotten_tomatoes = c_data["rotten_tomatoes"]
                if not metascore and c_data.get("metascore"):
                    metascore = c_data["metascore"]
                if not watch_providers and c_data.get("watch_providers"):
                    watch_providers = c_data["watch_providers"]
        except Exception:
            pass

    # 4. BADGES (Rating Bar & Genre, plus Country flags, Runtime, Content Rating)
    badge_items: List[str] = []

    clean_rating = None
    if rating:
        m = re.search(r"(\d+(?:\.\d+)?)", str(rating))
        if m:
            clean_rating = f"{m.group(1)}/10"
        elif str(rating).strip().lower() not in ("none", "n/a", "-", "", "0", "0.0"):
            clean_rating = str(rating).strip()

    if clean_rating:
        m_s = re.search(r"(\d+(?:\.\d+)?)", clean_rating)
        bar_str = ""
        if m_s:
            try:
                score = float(m_s.group(1))
                filled = max(0, min(10, int(round(score))))
                bar_str = " " + ("█" * filled + "░" * (10 - filled))
            except ValueError:
                pass
        badge_items.append(f"⭐ <b>{html_mod.escape(clean_rating)}</b>{bar_str}")
    else:
        badge_items.append("⭐ <b>Belum ada</b>")

    if genre:
        badge_items.append(html_mod.escape(_format_genre_with_emojis(str(genre))))

    if country_codes and isinstance(country_codes, list):
        flags = "".join([_country_code_to_flag(c) for c in country_codes[:2] if _country_code_to_flag(c)])
        if flags:
            badge_items.append(flags)

    if runtime_min and isinstance(runtime_min, (int, float)) and runtime_min > 0:
        h = int(runtime_min) // 60
        m = int(runtime_min) % 60
        rt_str = f"{h}j {m}m" if h else f"{m}m"
        badge_items.append(f"⏱️ {rt_str}")

    if certification:
        cert_icon = "🔞" if any(x in certification.upper() for x in ["17", "18", "21", "R", "NC-17", "DEWASA"]) else "🏷️"
        badge_items.append(f"{cert_icon} {html_mod.escape(certification)}")

    if badge_items:
        html_parts.append(f"<p>{' • '.join(badge_items)}</p>")

    # Status Badges: Trending, Baru Rilis, Rating Tinggi
    status_badges: List[str] = []
    if release_date:
        try:
            import datetime
            rel_dt = datetime.datetime.strptime(str(release_date)[:10], "%Y-%m-%d").date()
            diff_days = (datetime.date.today() - rel_dt).days
            if 0 <= diff_days <= 45:
                status_badges.append("🆕 <b>BARU RILIS</b>")
            elif diff_days < 0:
                status_badges.append("🔜 <b>SEGERA TAYANG</b>")
        except Exception:
            pass

    try:
        if float(popularity) >= 50.0:
            status_badges.append("🔥 <b>SEDANG TRENDING</b>")
    except (ValueError, TypeError):
        pass

    if clean_rating:
        m_s = re.search(r"(\d+(?:\.\d+)?)", clean_rating)
        if m_s:
            try:
                if float(m_s.group(1)) >= 8.0 and "🔥 <b>SEDANG TRENDING</b>" not in status_badges:
                    status_badges.append("🏆 <b>RATING TINGGI</b>")
            except ValueError:
                pass

    if status_badges:
        html_parts.append(f"<p>{' • '.join(status_badges)}</p>")

    html_parts.append("<hr/>")

    # 5. EXPANDABLE DETAILS — Sinopsis Lengkap (hanya di dalam lipatan agar tidak double)
    if synopsis:
        clean_synopsis = html_mod.escape(synopsis)
        html_parts.append(
            f"<details>\n"
            f"<summary>📖 Sinopsis Lengkap</summary>\n"
            f"{clean_synopsis}\n"
            f"</details>"
        )

    # 6. EXPANDABLE DETAILS — Spesifikasi & Pemain Lengkap
    spec_lines: List[str] = ["📌 <b>Informasi Film:</b>"]
    if year:
        spec_lines.append(f"🗓️ <b>Tahun :</b> {html_mod.escape(str(year))}")
    if original_title and original_title.lower() != title.lower():
        spec_lines.append(f"🏷️ <b>Judul Asli :</b> {html_mod.escape(original_title)}")
    if release_date:
        formatted_date = _format_indonesian_date(release_date)
        if formatted_date:
            spec_lines.append(f"📅 <b>Rilis :</b> {html_mod.escape(formatted_date)}")
    if genre:
        spec_lines.append(f"🎭 <b>Genre :</b> {html_mod.escape(str(genre))}")
    if director:
        spec_lines.append(f"🎬 <b>Sutradara :</b> {html_mod.escape(str(director))}")
    if writer:
        spec_lines.append(f"✍️ <b>Penulis :</b> {html_mod.escape(writer)}")
    if actors:
        spec_lines.append(f"👥 <b>Pemeran :</b> {html_mod.escape(str(actors))}")
    if prod_countries:
        country_display = prod_countries
        if country_codes and isinstance(country_codes, list):
            flags = " ".join([_country_code_to_flag(c) for c in country_codes[:2] if _country_code_to_flag(c)])
            if flags:
                country_display = f"{flags} {country_display}"
        spec_lines.append(f"🌍 <b>Negara :</b> {html_mod.escape(country_display)}")
    if spoken_langs:
        spec_lines.append(f"🗣️ <b>Bahasa :</b> {html_mod.escape(spoken_langs)}")
    if studio:
        spec_lines.append(f"🏢 <b>Studio :</b> {html_mod.escape(studio)}")
    if certification:
        spec_lines.append(f"🔞 <b>Rating Usia :</b> {html_mod.escape(certification)}")
    if budget and isinstance(budget, (int, float)) and budget > 0:
        spec_lines.append(f"💰 <b>Budget :</b> {html_mod.escape(_format_money(budget))}")
    if revenue and isinstance(revenue, (int, float)) and revenue > 0:
        spec_lines.append(f"💵 <b>Box Office :</b> {html_mod.escape(_format_money(revenue))}")
    if resolution:
        res_display = str(resolution)
        if resolution == "1080p":
            res_display = "1080p • Full HD"
        elif resolution == "720p":
            res_display = "720p • HD"
        elif resolution == "2160p":
            res_display = "2160p • 4K UHD"
        spec_lines.append(f"🎞️ <b>Kualitas :</b> {html_mod.escape(res_display)}")
    if source:
        spec_lines.append(f"📡 <b>Source :</b> {html_mod.escape(str(source))}")
    if video_codec:
        spec_lines.append(f"💿 <b>Video :</b> {html_mod.escape(str(video_codec))}")
    if release_group:
        spec_lines.append(f"🏷️ <b>Release :</b> {html_mod.escape(str(release_group))}")
    if file_size:
        spec_lines.append(f"📦 <b>Ukuran :</b> {html_mod.escape(str(file_size))}")
    if duration:
        spec_lines.append(f"⏱️ <b>Durasi :</b> {html_mod.escape(str(duration))}")
    elif runtime_min and isinstance(runtime_min, (int, float)) and runtime_min > 0:
        h = int(runtime_min) // 60
        m = int(runtime_min) % 60
        rt_full = f"{h}j {m}m ({int(runtime_min)} menit)" if h else f"{int(runtime_min)} menit"
        spec_lines.append(f"⏱️ <b>Durasi :</b> {html_mod.escape(rt_full)}")
    if audio:
        spec_lines.append(f"🔊 <b>Audio :</b> {html_mod.escape(str(audio))}")
    elif audio_codec:
        ac_str = f"{audio_codec} {audio_channels}" if audio_channels else audio_codec
        spec_lines.append(f"🔊 <b>Audio :</b> {html_mod.escape(str(ac_str))}")
    if subtitle:
        spec_lines.append(f"💬 <b>Subtitle :</b> {html_mod.escape(str(subtitle))}")

    if len(spec_lines) > 1:
        specs_body = "<br/>\n".join(spec_lines)
        html_parts.append(
            f"<details>\n"
            f"<summary>ℹ️ Detail Spesifikasi &amp; Pemain</summary>\n"
            f"{specs_body}\n"
            f"</details>"
        )

    # 7. EXPANDABLE DETAILS — Penghargaan & Rating Lain (Awards, Rotten Tomatoes, Metascore)
    awards_lines: List[str] = []
    if rotten_tomatoes:
        awards_lines.append(f"🍅 <b>Rotten Tomatoes :</b> {html_mod.escape(str(rotten_tomatoes))}")
    if metascore:
        awards_lines.append(f"📊 <b>Metascore :</b> {html_mod.escape(str(metascore))}")
    if awards:
        awards_lines.append(f"🏅 <b>Penghargaan :</b> {html_mod.escape(str(awards))}")

    if awards_lines:
        awards_body = "<br/>\n".join(awards_lines)
        html_parts.append(
            f"<details>\n"
            f"<summary>🏆 Penghargaan &amp; Rating Lain</summary>\n"
            f"{awards_body}\n"
            f"</details>"
        )

    # 8. EXPANDABLE DETAILS — Tersedia di Platform (Streaming Providers)
    if watch_providers:
        platform_icons = {
            "netflix": "🟥",
            "disney": "🟦",
            "hotstar": "🟦",
            "vidio": "🟩",
            "prime": "🟨",
            "amazon": "🟨",
            "apple": "⬛",
            "hbo": "🟪",
            "max": "🟪",
            "viu": "🟨",
            "wetv": "🟧",
            "catchplay": "🟧",
            "iqiyi": "🟩",
        }
        wp_lines: List[str] = []
        for wp in watch_providers:
            wp_name = wp.strip() if isinstance(wp, str) else (wp.get("provider_name") or wp.get("name") or "").strip()
            if not wp_name:
                continue
            icon = "▶️"
            clean_wp = wp_name.lower()
            for k, ico in platform_icons.items():
                if k in clean_wp:
                    icon = ico
                    break
            wp_lines.append(f"• <b>{html_mod.escape(wp_name)}</b> {icon}")

        if wp_lines:
            wp_body = "<br/>\n".join(wp_lines)
            html_parts.append(
                f"<details>\n"
                f"<summary>📺 Tersedia di Platform</summary>\n"
                f"{wp_body}\n"
                f"</details>"
            )

    # 7. EXPANDABLE DETAILS — Tonton Juga Film Lain (Rekomendasi Pintar Katalog Channel)
    if clean_wm and genre:
        try:
            from .cache import MetadataCache
            _mc = MetadataCache()
            similar_movies = _mc.get_similar_movies(clean_wm, genre=genre, exclude_title=title, limit=3)
            if similar_movies:
                sim_links = []
                for sm in similar_movies:
                    sm_title = html_mod.escape(sm.get("title") or "Film")
                    sm_year = f" ({sm['year']})" if sm.get("year") else ""
                    sm_mid = sm.get("message_id")
                    sm_genre = f" — <i>{html_mod.escape(sm['genre'])}</i>" if sm.get("genre") else ""
                    sim_links.append(f'• <a href="https://t.me/{clean_wm}/{sm_mid}">🎬 <b>{sm_title}{sm_year}</b>{sm_genre}</a>')

                sim_body = "<br/>\n".join(sim_links)
                html_parts.append(
                    f"<details>\n"
                    f"<summary>🍿 Tonton Juga Film Lain</summary>\n"
                    f"{sim_body}\n"
                    f"</details>"
                )
        except Exception as se:
            logger.debug(f"Failed to fetch similar movies: {se}")

    # 8. EXPANDABLE DETAILS — Urutan Nonton (Franchise / Universe Collection)
    collection = metadata.get("collection")
    if not collection and title:
        try:
            from .cache import MetadataCache
            _c = MetadataCache()
            clean_t = re.sub(r"[^\w\s]", "", title).strip()
            c_key = f"rating_v2_{clean_t.lower()}_{year}" if year else f"rating_v2_{clean_t.lower()}"
            cached_raw = _c.get_setting(c_key, "")
            if cached_raw:
                c_data = json.loads(cached_raw)
                if c_data.get("collection"):
                    collection = c_data["collection"]
        except Exception:
            pass

    if collection and isinstance(collection, dict) and len(collection.get("parts", [])) > 1:
        parts = collection.get("parts", [])
        col_name = collection.get("name") or "Universe"
        from .cache import MetadataCache
        _mc = MetadataCache()

        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        part_lines = []
        for idx, part in enumerate(parts):
            num = number_emojis[idx] if idx < len(number_emojis) else f"{idx + 1}."
            p_title = (part.get("title") or "Film").strip()
            p_year = part.get("year")
            p_year_str = f" ({p_year})" if p_year else ""

            # Check if this part is the current movie being posted
            is_current = (p_title.lower() == title.lower().strip())
            if not is_current and year and p_year and p_year == year:
                is_current = (difflib.SequenceMatcher(None, p_title.lower(), title.lower().strip()).ratio() >= 0.85)

            if is_current:
                part_lines.append(f"{num} <b>{html_mod.escape(p_title)}{p_year_str}</b> 📍 <i>(Film Ini)</i>")
            else:
                existing = _mc.find_existing_movie(p_title, p_year, clean_wm) if clean_wm else None
                if existing and existing.get("message_id"):
                    mid = existing["message_id"]
                    part_lines.append(f'{num} <a href="https://t.me/{clean_wm}/{mid}">{html_mod.escape(p_title)}{p_year_str}</a>')
                else:
                    part_lines.append(f"{num} {html_mod.escape(p_title)}{p_year_str}")

        if part_lines:
            col_body = "<br/>\n".join(part_lines)
            html_parts.append(
                f"<details>\n"
                f"<summary>🗺️ Urutan Nonton: {html_mod.escape(col_name)}</summary>\n"
                f"{col_body}\n"
                f"</details>"
            )

    # 9. SMART HASHTAGS
    hashtags = generate_smart_hashtags(title=title, year=year, genre=genre, actors=actors)
    if hashtags:
        html_parts.append(f"<p>{html_mod.escape(hashtags)}</p>")

    html_parts.append("<hr/>")

    # 10. FOOTER
    html_parts.append(f"<footer>🍿 Channel Resmi: {channel_display}</footer>")

    # Compile rich_message object
    rich_msg_obj: Dict[str, Any] = {
        "html": "\n".join(html_parts)
    }
    if media_items:
        rich_msg_obj["media"] = media_items

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": rich_msg_obj,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup
    if protect_content:
        payload["protect_content"] = True
    if disable_notification:
        payload["disable_notification"] = True

    return payload


async def async_send_rich_article_post(
    bot_token: str,
    chat_id: Union[int, str],
    metadata: Dict[str, Any],
    watermark: str,
    video_file_id: Optional[str] = None,
    banner_file_id_or_url: Optional[str] = None,
    poster_file_id_or_url: Optional[str] = None,
    banner_path: Optional[str] = None,
    poster_path: Optional[str] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
    protect_content: bool = False,
    disable_notification: bool = False,
) -> Optional[Dict[str, Any]]:
    """Send rich article post using Telegram Bot API sendRichMessage.

    Supports local file attachments via multipart/form-data with attach://.
    Returns the message result dict from Telegram on success, or None on error.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendRichMessage"

    files_to_upload: Dict[str, str] = {}
    if banner_path and os.path.exists(banner_path):
        banner_file_id_or_url = "attach://banner_file"
        files_to_upload["banner_file"] = banner_path

    if poster_path and os.path.exists(poster_path):
        poster_file_id_or_url = "attach://poster_file"
        files_to_upload["poster_file"] = poster_path

    payload = build_rich_article_payload(
        chat_id=chat_id,
        metadata=metadata,
        watermark=watermark,
        video_file_id=video_file_id,
        banner_file_id_or_url=banner_file_id_or_url,
        poster_file_id_or_url=poster_file_id_or_url,
        reply_markup=reply_markup,
        protect_content=protect_content,
        disable_notification=disable_notification,
    )

    def _sync_request():
        if not files_to_upload:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
        else:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body = bytearray()
            for k, v in payload.items():
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
                body.extend(json.dumps(v).encode() if isinstance(v, (dict, list)) else str(v).encode())
                body.extend(b"\r\n")
            for fname, fpath in files_to_upload.items():
                if fpath and os.path.exists(fpath):
                    body.extend(f"--{boundary}\r\n".encode())
                    body.extend(f'Content-Disposition: form-data; name="{fname}"; filename="{os.path.basename(fpath)}"\r\n'.encode())
                    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
                    with open(fpath, "rb") as f:
                        body.extend(f.read())
                    body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())
            req = urllib.request.Request(
                url,
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        res = await asyncio.to_thread(_sync_request)
        if res and res.get("ok"):
            logger.info(f"sendRichMessage successful: msg_id={res['result'].get('message_id')}")
            return res.get("result")
        logger.warning(f"sendRichMessage returned error: {res}")
        return None
    except urllib.error.HTTPError as he:
        body = he.read().decode("utf-8", errors="ignore")
        logger.warning(f"sendRichMessage HTTP {he.code}: {body}")
        return None
    except Exception as e:
        logger.warning(f"sendRichMessage failed: {e}")
        return None


async def async_delete_telegram_message(
    bot_token: str,
    chat_id: Union[int, str],
    message_id: int
) -> Tuple[bool, Optional[str]]:
    """Delete a message from channel using Telegram Bot API deleteMessage.

    Returns:
        (True, None) if deleted successfully (or already deleted).
        (False, error_description) if deletion failed.
    """
    if not bot_token:
        return False, "BOT_TOKEN tidak tersedia"

    clean_chat = str(chat_id).strip()
    if not clean_chat.startswith("@") and not clean_chat.startswith("-"):
        clean_chat = f"@{clean_chat}"

    url = f"https://api.telegram.org/bot{bot_token}/deleteMessage"
    payload = json.dumps({"chat_id": clean_chat, "message_id": int(message_id)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    def _sync():
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return True, None
                desc = data.get("description", "Unknown error")
                if "message to delete not found" in desc.lower():
                    return True, None
                return False, desc
        except urllib.error.HTTPError as he:
            try:
                body = json.loads(he.read().decode("utf-8"))
                desc = body.get("description", f"HTTP {he.code}")
                if "message to delete not found" in desc.lower():
                    return True, None
                return False, desc
            except Exception:
                return False, f"HTTP {he.code}"
        except Exception as e:
            return False, str(e)

    return await asyncio.to_thread(_sync)


async def async_delete_telegram_messages(
    bot_token: str,
    chat_id: Union[int, str],
    message_ids: List[int]
) -> Tuple[bool, Optional[str]]:
    """Delete multiple messages using Telegram Bot API deleteMessages with deleteMessage fallback."""
    if not bot_token:
        return False, "BOT_TOKEN tidak tersedia"
    if not message_ids:
        return True, None

    clean_chat = str(chat_id).strip()
    if not clean_chat.startswith("@") and not clean_chat.startswith("-"):
        clean_chat = f"@{clean_chat}"

    # Coba batch deleteMessages (Bot API 7.0+)
    url_batch = f"https://api.telegram.org/bot{bot_token}/deleteMessages"
    payload_batch = json.dumps({"chat_id": clean_chat, "message_ids": [int(m) for m in message_ids]}).encode("utf-8")
    req_batch = urllib.request.Request(url_batch, data=payload_batch, headers={"Content-Type": "application/json"})

    def _sync_batch():
        try:
            with urllib.request.urlopen(req_batch, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return True, None
                return False, data.get("description", "deleteMessages failed")
        except Exception as e:
            return False, str(e)

    ok, err = await asyncio.to_thread(_sync_batch)
    if ok:
        return True, None

    # Fallback ke deleteMessage per id
    any_deleted = False
    last_err = err
    for mid in message_ids:
        s_ok, s_err = await async_delete_telegram_message(bot_token, clean_chat, mid)
        if s_ok:
            any_deleted = True
        else:
            last_err = s_err

    return any_deleted, last_err


async def async_delete_channel_post(
    client: Any,
    bot_token: Optional[str],
    chat_id: Union[int, str],
    message_ids: Union[int, List[int]]
) -> Tuple[bool, Optional[str]]:
    """Delete message(s) from channel trying Bot API HTTP first, then Pyrogram MTProto fallback.

    Returns:
        (True, None) on success.
        (False, error_reason) on failure.
    """
    clean_chat = str(chat_id).strip()
    if not clean_chat.startswith("@") and not clean_chat.startswith("-"):
        clean_chat = f"@{clean_chat}"

    m_list = [message_ids] if isinstance(message_ids, int) else list(message_ids)
    if not m_list:
        return True, None

    last_err: Optional[str] = None

    # 1. Coba via HTTP Bot API deleteMessages/deleteMessage (paling andal untuk bot)
    if bot_token:
        ok, err = await async_delete_telegram_messages(bot_token, clean_chat, m_list)
        if ok:
            logger.info(f"Berhasil menghapus pesan {m_list} dari {clean_chat} via Bot API")
            return True, None
        last_err = err
        logger.warning(f"Bot API deleteMessages {m_list} di {clean_chat} gagal: {err}")

    # 2. Coba via Pyrogram client MTProto sebagai fallback
    if client:
        try:
            await client.delete_messages(chat_id=clean_chat, message_ids=m_list)
            logger.info(f"Berhasil menghapus pesan {m_list} dari {clean_chat} via Pyrogram")
            return True, None
        except Exception as pe:
            pe_str = str(pe)
            if "message to delete not found" in pe_str.lower() or "MESSAGE_ID_INVALID" in pe_str:
                return True, None
            last_err = pe_str
            logger.warning(f"Pyrogram delete_messages {m_list} di {clean_chat} gagal: {pe}")

    return False, last_err


