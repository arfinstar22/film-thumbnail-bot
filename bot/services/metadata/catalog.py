import json
import logging
import math
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Telegraph hard limit is 64KB per page; stay under with margin
_MAX_PAGE_BYTES = 58000


def _telegraph_api(endpoint: str, payload: dict, timeout: int = 15) -> Optional[dict]:
    """Call a Telegraph API endpoint and return the result dict, or None on failure."""
    data = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegra.ph/{endpoint}", data=data),
            timeout=timeout,
        ) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("ok"):
                return res.get("result", {})
    except Exception as e:
        logger.warning(f"Telegraph API {endpoint} failed: {e}")
    return None


def _ensure_token(cache: Any, channel: str) -> Optional[str]:
    """Get or create a Telegraph access token, cached in settings."""
    token = cache.get_setting("telegraph_token", "")
    if token:
        return token
    result = _telegraph_api("createAccount", {
        "short_name": "FilmCatalog",
        "author_name": f"Katalog @{channel}",
        "author_url": f"https://t.me/{channel}",
    })
    if result:
        token = result.get("access_token")
        if token:
            cache.set_setting("telegraph_token", token)
            return token
    return None


def _publish_page(token: str, title: str, nodes: list, channel: str,
                  cache: Any, cache_key: str) -> Optional[str]:
    """Create or edit a single Telegraph page. Returns URL or None."""
    content_str = json.dumps(nodes)
    author = f"@{channel}"
    author_url = f"https://t.me/{channel}"

    cached_path = cache.get_setting(cache_key, "")
    if cached_path:
        result = _telegraph_api("editPage", {
            "access_token": token,
            "path": cached_path,
            "title": title,
            "author_name": author,
            "author_url": author_url,
            "content": content_str,
            "return_content": "false",
        })
        if result:
            return result.get("url") or f"https://telegra.ph/{cached_path}"

    result = _telegraph_api("createPage", {
        "access_token": token,
        "title": title,
        "author_name": author,
        "author_url": author_url,
        "content": content_str,
        "return_content": "false",
    })
    if result:
        path = result.get("path")
        if path:
            cache.set_setting(cache_key, path)
        return result.get("url")
    return None


def _build_film_nodes(films: List[Dict[str, Any]], channel: str,
                      include_meta: bool = True) -> list:
    """Build Telegraph list-item nodes for a list of films."""
    items = []
    for m in films:
        title = (m.get("title") or "Film").strip()
        year = m.get("year")
        msg_id = m.get("message_id")
        post_url = f"https://t.me/{channel}/{msg_id}"
        t_str = f"{title} ({year})" if year else title

        link_node = {"tag": "a", "attrs": {"href": post_url}, "children": [f"🎬 {t_str}"]}
        children: list = [{"tag": "b", "children": [link_node]}]

        if include_meta:
            meta_parts = []
            if m.get("rating"):
                meta_parts.append(f"⭐ {m['rating']}")
            if m.get("quality"):
                meta_parts.append(f"🎞️ {m['quality']}")
            if m.get("genre"):
                meta_parts.append(f"🎭 {m['genre']}")
            if meta_parts:
                children.append(f" — {' • '.join(meta_parts)}")

        items.append({"tag": "li", "children": children})
    return items


def _content_size(nodes: list) -> int:
    return len(json.dumps(nodes).encode("utf-8"))


def publish_or_update_telegraph_catalog(
    movies: List[Dict[str, Any]],
    channel_username: str,
    cache: Any,
    bot_username: str = ""
) -> Optional[str]:
    """Publish a multi-page Telegraph catalog (one page per letter group + index).

    When films fit in a single page (<58KB), uses one page as before.
    When they don't, creates per-letter sub-pages and a master index page
    linking to each. Scales to 1000+ films without hitting Telegraph's 64KB limit.
    """
    clean_channel = (channel_username or "").lstrip("@").strip()
    if not movies:
        return None

    token = _ensure_token(cache, clean_channel)
    if not token:
        return None

    try:
        return _build_and_publish(movies, clean_channel, cache, token, bot_username)
    except Exception as e:
        logger.error(f"Telegraph catalog error: {e}")
        return None


def _build_and_publish(
    movies: List[Dict[str, Any]],
    channel: str,
    cache: Any,
    token: str,
    bot_username: str,
) -> Optional[str]:
    groups = defaultdict(list)
    for m in movies:
        t = (m.get("title") or "").strip()
        first_char = t[0].upper() if t and t[0].isalpha() else "#"
        groups[first_char].append(m)

    sorted_keys = sorted([k for k in groups if k != "#"])
    if "#" in groups:
        sorted_keys.append("#")

    bot_mention = f"@{bot_username}" if bot_username else f"@{channel}"

    # --- Try single-page first ---
    single_nodes = _build_single_page_nodes(movies, groups, sorted_keys, channel, bot_mention)
    if _content_size(single_nodes) <= _MAX_PAGE_BYTES:
        cache_key = f"telegraph_path_{channel}"
        title = f"🍿 KATALOG FILM @{channel.upper()}"
        return _publish_page(token, title, single_nodes, channel, cache, cache_key)

    # --- Try single-page compact (no meta) ---
    compact_nodes = _build_single_page_nodes(movies, groups, sorted_keys, channel, bot_mention, include_meta=False)
    if _content_size(compact_nodes) <= _MAX_PAGE_BYTES:
        cache_key = f"telegraph_path_{channel}"
        title = f"🍿 KATALOG FILM @{channel.upper()}"
        return _publish_page(token, title, compact_nodes, channel, cache, cache_key)

    # --- Multi-page: one page per letter, then master index ---
    letter_urls: List[Tuple[str, int, str]] = []  # (char, count, url)
    for char in sorted_keys:
        char_films = groups[char]
        urls = _publish_letter_pages(token, channel, cache, char, char_films, bot_mention)
        if urls:
            letter_urls.append((char, len(char_films), urls[0]))

    if not letter_urls:
        return None

    # Build index page
    index_nodes = _build_index_page_nodes(movies, letter_urls, channel, bot_mention)
    cache_key = f"telegraph_path_{channel}"
    title = f"🍿 KATALOG FILM @{channel.upper()}"
    return _publish_page(token, title, index_nodes, channel, cache, cache_key)


def _build_single_page_nodes(
    movies: List[Dict[str, Any]],
    groups: dict,
    sorted_keys: list,
    channel: str,
    bot_mention: str,
    include_meta: bool = True,
) -> list:
    ribbon = " • ".join([f"[{k}]" for k in sorted_keys])
    nodes = [
        {"tag": "h3", "children": [f"🍿 KATALOG KOLEKSI FILM @{channel.upper()} (A - Z)"]},
        {"tag": "blockquote", "children": [
            f"📢 Channel Resmi: @{channel}\n",
            f"🎬 Total Koleksi: {len(movies)} Judul Film\n",
            "⚡ Mode: Telegram Instant View (Buka cepat & ringan)\n",
            "💡 Ketuk judul film untuk langsung membuka dan menonton di Telegram.",
        ]},
        {"tag": "p", "children": [f"🔤 Indeks Abjad: {ribbon}"]},
        {"tag": "hr"},
    ]
    for char in sorted_keys:
        nodes.append({"tag": "h4", "children": [f"📁 [ {char} ] — {len(groups[char])} Koleksi"]})
        nodes.append({"tag": "ul", "children": _build_film_nodes(groups[char], channel, include_meta)})
        nodes.append({"tag": "hr"})
    nodes.append({"tag": "blockquote", "children": [
        "🔍 PANDUAN PENCARIAN & NONTON:\n",
        "• Cari Cepat: Gunakan fitur 'Find in page' (Ctrl+F) di browser / Telegram.\n",
        f"• Cari Instan via Bot: {bot_mention}\n",
        f"🍿 Selamat menonton & menikmati koleksi film di @{channel}!",
    ]})
    return nodes


def _publish_letter_pages(
    token: str, channel: str, cache: Any,
    char: str, films: List[Dict[str, Any]], bot_mention: str,
) -> List[str]:
    """Publish one or more Telegraph pages for a single letter.

    If the letter's films exceed _MAX_PAGE_BYTES, they get chunked
    into multiple pages (e.g. A part 1/2, A part 2/2).
    Returns list of URLs (first URL is the main one for this letter).
    """
    # Try full meta first
    items = _build_film_nodes(films, channel, include_meta=True)
    header_nodes = [
        {"tag": "h3", "children": [f"📁 KATALOG HURUF [ {char} ] — @{channel.upper()}"]},
        {"tag": "blockquote", "children": [
            f"🎬 {len(films)} Film dimulai huruf {char}\n",
            f"📢 Channel: @{channel}\n",
            f"💡 Ketuk judul film untuk langsung menonton di Telegram.",
        ]},
        {"tag": "hr"},
    ]
    footer_nodes = [{"tag": "p", "children": [
        f"🔍 Cari Instan via Bot: {bot_mention}"
    ]}]

    test_nodes = header_nodes + [{"tag": "ul", "children": items}] + footer_nodes
    if _content_size(test_nodes) <= _MAX_PAGE_BYTES:
        cache_key = f"telegraph_letter_{channel}_{char}"
        title = f"📁 Katalog [{char}] — @{channel.upper()}"
        url = _publish_page(token, title, test_nodes, channel, cache, cache_key)
        return [url] if url else []

    # Strip meta and retry
    items = _build_film_nodes(films, channel, include_meta=False)
    test_nodes = header_nodes + [{"tag": "ul", "children": items}] + footer_nodes
    if _content_size(test_nodes) <= _MAX_PAGE_BYTES:
        cache_key = f"telegraph_letter_{channel}_{char}"
        title = f"📁 Katalog [{char}] — @{channel.upper()}"
        url = _publish_page(token, title, test_nodes, channel, cache, cache_key)
        return [url] if url else []

    # Still too big — chunk the films
    # ponytail: binary-search optimal chunk count would be smaller diff,
    # but linear halving is simpler and letter pages rarely exceed 2 chunks
    n_chunks = 2
    while n_chunks <= len(films):
        chunk_size = math.ceil(len(films) / n_chunks)
        chunks = [films[i:i + chunk_size] for i in range(0, len(films), chunk_size)]
        fits = True
        for chunk in chunks:
            chunk_items = _build_film_nodes(chunk, channel, include_meta=False)
            chunk_nodes = header_nodes + [{"tag": "ul", "children": chunk_items}] + footer_nodes
            if _content_size(chunk_nodes) > _MAX_PAGE_BYTES:
                fits = False
                break
        if fits:
            break
        n_chunks += 1

    chunk_size = math.ceil(len(films) / n_chunks)
    chunks = [films[i:i + chunk_size] for i in range(0, len(films), chunk_size)]
    urls = []
    for idx, chunk in enumerate(chunks, 1):
        chunk_items = _build_film_nodes(chunk, channel, include_meta=False)
        part_header = [
            {"tag": "h3", "children": [f"📁 KATALOG [{char}] — Bagian {idx}/{len(chunks)}"]},
            {"tag": "blockquote", "children": [
                f"🎬 {len(chunk)} Film (bagian {idx} dari {len(chunks)})\n",
                f"📢 Channel: @{channel}",
            ]},
            {"tag": "hr"},
        ]
        page_nodes = part_header + [{"tag": "ul", "children": chunk_items}] + footer_nodes
        cache_key = f"telegraph_letter_{channel}_{char}_p{idx}"
        title = f"📁 [{char}] Bag.{idx}/{len(chunks)} — @{channel.upper()}"
        url = _publish_page(token, title, page_nodes, channel, cache, cache_key)
        if url:
            urls.append(url)
    return urls


def _build_index_page_nodes(
    movies: List[Dict[str, Any]],
    letter_urls: List[Tuple[str, int, str]],
    channel: str,
    bot_mention: str,
) -> list:
    """Build the master index page that links to each letter sub-page."""
    nodes = [
        {"tag": "h3", "children": [f"🍿 KATALOG KOLEKSI FILM @{channel.upper()} (A - Z)"]},
        {"tag": "blockquote", "children": [
            f"📢 Channel Resmi: @{channel}\n",
            f"🎬 Total Koleksi: {len(movies)} Judul Film\n",
            "⚡ Mode: Telegram Instant View (Buka cepat & ringan)\n",
            "💡 Ketuk huruf di bawah untuk melihat semua film yang dimulai huruf tersebut.",
        ]},
        {"tag": "hr"},
        {"tag": "h4", "children": ["📂 INDEKS KATALOG A - Z"]},
    ]

    li_items = []
    for char, count, url in letter_urls:
        li_items.append({"tag": "li", "children": [
            {"tag": "b", "children": [
                {"tag": "a", "attrs": {"href": url}, "children": [f"📁 [ {char} ] — {count} Film"]},
            ]},
        ]})
    nodes.append({"tag": "ul", "children": li_items})
    nodes.append({"tag": "hr"})

    # Latest films section on index page too
    latest = sorted(movies, key=lambda x: x.get("message_id") or 0, reverse=True)[:10]
    if latest:
        nodes.append({"tag": "h4", "children": ["🆕 UPDATE FILM TERBARU"]})
        latest_items = _build_film_nodes(latest, channel, include_meta=True)
        nodes.append({"tag": "ul", "children": latest_items})
        nodes.append({"tag": "hr"})

    nodes.append({"tag": "blockquote", "children": [
        "🔍 PANDUAN PENCARIAN & NONTON:\n",
        "• Ketuk huruf di atas untuk membuka katalog per abjad.\n",
        "• Gunakan 'Find in page' (Ctrl+F) di halaman huruf.\n",
        f"• Cari Instan via Bot: {bot_mention}\n",
        f"🍿 Selamat menonton & menikmati koleksi film di @{channel}!",
    ]})
    return nodes


def format_pinned_catalog(
    movies: List[Dict[str, Any]],
    channel_username: str,
    bot_username: str = "",
    telegraph_url: Optional[str] = None
) -> str:
    """Format an aesthetic 'Netflix Homepage' style directory with native Telegram links,
    top-rated curation, latest releases, genre mood navigator, and Instant View Telegraph master catalog.
    """
    clean_channel = channel_username.lstrip("@").strip()
    total = len(movies)

    header = (
        "🎬 <b>PUSAT FILM INDONESIA • KATALOG RESMI</b>\n"
        f"📢 <b>Channel:</b> @{clean_channel}\n"
        f"🍿 <i>Pusat Streaming & Download Film Indonesia Terlengkap</i>\n"
        f"📊 <i>Total Koleksi: <b>{total} Judul Film</b> • Update Otomatis</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # 1. Update Rilis Terbaru (5 film terakhir)
    latest_movies = sorted(movies, key=lambda x: x.get("message_id") or 0, reverse=True)[:5]
    latest_section = ""
    if latest_movies:
        latest_lines = ["🆕 <b>UPDATE RILIS TERBARU:</b>"]
        for m in latest_movies:
            title = m["title"]
            year_str = f" ({m['year']})" if m.get("year") else ""
            msg_id = m.get("message_id")
            post_url = f"https://t.me/{clean_channel}/{msg_id}" if msg_id else f"https://t.me/{clean_channel}"
            meta_chips = []
            if m.get("quality"):
                meta_chips.append(m["quality"])
            chips_str = f" <code>[{' • '.join(meta_chips)}]</code>" if meta_chips else ""
            latest_lines.append(f"• <a href=\"{post_url}\">{title}{year_str}</a>{chips_str}")
        latest_section = "\n".join(latest_lines) + "\n\n"

    # 2. Jelajahi Koleksi Berdasarkan Mood / Genre
    bot_ref = f"https://t.me/{bot_username}" if bot_username else f"https://t.me/{clean_channel}"
    genre_section = (
        "🎭 <b>JELAJAHI GENRE POPULER:</b>\n"
        f"• 👻 <b>Horor & Misteri</b> — Kisah mistis & uji nyali\n"
        f"• 😂 <b>Komedi & Santai</b> — Hiburan tawa keluarga\n"
        f"• 💥 <b>Aksi & Petualangan</b> — Ketegangan & adrenalin\n"
        f"• ❤️ <b>Romantis & Drama</b> — Cerita cinta & emosional\n"
        f"👉 <i>Temukan rekomendasi instan via <a href=\"{bot_ref}?start=mood\">Menu Mood Bot</a></i>\n\n"
    )

    # 3. Navigasi & Pencarian Cepat
    nav_section = (
        "🔍 <b>NAVIGASI & PENCARIAN CEPAT:</b>\n"
        f"• <a href=\"{bot_ref}?start=cari\">🔎 Cari Judul Film Instan</a>\n"
        f"• <a href=\"{bot_ref}?start=request\">💬 Request Film yang Belum Ada</a>\n"
        f"• <a href=\"{bot_ref}?start=mood\">🎲 Acak Film Sesuai Mood</a>\n\n"
    )

    footer = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📖 <i>Katalog lengkap seluruh film (A - Z) dapat dibuka tanpa batas melalui tombol <b>[ ⚡ BUKA KATALOG LENGKAP ]</b> di bawah!</i>"
    )

    return header + latest_section + genre_section + nav_section + footer


def publish_movie_instant_view(
    metadata: Dict[str, Any],
    channel_username: str,
    cache: Any,
    post_message_id: Optional[int] = None
) -> Optional[str]:
    """Publishes a rich, cinematic Telegraph Instant View page for a single movie.
    Returns the Telegraph URL for inclusion in channel post buttons.
    """
    clean_channel = channel_username.lstrip("@").strip()
    title = (metadata.get("title") or "Film").strip()
    year = metadata.get("year")
    title_disp = f"{title} ({year})" if year else title

    clean_key_title = re.sub(r'[^a-zA-Z0-9]', '', title).lower()
    cache_key = f"telegraph_movie_{clean_channel}_{clean_key_title}_{year or 0}"
    cached_url = cache.get_setting(cache_key, "")
    if cached_url and str(cached_url).startswith("http"):
        return cached_url

    token = _ensure_token(cache, clean_channel)
    if not token:
        return None

    # Telegraph Nodes
    nodes = []

    # 1. Header Image (Backdrop or Poster)
    img_src = metadata.get("backdrop_url") or metadata.get("poster_url")
    if img_src and str(img_src).startswith("http"):
        nodes.append({
            "tag": "figure",
            "children": [
                {"tag": "img", "attrs": {"src": img_src}},
                {"tag": "figcaption", "children": [f"🎬 {title_disp} • Channel Resmi @{clean_channel}"]}
            ]
        })

    # 2. Main Title & Badges
    nodes.append({"tag": "h3", "children": [f"🎬 {title_disp}"]})

    specs = []
    if metadata.get("rating"):
        specs.append(f"⭐ {metadata['rating']}")
    if metadata.get("genre"):
        specs.append(f"🎭 {metadata['genre']}")
    if metadata.get("duration"):
        specs.append(f"⏳ {metadata['duration']}")
    if metadata.get("resolution"):
        specs.append(f"🎞️ {metadata['resolution']}")
    if metadata.get("audio"):
        specs.append(f"🔊 {metadata['audio']}")
    if metadata.get("subtitle"):
        specs.append(f"💬 {metadata['subtitle']}")

    if specs:
        nodes.append({
            "tag": "blockquote",
            "children": [" • ".join(specs)]
        })

    nodes.append({"tag": "hr"})

    # 3. Synopsis Section
    synopsis = (metadata.get("synopsis") or metadata.get("plot") or "").strip()
    if synopsis:
        nodes.append({"tag": "h4", "children": ["📖 SINOPSIS RESMI"]})
        paras = [p.strip() for p in re.split(r'\n\n+|\.\s+(?=[A-Z])', synopsis) if p.strip()]
        if len(paras) > 1 and len(synopsis) > 200:
            for p in paras[:4]:
                p_text = p if p.endswith('.') else p + '.'
                nodes.append({"tag": "p", "children": [p_text]})
        else:
            nodes.append({"tag": "p", "children": [synopsis]})
        nodes.append({"tag": "hr"})

    # 4. Cast & Crew Section
    cast_children = []
    if metadata.get("director"):
        cast_children.append(f"🎬 Sutradara: {metadata['director']}\n")
    if metadata.get("actors"):
        cast_children.append(f"👥 Pemeran Utama: {metadata['actors']}\n")
    if metadata.get("source") or metadata.get("releaseGroup"):
        rel = f"{metadata.get('source', '')} {metadata.get('releaseGroup', '')}".strip()
        cast_children.append(f"📦 Release / Source: {rel}\n")

    if cast_children:
        nodes.append({"tag": "h4", "children": ["👥 INFORMASI PRODUKSI"]})
        nodes.append({"tag": "blockquote", "children": cast_children})
        nodes.append({"tag": "hr"})

    # 5. Direct Action CTA
    channel_url = f"https://t.me/{clean_channel}"
    watch_url = f"{channel_url}/{post_message_id}" if post_message_id else channel_url
    nodes.append({"tag": "h4", "children": ["🍿 NONTON & DOWNLOAD FILM"]})
    nodes.append({
        "tag": "p",
        "children": [
            {"tag": "b", "children": [
                {"tag": "a", "attrs": {"href": watch_url}, "children": ["▶️ Klik Di Sini Untuk Menonton / Download di Channel"]}
            ]}
        ]
    })
    nodes.append({
        "tag": "p",
        "children": [
            {"tag": "a", "attrs": {"href": channel_url}, "children": [f"📢 Gabung Channel @{clean_channel} untuk film lainnya!"]}
        ]
    })

    page_title = f"{title_disp} — Brosur Resmi"
    url = _publish_page(token, page_title, nodes, clean_channel, cache, cache_key)
    if url:
        cache.set_setting(cache_key, url)
    return url
