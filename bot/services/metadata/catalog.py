import json
import logging
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def publish_or_update_telegraph_catalog(
    movies: List[Dict[str, Any]],
    channel_username: str,
    cache: Any,
    bot_username: str = ""
) -> Optional[str]:
    """Publish or update a Telegraph page containing the complete A-Z catalog.
    Enables native Telegram Instant View (⚡) without any character limit.
    """
    clean_channel = (channel_username or "").lstrip("@").strip()
    if not movies:
        return None

    try:
        token = cache.get_setting("telegraph_token", "")
        if not token:
            acc_data = urllib.parse.urlencode({
                "short_name": "FilmCatalog",
                "author_name": f"Katalog @{clean_channel}",
                "author_url": f"https://t.me/{clean_channel}"
            }).encode("utf-8")
            req = urllib.request.Request("https://api.telegra.ph/createAccount", data=acc_data)
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    token = res.get("result", {}).get("access_token")
                    if token:
                        cache.set_setting("telegraph_token", token)

        if not token:
            logger.warning("Could not obtain Telegraph access token")
            return None

        # Build Telegraph content nodes
        groups = defaultdict(list)
        for m in movies:
            t = (m.get("title") or "").strip()
            first_char = t[0].upper() if t and t[0].isalpha() else "#"
            groups[first_char].append(m)

        sorted_keys = sorted([k for k in groups.keys() if k != "#"])
        if "#" in groups:
            sorted_keys.append("#")

        ribbon = " • ".join([f"[{k}]" for k in sorted_keys])
        nodes = [
            {"tag": "h3", "children": [f"🍿 KATALOG KOLEKSI FILM @{clean_channel.upper()} (A - Z)"]},
            {
                "tag": "blockquote",
                "children": [
                    f"📢 Channel Resmi: @{clean_channel}\n",
                    f"🎬 Total Koleksi: {len(movies)} Judul Film\n",
                    "⚡ Mode: Telegram Instant View (Buka cepat & ringan)\n",
                    "💡 Ketuk judul film untuk langsung membuka dan menonton di Telegram."
                ]
            },
            {
                "tag": "p",
                "children": [
                    f"🔤 Indeks Abjad: {ribbon}"
                ]
            },
            {"tag": "hr"}
        ]

        for char in sorted_keys:
            nodes.append({
                "tag": "h4",
                "children": [f"📁 [ {char} ] — {len(groups[char])} Koleksi"]
            })
            li_items = []
            for m in groups[char]:
                title = (m.get("title") or "Film").strip()
                year = m.get("year")
                rating = m.get("rating")
                genre = m.get("genre")
                quality = m.get("quality")
                msg_id = m.get("message_id")
                post_url = f"https://t.me/{clean_channel}/{msg_id}"

                title_str = f"{title} ({year})" if year else title
                meta_parts = []
                if rating:
                    meta_parts.append(f"⭐ {rating}")
                if quality:
                    meta_parts.append(f"🎞️ {quality}")
                if genre:
                    meta_parts.append(f"🎭 {genre}")

                meta_str = f" — {' • '.join(meta_parts)}" if meta_parts else ""

                li_items.append({
                    "tag": "li",
                    "children": [
                        {
                            "tag": "b",
                            "children": [
                                {
                                    "tag": "a",
                                    "attrs": {"href": post_url},
                                    "children": [f"🎬 {title_str}"]
                                }
                            ]
                        },
                        meta_str
                    ]
                })
            nodes.append({"tag": "ul", "children": li_items})
            nodes.append({"tag": "hr"})

        bot_mention = f"@{bot_username}" if bot_username else f"@{clean_channel}"
        nodes.append({
            "tag": "blockquote",
            "children": [
                "🔍 PANDUAN PENCARIAN & NONTON:\n",
                "• Cari Cepat: Gunakan fitur 'Find in page' (Ctrl+F) di browser / Telegram.\n",
                f"• Cari Instan via Bot: {bot_mention}\n",
                f"🍿 Selamat menonton & menikmati koleksi film di @{clean_channel}!"
            ]
        })

        path_key = f"telegraph_path_{clean_channel}"
        cached_path = cache.get_setting(path_key, "")

        # Telegraph 64KB content limit safeguard: switch to compact format if content exceeds 60KB
        content_json = json.dumps(nodes)
        if len(content_json.encode("utf-8")) > 60000:
            compact_nodes = [nodes[0], nodes[1], nodes[2], nodes[3]]
            for char in sorted_keys:
                char_items = []
                for m in groups[char]:
                    title = (m.get("title") or "Film").strip()
                    year = m.get("year")
                    msg_id = m.get("message_id")
                    post_url = f"https://t.me/{clean_channel}/{msg_id}"
                    t_str = f"{title} ({year})" if year else title
                    char_items.append({
                        "tag": "li",
                        "children": [{"tag": "b", "children": [{"tag": "a", "attrs": {"href": post_url}, "children": [f"🎬 {t_str}"]}]}]
                    })
                compact_nodes.append({"tag": "h4", "children": [f"📁 [ {char} ] — {len(groups[char])} Koleksi"]})
                compact_nodes.append({"tag": "ul", "children": char_items})
                compact_nodes.append({"tag": "hr"})
            compact_nodes.append(nodes[-1])
            nodes = compact_nodes

        page_title = f"🍿 KATALOG FILM @{clean_channel.upper()}"

        if cached_path:
            # Edit existing page
            edit_data = urllib.parse.urlencode({
                "access_token": token,
                "path": cached_path,
                "title": page_title,
                "author_name": f"@{clean_channel}",
                "author_url": f"https://t.me/{clean_channel}",
                "content": json.dumps(nodes),
                "return_content": "false"
            }).encode("utf-8")
            try:
                with urllib.request.urlopen(urllib.request.Request("https://api.telegra.ph/editPage", data=edit_data), timeout=10) as resp:
                    res_edit = json.loads(resp.read().decode("utf-8"))
                    if res_edit.get("ok"):
                        return res_edit.get("result", {}).get("url") or f"https://telegra.ph/{cached_path}"
            except Exception as ee:
                logger.warning(f"Failed to edit Telegraph page {cached_path}: {ee}")

        # Create new page if not existing or edit failed
        create_data = urllib.parse.urlencode({
            "access_token": token,
            "title": page_title,
            "author_name": f"@{clean_channel}",
            "author_url": f"https://t.me/{clean_channel}",
            "content": json.dumps(nodes),
            "return_content": "false"
        }).encode("utf-8")
        with urllib.request.urlopen(urllib.request.Request("https://api.telegra.ph/createPage", data=create_data), timeout=10) as resp:
            res_create = json.loads(resp.read().decode("utf-8"))
            if res_create.get("ok"):
                new_path = res_create.get("result", {}).get("path")
                new_url = res_create.get("result", {}).get("url")
                if new_path:
                    cache.set_setting(path_key, new_path)
                return new_url
    except Exception as e:
        logger.error(f"Telegraph catalog error: {e}")
        return None


def format_pinned_catalog(
    movies: List[Dict[str, Any]],
    channel_username: str,
    bot_username: str = "",
    telegraph_url: Optional[str] = None
) -> str:
    """Format an aesthetic A-Z alphabetical directory with native Telegram links.
    If catalog exceeds character limit, switches to an Executive Hub layout with Telegraph Instant View.
    """
    clean_channel = channel_username.lstrip("@").strip()
    total = len(movies)

    groups = defaultdict(list)
    for m in movies:
        title = (m.get("title") or "").strip()
        first_char = title[0].upper() if title else "#"
        if not first_char.isalpha():
            first_char = "#"
        groups[first_char].append(m)

    sorted_keys = sorted([k for k in groups.keys() if k != "#"])
    if "#" in groups:
        sorted_keys.append("#")

    # If small list (< 60 movies), display direct list
    if total <= 60:
        header = (
            "📚 <b>KATALOG & DAFTAR ISI FILM LENGKAP</b>\n"
            f"📢 <b>Channel:</b> @{clean_channel}\n"
            f"🔄 <i>Diperbarui otomatis • Total: {total} Koleksi</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        body_lines = []
        for char in sorted_keys:
            body_lines.append(f"🔤 <b>[ {char} ]</b>")
            for m in groups[char]:
                title = m["title"]
                year_str = f" ({m['year']})" if m.get("year") else ""
                msg_id = m["message_id"]
                post_url = f"https://t.me/{clean_channel}/{msg_id}"
                meta_parts = []
                if m.get("rating"):
                    meta_parts.append(f"⭐ {m['rating']}")
                if m.get("quality"):
                    meta_parts.append(f"🎞️ {m['quality']}")
                meta_str = f" • {' '.join(meta_parts)}" if meta_parts else ""
                body_lines.append(f"• <a href=\"{post_url}\">{title}{year_str}</a>{meta_str}")
            body_lines.append("")

        body_text = "\n".join(body_lines).strip()
        if not body_text:
            body_text = "<i>Belum ada film di katalog. Gunakan /synckatalog untuk memindai channel.</i>"

        footer = (
            "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 <i>Gunakan tombol di bawah untuk cari film instan atau buka Instant View ⚡!</i>"
        )

        full_text = header + body_text + footer
        if len(full_text) <= 3800:
            return full_text

    # Executive Hub layout for large catalogs (prevents character limit overflow)
    header = (
        "📚 <b>KATALOG KOLEKSI FILM LENGKAP</b>\n"
        f"📢 <b>Channel:</b> @{clean_channel}\n"
        f"🎬 <b>Total Koleksi:</b> <b>{total} Film (A - Z)</b>\n"
        "⚡ <b>Mode:</b> Instant View (Buka kilat tanpa lag)\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    index_letters = " ".join([f"<b>[{k}]</b>" for k in sorted_keys])
    index_section = (
        "🔤 <b>Indeks Abjad Tersedia:</b>\n"
        f"{index_letters}\n\n"
    )

    latest_movies = sorted(movies, key=lambda x: x.get("message_id") or 0, reverse=True)[:8]
    latest_lines = ["🆕 <b>Update Film Terbaru:</b>"]
    for m in latest_movies:
        title = m["title"]
        year_str = f" ({m['year']})" if m.get("year") else ""
        msg_id = m["message_id"]
        post_url = f"https://t.me/{clean_channel}/{msg_id}"
        meta_parts = []
        if m.get("rating"):
            meta_parts.append(f"⭐ {m['rating']}")
        if m.get("quality"):
            meta_parts.append(f"🎞️ {m['quality']}")
        meta_str = f" • {' '.join(meta_parts)}" if meta_parts else ""
        latest_lines.append(f"• <a href=\"{post_url}\">{title}{year_str}</a>{meta_str}")

    latest_section = "\n".join(latest_lines) + "\n\n"

    footer = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📖 <i>Klik tombol <b>[ ⚡ BUKA KATALOG LENGKAP ]</b> di bawah untuk membuka daftar lengkap via Instant View tanpa limit karakter!</i>"
    )

    return header + index_section + latest_section + footer
