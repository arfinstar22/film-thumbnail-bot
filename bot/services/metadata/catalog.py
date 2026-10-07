import logging
from collections import defaultdict
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def format_pinned_catalog(movies: List[Dict[str, Any]], channel_username: str, bot_username: str = "") -> str:
    """Format an aesthetic A-Z alphabetical directory with native Telegram links."""
    clean_channel = channel_username.lstrip("@").strip()
    total = len(movies)

    header = (
        "📚 <b>KATALOG & DAFTAR ISI FILM LENGKAP</b>\n"
        f"📢 <b>Channel:</b> @{clean_channel}\n"
        f"🔄 <i>Diperbarui otomatis • Total: {total} Koleksi</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    groups = defaultdict(list)
    for m in movies:
        title = (m.get("title") or "").strip()
        first_char = title[0].upper() if title else "#"
        if not first_char.isalpha():
            first_char = "#"
        groups[first_char].append(m)

    body_lines = []
    sorted_keys = sorted([k for k in groups.keys() if k != "#"])
    if "#" in groups:
        sorted_keys.append("#")

    for char in sorted_keys:
        body_lines.append(f"🔤 <b>[ {char} ]</b>")
        for m in groups[char]:
            title = m["title"]
            year_str = f" ({m['year']})" if m.get("year") else ""
            msg_id = m["message_id"]
            post_url = f"https://t.me/{clean_channel}/{msg_id}"
            rating = f" • ⭐ {m['rating']}" if m.get("rating") else ""
            body_lines.append(f"• <a href=\"{post_url}\">{title}{year_str}</a>{rating}")
        body_lines.append("")

    body_text = "\n".join(body_lines).strip()
    if not body_text:
        body_text = "<i>Belum ada film di katalog. Gunakan /synckatalog untuk memindai channel.</i>"

    footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <i>Gunakan tombol di bawah atau ketik @{bot_username or 'bot'} untuk cari film instan.</i>"
    )

    full_text = header + body_text + footer

    # Fallback to ultra-compact format if exceeding Telegram limit of 4096 chars
    if len(full_text) > 4000:
        compact_lines = []
        for char in sorted_keys:
            items = [
                f'<a href="https://t.me/{clean_channel}/{m["message_id"]}">{m["title"]}</a>'
                for m in groups[char]
            ]
            compact_lines.append(f"🔤 <b>[{char}]</b> " + " • ".join(items))
        body_text = "\n".join(compact_lines)
        full_text = header + body_text + footer

    # Hard safety cap
    if len(full_text) > 4000:
        full_text = full_text[:3950] + "...\n\n<i>(Daftar berlanjut via /cari)</i>" + footer

    return full_text
