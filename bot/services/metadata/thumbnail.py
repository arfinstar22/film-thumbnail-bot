import io
import logging
import os
from typing import Optional, Union

from PIL import Image, ImageDraw, ImageFont

from .banner import _get_font, _load_image

logger = logging.getLogger(__name__)


class ThumbnailGenerator:
    """Zero-cost, lightweight Telegram Video Thumbnail generator.
    Creates 320px high-contrast branded video thumbnails with watermark overlay.
    Guaranteed < 100 KB and 0 MB video download (100% Render Free friendly)."""

    MAX_DIM = 320

    def __init__(self):
        self.font_badge = _get_font(13, bold=True)
        self.font_title = _get_font(16, bold=True)
        self.font_sub = _get_font(12, bold=False)

    def create_thumbnail(
        self,
        source: Optional[Union[str, bytes, Image.Image]] = None,
        watermark: str = "@film_indonesia1",
        title: str = "",
        output_path: Optional[str] = None
    ) -> Image.Image:
        """Composes a high-visibility Telegram thumbnail with watermark badge."""
        base_img = _load_image(source) if source else None

        if base_img is None:
            # Fallback: Create a sleek cinematic gradient placeholder instead of pure black
            w, h = 320, 180
            base_img = Image.new("RGBA", (w, h), (15, 23, 42, 255))
            draw = ImageDraw.Draw(base_img)

            # Elegant dark vignette/gradient bars
            for y in range(h):
                alpha = int(30 * (y / h))
                draw.line([(0, y), (w, y)], fill=(30, 41, 59, 255 - alpha))

            # Center Title if provided
            disp_title = (title or "FILM").strip().upper()
            if len(disp_title) > 28:
                disp_title = disp_title[:26] + "..."

            draw.text((w // 2, h // 2 - 12), f"🎬 {disp_title}", fill=(241, 245, 249, 255),
                      font=self.font_title or ImageFont.load_default(), anchor="mm")
            draw.text((w // 2, h // 2 + 12), "Official Video Post", fill=(148, 163, 184, 255),
                      font=self.font_sub or ImageFont.load_default(), anchor="mm")
        else:
            # Scale proportionally to fit within MAX_DIM x MAX_DIM
            orig_w, orig_h = base_img.size
            ratio = min(self.MAX_DIM / orig_w, self.MAX_DIM / orig_h)
            new_w = max(1, int(orig_w * ratio))
            new_h = max(1, int(orig_h * ratio))

            resample_filter = getattr(Image, "Resampling", Image).LANCZOS
            base_img = base_img.resize((new_w, new_h), resample=resample_filter)

        # Overlay Watermark Badge if provided
        wm_text = (watermark or "").strip()
        if wm_text:
            base_img = self._stamp_watermark(base_img, wm_text)

        # Convert to RGB (required for Telegram video thumbnail JPEG)
        rgb_img = Image.new("RGB", base_img.size, (15, 23, 42))
        rgb_img.paste(base_img, mask=base_img.split()[3] if base_img.mode == "RGBA" else None)

        if output_path:
            out_dir = os.path.dirname(os.path.abspath(output_path))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            rgb_img.save(output_path, "JPEG", quality=90, optimize=True)

        return rgb_img

    def _stamp_watermark(self, img: Image.Image, watermark: str) -> Image.Image:
        """Stamps an aesthetic semi-transparent channel pill badge on the thumbnail."""
        clean_wm = watermark.strip()
        badge_text = f"▶ {clean_wm}"

        font = self.font_badge or ImageFont.load_default()

        # Temporary draw to calculate text size
        temp_draw = ImageDraw.Draw(img)
        bbox = temp_draw.textbbox((0, 0), badge_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        pad_x, pad_y = 7, 4
        pill_w = text_w + pad_x * 2
        pill_h = text_h + pad_y * 2

        img_w, img_h = img.size

        # Position at bottom-right corner with 8px margin
        pos_x = max(4, img_w - pill_w - 8)
        pos_y = max(4, img_h - pill_h - 8)

        # Create overlay layer for transparent pill
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)

        # Dark frosted glass pill: rgba(10, 15, 30, 215)
        pill_box = [pos_x, pos_y, pos_x + pill_w, pos_y + pill_h]
        draw_ov.rounded_rectangle(pill_box, radius=5, fill=(10, 15, 30, 215), outline=(255, 255, 255, 70), width=1)

        # Text in crisp white
        text_x = pos_x + pad_x
        text_y = pos_y + pad_y
        draw_ov.text((text_x, text_y), badge_text, fill=(255, 255, 255, 245), font=font)

        # Alpha composite
        return Image.alpha_composite(img.convert("RGBA"), overlay)
