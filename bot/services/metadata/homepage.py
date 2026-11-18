"""Visual pinned homepage for the Telegram channel.

Builds one 1280x720 collage (hero poster + 2x2 grid), a short HTML caption with
numbered movie links, and the catalog/search/request keyboard.

The module is deliberately side-effect free except for poster URL caching in the
existing settings table. Telegram calls live in bot.handlers.
"""
import datetime
import hashlib
import html
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .banner import _download_image_bytes, _get_font, _load_image
from .cache import WIB

logger = logging.getLogger(__name__)

WIDTH = 1280
HEIGHT = 720
CAPTION_LIMIT = 1024

MONTHS_ID = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
    7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des",
}


def _clean_title(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title or "").strip().lower()


def poster_key(title: str, year: Any = None) -> str:
    key = f"homepage_poster_{_clean_title(title)}"
    return f"{key}_{year}" if year else key


def backdrop_key(title: str, year: Any = None) -> str:
    key = f"homepage_backdrop_{_clean_title(title)}"
    return f"{key}_{year}" if year else key


def _title_with_year(movie: Dict[str, Any]) -> str:
    title = str(movie.get("title") or "Film").strip()
    year = movie.get("year")
    return f"{title} ({year})" if year else title


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _rating_value(rating: Any) -> Optional[float]:
    if rating is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(rating))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _rating_label(rating: Any) -> str:
    value = _rating_value(rating)
    return f"{value:.1f}" if value is not None else ""


def _quality_label(movie: Dict[str, Any]) -> str:
    return str(movie.get("quality") or movie.get("resolution") or "").strip()


def _local_image_bytes(source: Optional[str]) -> Optional[bytes]:
    if not source:
        return None
    try:
        if source.startswith(("http://", "https://")):
            return _download_image_bytes(source)
        if os.path.exists(source):
            with open(source, "rb") as handle:
                return handle.read()
    except Exception as exc:
        logger.debug("Homepage image load failed for %s: %s", source, exc)
    return None


def _parse_cached_meta(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_homepage_assets(
    cache,
    movies: List[Dict[str, Any]],
    tmdb_service=None,
) -> List[Dict[str, Any]]:
    """Resolve poster/backdrop bytes for the newest movies.

    Order: homepage setting, rating_v2 cache, banner_fid cache, TMDb, placeholder.
    Download failures return a movie without image bytes; renderer draws a
    placeholder instead of failing the whole homepage.
    """
    assets: List[Dict[str, Any]] = []
    for movie in movies:
        title = str(movie.get("title") or "").strip()
        year = movie.get("year")
        clean = _clean_title(title)
        poster_src = cache.get_setting(poster_key(title, year), "")
        if not poster_src and year:
            poster_src = cache.get_setting(poster_key(title), "")
        backdrop_src = cache.get_setting(backdrop_key(title, year), "")

        rating_meta = _parse_cached_meta(
            cache.get_setting(f"rating_v2_{clean}_{year}", "")
            or (cache.get_setting(f"rating_v2_{clean}", "") if year else "")
        )
        if not poster_src:
            poster_src = str(rating_meta.get("poster_url") or "")
        if not backdrop_src:
            backdrop_src = str(rating_meta.get("backdrop_url") or "")

        banner_src = cache.get_setting(f"banner_fid_{clean}_{year}", "") if year else ""
        if not banner_src:
            banner_src = cache.get_setting(f"banner_fid_{clean}", "")

        # TMDb poster before banner: banner_fid usually stores a 16:9 backdrop,
        # which crops badly into the 2:3 hero slot.
        if not poster_src and tmdb_service is not None:
            try:
                meta = tmdb_service.search_movie(title, year) or {}
                poster_src = str(meta.get("poster_url") or "")
                if not backdrop_src:
                    backdrop_src = str(meta.get("backdrop_url") or "")
            except Exception as exc:
                logger.debug("TMDb poster fallback failed for %s: %s", title, exc)

        if not poster_src and banner_src.startswith(("http://", "https://")):
            poster_src = banner_src
        if not backdrop_src and banner_src.startswith(("http://", "https://")):
            backdrop_src = banner_src

        if poster_src:
            cache.set_setting(poster_key(title, year), poster_src)
        if backdrop_src:
            cache.set_setting(backdrop_key(title, year), backdrop_src)

        assets.append({
            "title": title,
            "year": year,
            "message_id": movie.get("message_id"),
            "rating": movie.get("rating"),
            "quality": _quality_label(movie),
            "poster_url": poster_src,
            "poster": _local_image_bytes(poster_src),
            "backdrop": _local_image_bytes(backdrop_src) if backdrop_src else None,
        })
    return assets


def build_homepage_caption(
    movies: List[Dict[str, Any]],
    channel_username: str,
    total: int,
    schedule: Optional[List[Tuple[str, str]]] = None,
    channel_title: str = "FILM INDONESIA",
    subtitle: str = "Pusat Film Indonesia",
    now: Optional[datetime.datetime] = None,
) -> str:
    """Build a photo caption no longer than Telegram's 1024-character limit."""
    clean_channel = (channel_username or "").lstrip("@").strip()
    current = now or datetime.datetime.now(WIB)
    date_label = f"{current.day:02d} {MONTHS_ID[current.month]} {current.year}"

    header = (
        f"🎬 <b>{html.escape(channel_title)}</b> · "
        f"<i>{html.escape(subtitle)}</i>\n"
        f"📊 <b>{int(total)} film</b> · Update {date_label}"
    )
    footer = "📌 <i>Katalog A-Z lengkap ada di tombol di bawah.</i>"

    def compose(title_limit: int, with_schedule: bool) -> str:
        lines = [header, "", "🆕 <b>Rilis terbaru</b>"]
        for index, movie in enumerate(movies[:5], 1):
            label = html.escape(_short(_title_with_year(movie), title_limit))
            message_id = movie.get("message_id")
            if message_id and clean_channel:
                label = f'<a href="https://t.me/{clean_channel}/{int(message_id)}">{label}</a>'
            quality = _short(html.escape(_quality_label(movie)), 20)
            suffix = f" · {quality}" if quality else ""
            lines.append(f"{index}. {label}{suffix}")

        if with_schedule and schedule:
            slots = " · ".join(
                f"{html.escape(str(time_label))} {html.escape(_short(str(name), 34))}"
                for time_label, name in schedule[:2]
            )
            lines.extend(["", f"🗓️ <b>Hari ini</b> · {slots}"])

        lines.extend(["", footer])
        return "\n".join(lines)

    for limit in (70, 52, 40, 30):
        for with_schedule in (True, False):
            caption = compose(limit, with_schedule)
            if len(caption) <= CAPTION_LIMIT:
                return caption

    # Last resort: keep the header, five links and the footer, with very short titles.
    return compose(18, False)[:CAPTION_LIMIT]


def build_homepage_keyboard(
    channel_username: str,
    total: int,
    telegraph_url: str = "",
    bot_username: str = "",
    request_url: str = "",
    search_url: str = "",
):
    """Catalog / search / request keyboard for the pinned post."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    clean_channel = (channel_username or "").lstrip("@").strip()
    rows = []
    if telegraph_url:
        button = InlineKeyboardButton(
            f"⚡ BUKA KATALOG A-Z ({int(total)} Film)",
            url=telegraph_url,
        )
        button.style = "primary"
        rows.append([button])

    if not search_url:
        search_url = (
            f"https://t.me/{bot_username}?start=cari"
            if bot_username else f"https://t.me/{clean_channel}"
        )
    search_button = InlineKeyboardButton("🔍 Cari Film", url=search_url)
    search_button.style = "success"

    if request_url and request_url != "off":
        request_button = InlineKeyboardButton("💬 Request Film", url=request_url)
        request_button.style = "danger"
        rows.append([search_button, request_button])
    else:
        rows.append([search_button])

    return InlineKeyboardMarkup(rows)


def homepage_signature(
    channel_username: str,
    assets: List[Dict[str, Any]],
    total: int,
    now: Optional[datetime.datetime] = None,
) -> str:
    clean_channel = (channel_username or "").lstrip("@").strip().lower()
    current = now or datetime.datetime.now(WIB)
    date_key = current.strftime("%Y-%m-%d")
    parts = [clean_channel, str(int(total)), date_key]
    for movie in assets[:5]:
        parts.append(
            "|".join([
                str(movie.get("title") or ""),
                str(movie.get("year") or ""),
                str(movie.get("message_id") or ""),
                str(movie.get("rating") or ""),
                str(movie.get("quality") or ""),
                str(movie.get("poster_url") or ""),
                "1" if movie.get("poster") else "0",
            ])
        )
    return hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()


def _fit_rounded(image: Image.Image, size: Tuple[int, int], radius: int) -> Tuple[Image.Image, Image.Image]:
    fitted = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255
    )
    rounded = Image.new("RGBA", size, (0, 0, 0, 0))
    rounded.paste(fitted, (0, 0), mask)
    return rounded, mask


def _placeholder(size: Tuple[int, int], title: str) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (12, 20, 32, 255))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = int(16 + 22 * (y / max(1, height)))
        draw.line([(0, y), (width, y)], fill=(shade, shade + 6, shade + 16, 255))
    initials = "".join(word[0] for word in (title or "FILM").split()[:2]).upper() or "F"
    font = _get_font(max(26, width // 4), bold=True)
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(
        ((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2 - box[1]),
        initials,
        font=font,
        fill=(148, 163, 184, 255),
    )
    return image


def _shadow(canvas: Image.Image, box: Tuple[int, int, int, int], radius: int, blur: int, alpha: int) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        [x0 + 8, y0 + 12, x1 + 8, y1 + 12], radius=radius, fill=(0, 0, 0, alpha)
    )
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _badge(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str,
           font, background=(56, 189, 248, 235), foreground=(7, 12, 20, 255),
           padding=(12, 6), radius=8) -> None:
    x, y = xy
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0] + padding[0] * 2
    height = box[3] - box[1] + padding[1] * 2
    draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, fill=background)
    draw.text((x + padding[0], y + padding[1] - 1), text, font=font, fill=foreground)


class HomepageRenderer:
    """Renders the pinned visual homepage as a 1280x720 JPEG."""

    def render(
        self,
        assets: List[Dict[str, Any]],
        channel_username: str,
        total: int,
        output_path: str,
        channel_title: str = "FILM INDONESIA",
        subtitle: str = "Pusat Film Indonesia",
        now: Optional[datetime.datetime] = None,
    ) -> str:
        clean_channel = (channel_username or "").lstrip("@").strip()
        current = now or datetime.datetime.now(WIB)
        canvas = Image.new("RGBA", (WIDTH, HEIGHT), (7, 10, 18, 255))

        first = assets[0] if assets else {}
        background_bytes = first.get("backdrop") or first.get("poster")
        background_image = _load_image(background_bytes) if background_bytes else None
        if background_image:
            canvas = ImageOps.fit(
                background_image, (WIDTH, HEIGHT), Image.Resampling.LANCZOS
            ).filter(ImageFilter.GaussianBlur(22)).convert("RGBA")

        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        for x in range(WIDTH):
            alpha = int(205 + 35 * (1 - x / WIDTH))
            draw_overlay.line([(x, 0), (x, HEIGHT)], fill=(7, 10, 18, alpha))
        for y in range(HEIGHT):
            alpha = int(90 * max(0, (y - 380) / 340))
            if alpha:
                draw_overlay.line([(0, y), (WIDTH, y)], fill=(3, 6, 12, alpha))
        canvas.alpha_composite(overlay)
        draw = ImageDraw.Draw(canvas)

        draw.rectangle([56, 56, 64, 664], fill=(56, 189, 248, 255))

        hero_box = (88, 90, 448, 630)
        _shadow(canvas, hero_box, 18, 24, 170)
        hero_image = _load_image(first.get("poster")) if first.get("poster") else None
        hero_image = hero_image or _placeholder((360, 540), str(first.get("title") or "FILM"))
        hero_poster, _ = _fit_rounded(hero_image, (360, 540), 18)
        canvas.alpha_composite(hero_poster, (hero_box[0], hero_box[1]))
        draw.rounded_rectangle(hero_box, radius=18, outline=(255, 255, 255, 55), width=2)

        _badge(draw, (104, 106), "1", _get_font(20, bold=True))
        _badge(draw, (104, 146), "BARU", _get_font(16, bold=True),
               (245, 158, 11, 245), (20, 12, 2, 255))

        hero_rating = _rating_label(first.get("rating"))
        if hero_rating:
            rating_text = f"★ {hero_rating}"
            font_rating = _get_font(20, bold=True)
            box = draw.textbbox((0, 0), rating_text, font=font_rating)
            pill_width = box[2] - box[0] + 28
            draw.rounded_rectangle(
                [104, 560, 104 + pill_width, 598], radius=19,
                fill=(15, 23, 42, 225), outline=(245, 158, 11, 230), width=2,
            )
            draw.text((118, 568), rating_text, font=font_rating, fill=(251, 191, 36, 255))

        hero_quality = _short(str(first.get("quality") or ""), 12)
        if hero_quality:
            _badge(draw, (hero_box[2] - 108, 566), hero_quality, _get_font(15, bold=True),
                   (15, 23, 42, 225), (230, 240, 255, 255))

        draw.text((500, 82), _short(channel_title.upper(), 28), font=_get_font(16, bold=True),
                  fill=(56, 189, 248, 255))
        draw.text((500, 110), "KOLEKSI TERBARU", font=_get_font(40, bold=True),
                  fill=(255, 255, 255, 255))
        latest_label = (
            f"{len(assets)} film terbaru minggu ini" if len(assets) >= 5
            else f"{len(assets)} film terbaru"
        )
        draw.text((500, 158), latest_label, font=_get_font(18, bold=False),
                  fill=(148, 163, 184, 255))
        draw.line([500, 196, 838, 196], fill=(56, 189, 248, 110), width=2)

        grid = assets[1:5]
        grid_positions = [(500, 216), (672, 216), (500, 474), (672, 474)]
        grid_size = (154, 232)
        for index, movie in enumerate(grid):
            box_x, box_y = grid_positions[index]
            _shadow(canvas, (box_x, box_y, box_x + grid_size[0], box_y + grid_size[1]),
                    12, 12, 120)
            image = _load_image(movie.get("poster")) if movie.get("poster") else None
            image = image or _placeholder(grid_size, str(movie.get("title") or "FILM"))
            poster, _ = _fit_rounded(image, grid_size, 12)
            canvas.alpha_composite(poster, (box_x, box_y))
            draw.rounded_rectangle(
                [box_x, box_y, box_x + grid_size[0], box_y + grid_size[1]],
                radius=12, outline=(255, 255, 255, 45), width=1,
            )
            _badge(draw, (box_x + 8, box_y + 8), str(index + 2), _get_font(15, bold=True),
                   (7, 12, 20, 220), (255, 255, 255, 255), padding=(8, 4), radius=6)
            rating = _rating_label(movie.get("rating"))
            if rating:
                draw.rounded_rectangle(
                    [box_x + 8, box_y + grid_size[1] - 30,
                     box_x + 66, box_y + grid_size[1] - 8],
                    radius=8, fill=(7, 12, 20, 215),
                )
                draw.text((box_x + 16, box_y + grid_size[1] - 28), f"★ {rating}",
                          font=_get_font(12, bold=True), fill=(251, 191, 36, 255))

        if grid:
            panel = (862, 216, 1224, 474)
        else:
            panel = (500, 216, 1224, 474)
        draw.rounded_rectangle(panel, radius=18, fill=(10, 16, 28, 195),
                               outline=(56, 189, 248, 80), width=1)
        panel_x = panel[0] + 28
        draw.text((panel_x, 244), str(int(total)), font=_get_font(76, bold=True),
                  fill=(255, 255, 255, 255))
        draw.text((panel_x + 2, 326), _short(channel_title.upper(), 24),
                  font=_get_font(16, bold=True), fill=(56, 189, 248, 255))
        draw.line([panel_x + 2, 358, panel[2] - 28, 358], fill=(255, 255, 255, 35), width=1)
        draw.text((panel_x + 2, 376), "UPDATE", font=_get_font(13, bold=True),
                  fill=(148, 163, 184, 255))
        date_label = f"{current.day:02d} {MONTHS_ID[current.month]} {current.year}".upper()
        draw.text((panel_x + 2, 396), date_label, font=_get_font(20, bold=True),
                  fill=(241, 245, 249, 255))
        draw.text((panel_x + 2, 434), f"t.me/{clean_channel}", font=_get_font(15, bold=True),
                  fill=(186, 230, 253, 255))

        draw.line([88, 648, 448, 648], fill=(255, 255, 255, 30), width=1)
        draw.text((88, 662), _short(subtitle.upper(), 30), font=_get_font(15, bold=True),
                  fill=(186, 230, 253, 255))
        draw.text((88, 686), "KUALITAS HD  •  UPDATE BERKALA", font=_get_font(13, bold=False),
                  fill=(100, 116, 139, 255))

        output = canvas.convert("RGB")
        output.save(output_path, quality=90, optimize=True)
        return output_path
