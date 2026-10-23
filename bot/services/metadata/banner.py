import io
import logging
import os
import re
import urllib.request
from typing import Any, Dict, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# Standard available TrueType fonts on Linux systems
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
FONT_REGULAR_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def _get_font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    paths = FONT_PATHS if bold else FONT_REGULAR_PATHS
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _load_image(source: Union[str, bytes, Image.Image]) -> Optional[Image.Image]:
    """Safely loads an image from a filepath, URL, bytes, or returns the Image directly."""
    if not source:
        return None
    if isinstance(source, Image.Image):
        return source.convert("RGBA")
    try:
        if isinstance(source, bytes):
            return Image.open(io.BytesIO(source)).convert("RGBA")
        if isinstance(source, str):
            if source.startswith("http://") or source.startswith("https://"):
                req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    data = resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
            elif os.path.exists(source):
                return Image.open(source).convert("RGBA")
    except Exception as e:
        logger.debug(f"Failed to load image from source: {e}")
    return None


class BannerGenerator:
    """Generates 1280x720 cinematic promotional movie banners for Telegram channels.
    100% offline, zero-cost, high aesthetic quality."""

    WIDTH = 1280
    HEIGHT = 720

    def __init__(self):
        self.font_title = _get_font(40, bold=True)
        self.font_subtitle = _get_font(22, bold=True)
        self.font_label = _get_font(18, bold=True)
        self.font_body = _get_font(18, bold=False)
        self.font_pill = _get_font(16, bold=True)
        self.font_badge = _get_font(15, bold=True)
        self.font_card_tag = _get_font(14, bold=True)
        self.font_card_wm = _get_font(30, bold=True)
        self.font_card_sub = _get_font(17, bold=False)

    def create_banner(
        self,
        metadata: Dict[str, Any],
        poster_source: Optional[Union[str, bytes, Image.Image]] = None,
        watermark: str = "@film_indonesia1",
        output_path: Optional[str] = None
    ) -> Image.Image:
        """Composes a high-definition cinematic promotional banner with dedicated channel watermark showcase."""
        title = (metadata.get("title") or "FILM INDONESIA").strip().upper()
        year = metadata.get("year")
        rating = metadata.get("rating")
        genre = metadata.get("genre")
        director = metadata.get("director")
        actors = metadata.get("actors")
        res = metadata.get("resolution") or "1080p"
        src = metadata.get("source") or "WEB-DL"
        ac = metadata.get("audioCodec") or "AAC"
        duration = metadata.get("duration")
        wm = (watermark or "@film_indonesia1").strip()
        clean_wm = wm.lstrip("@").strip()
        channel_url = f"https://t.me/{clean_wm}" if clean_wm else "https://t.me"

        # 1. Load Poster & Backdrop Image
        poster_img = _load_image(poster_source or metadata.get("poster_url"))
        backdrop_img = _load_image(metadata.get("backdrop_url")) if metadata.get("backdrop_url") else None
        bg_source = backdrop_img or poster_img

        # 2. Base Canvas & Cinematic Atmospheric Background
        canvas = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (12, 14, 20, 255))
        if bg_source:
            pw, ph = bg_source.size
            scale = max(self.WIDTH / pw, self.HEIGHT / ph)
            nw, nh = int(pw * scale), int(ph * scale)
            bg = bg_source.resize((nw, nh), Image.Resampling.LANCZOS)
            left = (nw - self.WIDTH) // 2
            top = (nh - self.HEIGHT) // 2
            bg = bg.crop((left, top, left + self.WIDTH, top + self.HEIGHT))
            bg = bg.filter(ImageFilter.GaussianBlur(radius=18))
            canvas.paste(bg, (0, 0))

        # 3. Apply Multi-Stage Film Vignette & Horizontal Contrast Gradient
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        # Horizontal gradient: Darker on left (under poster/text) transitioning smoothly
        for x in range(self.WIDTH):
            if x < 480:
                alpha = int(210 + (1.0 - x / 480.0) * 35)  # 245 -> 210 on left
            else:
                progress = (x - 480) / float(self.WIDTH - 480)
                alpha = int(210 - progress * 80)          # 210 -> 130 on right
            draw_ov.line([(x, 0), (x, self.HEIGHT)], fill=(8, 10, 16, alpha))

        # Subtle vertical vignette (top & bottom edges)
        for y in range(80):
            top_a = int(140 * (1.0 - y / 80.0))
            draw_ov.line([(0, y), (self.WIDTH, y)], fill=(5, 6, 10, top_a))
            bot_y = self.HEIGHT - 1 - y
            bot_a = int(160 * (1.0 - y / 80.0))
            draw_ov.line([(0, bot_y), (self.WIDTH, bot_y)], fill=(5, 6, 10, bot_a))

        canvas = Image.alpha_composite(canvas, overlay)
        draw = ImageDraw.Draw(canvas)

        # 4. Render Floating 3D Poster (Left Side)
        poster_x = 60
        poster_y = 55
        poster_w = 390
        poster_h = 610

        if poster_img:
            pw, ph = poster_img.size
            p_scale = min(poster_w / pw, poster_h / ph)
            fit_w, fit_h = int(pw * p_scale), int(ph * p_scale)
            fitted_poster = poster_img.resize((fit_w, fit_h), Image.Resampling.LANCZOS)

            draw_px = poster_x + (poster_w - fit_w) // 2
            draw_py = poster_y + (poster_h - fit_h) // 2

            # Realistic Multi-Layer Floating Drop Shadow
            for s_rad, s_alpha in [(22, 110), (12, 160), (4, 210)]:
                shadow = Image.new("RGBA", (fit_w + s_rad * 2, fit_h + s_rad * 2), (0, 0, 0, 0))
                s_draw = ImageDraw.Draw(shadow)
                s_draw.rounded_rectangle([s_rad, s_rad + 6, fit_w + s_rad, fit_h + s_rad + 6], radius=18, fill=(0, 0, 0, s_alpha))
                shadow = shadow.filter(ImageFilter.GaussianBlur(radius=s_rad // 2))
                canvas.paste(shadow, (draw_px - s_rad, draw_py - s_rad), shadow)

            # Rounded poster mask with subtle corner radius
            mask = Image.new("L", (fit_w, fit_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, fit_w, fit_h], radius=16, fill=255)
            canvas.paste(fitted_poster, (draw_px, draw_py), mask)

            # Elegant Sleek Glass Border
            draw.rounded_rectangle(
                [draw_px, draw_py, draw_px + fit_w, draw_py + fit_h],
                radius=16,
                outline=(255, 255, 255, 65),
                width=2
            )

            # Top Rated Pill Badge on poster if rating >= 7.0
            r_num = 0.0
            if rating:
                m_r = re.search(r"([\d\.]+)", str(rating))
                if m_r:
                    try:
                        r_num = float(m_r.group(1))
                    except ValueError:
                        pass
            if r_num >= 7.0:
                ribbon_txt = "★ POPULAR" if r_num < 8.0 else "★ TOP RATED"
                r_box = draw.textbbox((0, 0), ribbon_txt, font=self.font_pill)
                rw = r_box[2] - r_box[0] + 20
                rh = 28
                rx0 = draw_px + 14
                ry0 = draw_py + 14
                draw.rounded_rectangle([rx0, ry0, rx0 + rw, ry0 + rh], radius=6, fill=(180, 83, 9, 230), outline=(245, 158, 11, 240), width=1)
                draw.text((rx0 + 10, ry0 + 5), ribbon_txt, fill=(255, 251, 235), font=self.font_pill)
        else:
            draw.rounded_rectangle(
                [poster_x, poster_y, poster_x + poster_w, poster_y + poster_h],
                radius=18,
                fill=(18, 22, 32, 230),
                outline=(255, 255, 255, 45),
                width=2
            )
            draw.text(
                (poster_x + poster_w // 2, poster_y + poster_h // 2),
                "FILM INDONESIA",
                fill=(180, 195, 220),
                font=self.font_subtitle,
                anchor="mm"
            )

        # 5. Right Info Section (x = 490 to 1220)
        info_x = 490
        curr_y = 55

        # Top Header Bar: Premiere Tag (Left) + Frosted Glass Watermark Badge (Right)
        top_tag = "CINEMA PREMIERE  •  INDONESIA"
        t_box = draw.textbbox((0, 0), top_tag, font=self.font_pill)
        tw = t_box[2] - t_box[0] + 24
        th = 30
        draw.rounded_rectangle(
            [info_x, curr_y, info_x + tw, curr_y + th],
            radius=15,
            fill=(30, 41, 59, 180),
            outline=(56, 189, 248, 160),
            width=1
        )
        draw.text((info_x + 12, curr_y + 6), top_tag, fill=(186, 230, 253), font=self.font_pill)

        # Frosted Glass Watermark Pill on the far right
        wm_label = wm.upper()
        wm_box = draw.textbbox((0, 0), wm_label, font=self.font_subtitle)
        wm_w = wm_box[2] - wm_box[0] + 28
        wm_h = 36
        wm_x0 = self.WIDTH - wm_w - 60
        wm_y0 = curr_y - 3
        draw.rounded_rectangle(
            [wm_x0, wm_y0, wm_x0 + wm_w, wm_y0 + wm_h],
            radius=18,
            fill=(15, 23, 42, 210),
            outline=(14, 165, 233, 200),
            width=2
        )
        draw.text((wm_x0 + 14, wm_y0 + 6), wm_label, fill=(240, 249, 255), font=self.font_subtitle)

        curr_y += th + 18

        # Title (Big Bold with subtle text shadow, smart line break)
        title_lines = []
        words = title.split()
        current_line = []
        for w in words:
            test_line = " ".join(current_line + [w])
            bbox = draw.textbbox((0, 0), test_line, font=self.font_title)
            if (bbox[2] - bbox[0]) > 680:
                if current_line:
                    title_lines.append(" ".join(current_line))
                    current_line = [w]
                else:
                    title_lines.append(w)
                    current_line = []
            else:
                current_line.append(w)
        if current_line:
            title_lines.append(" ".join(current_line))

        for tl in title_lines[:2]:
            # Soft shadow
            draw.text((info_x + 2, curr_y + 2), tl, fill=(0, 0, 0, 180), font=self.font_title)
            draw.text((info_x, curr_y), tl, fill=(255, 255, 255), font=self.font_title)
            curr_y += 46
        curr_y += 2

        # Sub-header: Year, Duration, Country & Rating Pill
        meta_items = []
        if year:
            meta_items.append(str(year))
        if duration:
            meta_items.append(str(duration))
        meta_items.append("Indonesia")

        sub_text = "   •   ".join(meta_items)
        draw.text((info_x, curr_y + 4), sub_text, fill=(186, 202, 224), font=self.font_subtitle)

        # Rating Badge (Pill)
        if rating:
            clean_rating = str(rating).replace("• IMDb", "").replace("IMDb", "").replace("• TMDb", "").replace("TMDb", "").strip()
            r_str = f"★ {clean_rating}"
            r_box = draw.textbbox((0, 0), r_str, font=self.font_subtitle)
            rw = r_box[2] - r_box[0] + 24
            rh = 32
            rx = info_x + draw.textbbox((0, 0), sub_text, font=self.font_subtitle)[2] + 24
            if rx + rw < self.WIDTH - 60:
                draw.rounded_rectangle([rx, curr_y, rx + rw, curr_y + rh], radius=16, fill=(45, 30, 5, 220), outline=(245, 158, 11, 220), width=1)
                draw.text((rx + 12, curr_y + 4), r_str, fill=(251, 191, 36), font=self.font_subtitle)

        curr_y += 42

        # Metadata Specs (Genre, Sutradara, Pemeran)
        if genre:
            draw.text((info_x, curr_y), "GENRE", fill=(56, 189, 248), font=self.font_label)
            genre_val = str(genre)[:46] + ("..." if len(str(genre)) > 46 else "")
            draw.text((info_x + 130, curr_y), genre_val, fill=(241, 245, 249), font=self.font_body)
            curr_y += 30

        if director:
            draw.text((info_x, curr_y), "SUTRADARA", fill=(56, 189, 248), font=self.font_label)
            dir_val = str(director)[:42] + ("..." if len(str(director)) > 42 else "")
            draw.text((info_x + 130, curr_y), dir_val, fill=(241, 245, 249), font=self.font_body)
            curr_y += 30

        if actors:
            draw.text((info_x, curr_y), "PEMERAN", fill=(56, 189, 248), font=self.font_label)
            act_val = str(actors)[:42] + ("..." if len(str(actors)) > 42 else "")
            draw.text((info_x + 130, curr_y), act_val, fill=(241, 245, 249), font=self.font_body)
            curr_y += 32

        # Quality & Tech Badges (Pills)
        badges = []
        if res:
            res_label = "2160p 4K UHD" if res == "2160p" else ("1080p Full HD" if res == "1080p" else res)
            badges.append((res_label, (14, 165, 233)))   # Sky Blue
        audio_preset = metadata.get("audio") or ac
        if audio_preset:
            badges.append((str(audio_preset).upper(), (16, 185, 129))) # Emerald
        sub_preset = metadata.get("subtitle")
        if sub_preset:
            badges.append((str(sub_preset).upper(), (139, 92, 246)))   # Purple
        if src:
            badges.append((str(src).upper(), (100, 116, 139)))        # Slate

        badge_x = info_x
        curr_y += 4
        for b_text, b_col in badges[:4]:
            b_box = draw.textbbox((0, 0), b_text, font=self.font_badge)
            bw = b_box[2] - b_box[0] + 24
            bh = 28
            if badge_x + bw > self.WIDTH - 60:
                break
            draw.rounded_rectangle(
                [badge_x, curr_y, badge_x + bw, curr_y + bh],
                radius=8,
                fill=(b_col[0], b_col[1], b_col[2], 65),
                outline=(b_col[0], b_col[1], b_col[2], 210),
                width=1
            )
            draw.text((badge_x + 12, curr_y + 5), b_text, fill=(255, 255, 255), font=self.font_badge)
            badge_x += bw + 12

        # 6. Sleek Modern Bottom Branding Bar (Apple TV / Streaming style)
        bar_y0 = 600
        bar_y1 = 665
        bar_x0 = info_x
        bar_x1 = self.WIDTH - 60

        draw.rounded_rectangle(
            [bar_x0, bar_y0, bar_x1, bar_y1],
            radius=14,
            fill=(15, 23, 42, 220),
            outline=(56, 189, 248, 90),
            width=1
        )

        draw.text(
            (bar_x0 + 20, bar_y0 + 13),
            "▶️ TAYANG EKSKLUSIF DI TELEGRAM",
            fill=(56, 189, 248),
            font=self.font_pill
        )
        draw.text(
            (bar_x0 + 20, bar_y0 + 36),
            "Koleksi Film Indonesia Terlengkap & Kualitas Terbaik",
            fill=(148, 163, 184),
            font=self.font_badge
        )

        cta_link = f"t.me/{clean_wm}"
        c_box = draw.textbbox((0, 0), cta_link, font=self.font_subtitle)
        cw = c_box[2] - c_box[0]
        draw.text(
            (bar_x1 - cw - 20, bar_y0 + 20),
            cta_link,
            fill=(248, 250, 252),
            font=self.font_subtitle
        )

        # 7. Convert to RGB and Save / Return
        final_rgb = canvas.convert("RGB")
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            final_rgb.save(output_path, format="JPEG", quality=92, optimize=True)
        return final_rgb
