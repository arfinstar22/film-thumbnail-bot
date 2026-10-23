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
import html as html_mod
import json
import logging
import os
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


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
    source = metadata.get("source")
    video_codec = metadata.get("videoCodec")
    audio_codec = metadata.get("audioCodec")
    audio_channels = metadata.get("audioChannels")
    release_group = metadata.get("releaseGroup")

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

    # 2. HEADING (Film Title)
    html_parts.append(f"<h1>🎬 {title_disp}</h1>")

    # 3. SLIDESHOW (Banner & Poster swipeable gallery — collapsible)
    slideshow_imgs: List[str] = []
    if banner_file_id_or_url:
        slideshow_imgs.append('<img src="tg://photo?id=banner_img"/>')
        media_items.append({
            "id": "banner_img",
            "media": {
                "type": "photo",
                "media": banner_file_id_or_url
            }
        })
    if (
        poster_file_id_or_url
        and poster_file_id_or_url != banner_file_id_or_url
    ):
        slideshow_imgs.append('<img src="tg://photo?id=poster_img"/>')
        media_items.append({
            "id": "poster_img",
            "media": {
                "type": "photo",
                "media": poster_file_id_or_url
            }
        })

    if slideshow_imgs:
        if len(slideshow_imgs) > 1:
            imgs_content = f"<tg-slideshow>\n{''.join(slideshow_imgs)}\n</tg-slideshow>"
        else:
            imgs_content = slideshow_imgs[0]
        html_parts.append(
            f"<details>\n"
            f"<summary>🖼️ Poster &amp; Banner HD</summary>\n"
            f"{imgs_content}\n"
            f"</details>"
        )

    # 4. BADGES (Rating, Genre, Resolution, Duration)
    badge_items: List[str] = []
    if rating:
        clean_rating = str(rating).replace("• IMDb", "").replace("IMDb", "").replace("• TMDb", "").replace("TMDb", "").strip()
        badge_items.append(f"⭐ <b>{html_mod.escape(clean_rating)}/10</b>")
    if genre:
        badge_items.append(f"🎭 {html_mod.escape(str(genre))}")
    if resolution:
        res_label = resolution
        if resolution == "1080p":
            res_label = "1080p FHD"
        elif resolution == "2160p":
            res_label = "2160p 4K UHD"
        elif resolution == "720p":
            res_label = "720p HD"
        badge_items.append(f"🎞️ {html_mod.escape(res_label)}")
    if duration:
        badge_items.append(f"⏳ {html_mod.escape(str(duration))}")

    if badge_items:
        html_parts.append(f"<p>{' • '.join(badge_items)}</p>")

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
    if genre:
        spec_lines.append(f"🎭 <b>Genre :</b> {html_mod.escape(str(genre))}")
    if director:
        spec_lines.append(f"🎬 <b>Sutradara :</b> {html_mod.escape(str(director))}")
    if actors:
        spec_lines.append(f"👥 <b>Pemeran :</b> {html_mod.escape(str(actors))}")
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

    html_parts.append("<hr/>")

    # 7. FOOTER
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
