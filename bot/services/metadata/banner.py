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
        self.font_title = _get_font(42, bold=True)
        self.font_subtitle = _get_font(24, bold=True)
        self.font_body = _get_font(20, bold=False)
        self.font_pill = _get_font(18, bold=True)
        self.font_badge = _get_font(16, bold=True)

    def create_banner(
        self,
        metadata: Dict[str, Any],
        poster_source: Optional[Union[str, bytes, Image.Image]] = None,
        watermark: str = "@film_indonesia1",
        output_path: Optional[str] = None
    ) -> Image.Image:
        """Composes a high-definition cinematic promotional banner."""
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

        # 1. Load Poster Image
        poster_img = _load_image(poster_source)

        # 2. Create Base Canvas & Cinematic Blurred Background
        canvas = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (15, 18, 25, 255))
        if poster_img:
            # Crop to cover canvas
            pw, ph = poster_img.size
            scale = max(self.WIDTH / pw, self.HEIGHT / ph)
            nw, nh = int(pw * scale), int(ph * scale)
            bg = poster_img.resize((nw, nh), Image.Resampling.LANCZOS)
            # Center crop
            left = (nw - self.WIDTH) // 2
            top = (nh - self.HEIGHT) // 2
            bg = bg.crop((left, top, left + self.WIDTH, top + self.HEIGHT))
            # Blur
            bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
            canvas.paste(bg, (0, 0))

        # 3. Apply Dark Cinematic Vignette & Gradient Overlays
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        # Deep dark gradient from left to right (darker on right for text legibility)
        for x in range(self.WIDTH):
            alpha = int(140 + (x / self.WIDTH) * 95)
            draw_ov.line([(x, 0), (x, self.HEIGHT)], fill=(10, 13, 20, alpha))
        canvas = Image.alpha_composite(canvas, overlay)

        draw = ImageDraw.Draw(canvas)

        # 4. Render Poster Box (Left Side)
        poster_x = 70
        poster_y = 70
        poster_w = 380
        poster_h = 580

        if poster_img:
            # Scale poster to fit 380x580 preserving aspect ratio
            pw, ph = poster_img.size
            p_scale = min(poster_w / pw, poster_h / ph)
            fit_w, fit_h = int(pw * p_scale), int(ph * p_scale)
            fitted_poster = poster_img.resize((fit_w, fit_h), Image.Resampling.LANCZOS)

            # Center inside poster frame box
            draw_px = poster_x + (poster_w - fit_w) // 2
            draw_py = poster_y + (poster_h - fit_h) // 2

            # Drop shadow
            shadow = Image.new("RGBA", (fit_w + 30, fit_h + 30), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([10, 10, fit_w + 20, fit_h + 20], radius=16, fill=(0, 0, 0, 180))
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
            canvas.paste(shadow, (draw_px - 5, draw_py - 5), shadow)

            # Rounded poster mask
            mask = Image.new("L", (fit_w, fit_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, fit_w, fit_h], radius=14, fill=255)

            canvas.paste(fitted_poster, (draw_px, draw_py), mask)

            # Sleek Border around poster
            draw.rounded_rectangle(
                [draw_px, draw_py, draw_px + fit_w, draw_py + fit_h],
                radius=14,
                outline=(255, 255, 255, 60),
                width=2
            )
        else:
            # Fallback stylized placeholder box
            draw.rounded_rectangle(
                [poster_x, poster_y, poster_x + poster_w, poster_y + poster_h],
                radius=16,
                fill=(22, 27, 38, 220),
                outline=(255, 255, 255, 40),
                width=2
            )
            draw.text(
                (poster_x + poster_w // 2, poster_y + poster_h // 2 - 20),
                "🎬",
                fill=(255, 255, 255, 200),
                font=self.font_title,
                anchor="mm"
            )
            draw.text(
                (poster_x + poster_w // 2, poster_y + poster_h // 2 + 30),
                "FILM INDONESIA",
                fill=(160, 175, 200),
                font=self.font_pill,
                anchor="mm"
            )

        # 5. Render Info Section (Right Side)
        info_x = 490
        curr_y = 80

        # Channel Pill (Top of right side)
        wm_text = f"🍿 {wm}"
        wm_bbox = draw.textbbox((0, 0), wm_text, font=self.font_pill)
        wm_w = wm_bbox[2] - wm_bbox[0] + 28
        wm_h = 36
        draw.rounded_rectangle(
            [info_x, curr_y, info_x + wm_w, curr_y + wm_h],
            radius=18,
            fill=(255, 255, 255, 22),
            outline=(255, 255, 255, 45),
            width=1
        )
        draw.text((info_x + 14, curr_y + 7), wm_text, fill=(240, 245, 255), font=self.font_pill)
        curr_y += wm_h + 24

        # Title (Big Bold, with smart wrap)
        title_lines = []
        words = title.split()
        current_line = []
        for w in words:
            test_line = " ".join(current_line + [w])
            bbox = draw.textbbox((0, 0), test_line, font=self.font_title)
            if (bbox[2] - bbox[0]) > 700:
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

        # Max 2 lines for title
        for i, tl in enumerate(title_lines[:2]):
            draw.text((info_x, curr_y), tl, fill=(255, 255, 255), font=self.font_title)
            curr_y += 48
        curr_y += 6

        # Year & Duration Line
        meta_sub_parts = []
        if year:
            meta_sub_parts.append(f"🗓️ {year}")
        if duration:
            meta_sub_parts.append(f"⏱️ {duration}")
        if meta_sub_parts:
            sub_str = "   •   ".join(meta_sub_parts)
            draw.text((info_x, curr_y), sub_str, fill=(175, 195, 220), font=self.font_subtitle)
            curr_y += 38

        # Rating
        if rating:
            clean_rating = str(rating).replace("• IMDb", "").strip()
            draw.text((info_x, curr_y), f"⭐ {clean_rating} • IMDb", fill=(255, 205, 55), font=self.font_subtitle)
            curr_y += 38

        # Genre
        if genre:
            genre_disp = f"🎭 {genre}"
            if len(genre_disp) > 45:
                genre_disp = genre_disp[:42] + "..."
            draw.text((info_x, curr_y), genre_disp, fill=(220, 228, 240), font=self.font_body)
            curr_y += 34

        # Director
        if director:
            dir_disp = f"🎬 Sutradara : {director}"
            if len(dir_disp) > 48:
                dir_disp = dir_disp[:45] + "..."
            draw.text((info_x, curr_y), dir_disp, fill=(185, 195, 210), font=self.font_body)
            curr_y += 32

        # Actors
        if actors:
            act_disp = f"👥 Pemeran : {actors}"
            if len(act_disp) > 48:
                act_disp = act_disp[:45] + "..."
            draw.text((info_x, curr_y), act_disp, fill=(185, 195, 210), font=self.font_body)
            curr_y += 36

        # Divider Line
        curr_y += 10
        draw.line([(info_x, curr_y), (info_x + 690, curr_y)], fill=(255, 255, 255, 30), width=1)
        curr_y += 24

        # Quality & Tech Badges (Pills)
        badges = []
        if res:
            res_label = "1080p Full HD" if res == "1080p" else ("2160p 4K" if res == "2160p" else res)
            badges.append((f"🎞️ {res_label}", (40, 160, 240)))
        if src:
            badges.append((f"📡 {src}", (70, 80, 100)))
        if ac:
            badges.append((f"🔊 {ac}", (70, 80, 100)))

        badge_x = info_x
        for b_text, b_col in badges:
            b_box = draw.textbbox((0, 0), b_text, font=self.font_badge)
            bw = b_box[2] - b_box[0] + 24
            bh = 32
            draw.rounded_rectangle(
                [badge_x, curr_y, badge_x + bw, curr_y + bh],
                radius=10,
                fill=(b_col[0], b_col[1], b_col[2], 50),
                outline=(b_col[0], b_col[1], b_col[2], 180),
                width=1
            )
            draw.text((badge_x + 12, curr_y + 7), b_text, fill=(255, 255, 255), font=self.font_badge)
            badge_x += bw + 14

        # 6. Save or return image
        final_rgb = canvas.convert("RGB")
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            final_rgb.save(output_path, format="JPEG", quality=92, optimize=True)
        return final_rgb
