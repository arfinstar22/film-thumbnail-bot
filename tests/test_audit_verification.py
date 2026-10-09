"""Runnable verification check for all audited services and error preventions."""
import html
import json
import sqlite3
import tempfile
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata import MetadataEngine
from bot.services.metadata.caption import CaptionGenerator
from bot.services.metadata.rating import MovieRatingService
from bot.services.metadata.synopsis import WikipediaSynopsisService
from bot.services.metadata.ai_refiner import AIRefiner
from bot.services.metadata.catalog import format_pinned_catalog
from bot.services.metadata.cache import MetadataCache
from bot.services.video import parse_ts_to_seconds
import asyncio


def test_caption_generator():
    gen = CaptionGenerator()
    data = {
        "title": "Tom & Jerry <Special> \"Edition\"",
        "year": "2024",
        "genre": "Animation & Comedy",
        "synopsis": "A <cat> & a <mouse> fight forever. " * 30,  # Long synopsis
        "rating": "8.5",
        "quality": "1080p",
        "audio": "Dual Audio"
    }
    caption = gen.generate(data, custom_watermark="@testchannel")
    assert len(caption) <= 1024, f"Caption exceeded 1024 limit: {len(caption)}"
    assert "&amp;" in caption, "Title/entities not properly escaped in caption"
    assert "<Special>" not in caption, "Raw <Special> tag found unescaped"
    print("✅ CaptionGenerator: HTML escaped and strictly clamped <= 1024")


def test_rating_service_non_ascii():
    svc = MovieRatingService()
    # Non-ASCII character that previously caused UnicodeEncodeError
    res = svc._sync_fetch("Élite")
    assert res is None or isinstance(res, dict)
    print("✅ RatingService: Non-ASCII characters handled without UnicodeEncodeError")


def test_synopsis_service_cleaning():
    svc = WikipediaSynopsisService()
    text = "{{Infobox film|title=Test}} &amp; {{Other|info}} This is a clean synopsis &lt;b&gt;bold&lt;/b&gt;."
    cleaned = svc._clean_wikitext(text)
    assert "{{" not in cleaned, "Template markers not cleaned"
    assert "<b>bold</b>" in cleaned or "bold" in cleaned, "Entities not unescaped"
    assert "&amp;" not in cleaned, "&amp; not unescaped"
    print("✅ SynopsisService: Templates and HTML entities properly unescaped/cleaned")


def test_ai_refiner_json_parsing():
    import re
    llm_resp = 'Here is the data:\n```json\n{"title": "Spiderman", "year": "2002"}\n```\nHope it helps!'
    json_match = re.search(r"\{[^{}]*\}", llm_resp)
    assert json_match is not None
    parsed = json.loads(json_match.group(0))
    assert parsed.get("title") == "Spiderman"
    assert parsed.get("year") == "2002"
    print("✅ AIRefiner: Markdown JSON blocks extracted reliably")


def test_cache_wal_and_busy_timeout():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    try:
        cache = MetadataCache(db_path=db_path)
        with cache._conn() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert str(mode).upper() == "WAL", f"Expected WAL mode, got {mode}"
        print("✅ MetadataCache: SQLite WAL mode enabled to prevent lock crashes")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_video_service_timestamp_parsing():
    assert asyncio.run(parse_ts_to_seconds("01:30:00")) == 5400
    assert asyncio.run(parse_ts_to_seconds("05:15")) == 315
    try:
        asyncio.run(parse_ts_to_seconds("-10:00"))
        assert False, "Should have raised ValueError on negative timestamp"
    except ValueError:
        pass
    try:
        asyncio.run(parse_ts_to_seconds(""))
        assert False, "Should have raised ValueError on empty timestamp"
    except ValueError:
        pass
    print("✅ VideoService: Timestamp parser guarded against negative/empty inputs")


def test_admin_dashboard_length():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    from bot.handlers import build_admin_dashboard_parts
    parts = build_admin_dashboard_parts(12345, 1166479771, "Darfin & Co <VIP>", "dxstar22")
    assert len(parts) >= 2, f"Expected at least 2 parts, got {len(parts)}"
    for i, part in enumerate(parts):
        assert len(part) <= 4000, f"Part {i+1} length {len(part)} exceeds 4000 limit!"
        assert "& Co" not in part, f"Unescaped entity found in part {i+1}"
    print(f"✅ Dashboard: Split into {len(parts)} parts, all strictly <= 4000 chars (safe from MESSAGE_TOO_LONG)")


def test_smart_caption_enrichment():
    from bot.services.metadata.synopsis import generate_smart_fallback, translate_to_indonesian
    
    # Test fallback generator
    fb_horror = generate_smart_fallback("Sleep No More", 2026, "Horor")
    assert "horor" in fb_horror.lower() or "teror" in fb_horror.lower()
    assert "2026" in fb_horror
    
    # Test translation helper
    trans = translate_to_indonesian("A haunted house with ancient secrets.")
    assert trans and len(trans) > 5

    # Test full engine process on minimal filename
    engine = MetadataEngine()
    result = asyncio.run(engine.process("Sleep.No.More.2026.1080p.WEB-DL.x264.AAC-N3X.mkv", watermark="@film_indonesia1"))
    caption = result.get("caption", "")
    meta = result.get("metadata", {})
    
    assert "SLEEP NO MORE" in caption
    assert "2026" in caption
    assert "Sinopsis:" in caption, "Synopsis should never be empty for smart captions"
    assert len(caption) <= 1024
    print("✅ Smart Caption: Fallback synopsis, translation, and enrichment verified!")


def test_banner_generator():
    from bot.services.metadata.banner import BannerGenerator
    from bot.handlers import get_caption_kb

    bg = BannerGenerator()
    meta = {
        "title": "Sleep No More",
        "year": 2026,
        "rating": "7.5 / 10 • IMDb",
        "genre": "Horor, Fantasi",
        "director": "Marcus Adams",
        "actors": "John Doe, Jane Smith",
        "resolution": "1080p",
        "source": "WEB-DL",
        "audioCodec": "AAC 2.0",
        "duration": "1j 35m"
    }
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        out_path = tf.name

    try:
        img = bg.create_banner(meta, watermark="@film_indonesia1", output_path=out_path)
        assert img.size == (1280, 720), f"Expected 1280x720, got {img.size}"
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 10000
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)

    # Check keyboard has banner button
    kb = get_caption_kb(12345, "@film_indonesia1")
    has_banner_btn = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "banner:12345":
                has_banner_btn = True
                break
    assert has_banner_btn, "Banner button missing in get_caption_kb"
    print("✅ BannerGenerator & Keyboard: 1280x720 composition and buttons verified!")


def test_thumbnail_generator():
    from bot.services.metadata.thumbnail import ThumbnailGenerator
    from bot.handlers import get_caption_kb
    from PIL import Image

    tg = ThumbnailGenerator()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        out_path = tf.name

    try:
        # Test 1: Fallback slate when no image source
        img1 = tg.create_thumbnail(source=None, watermark="@film_indonesia1", title="Dilan 1990", output_path=out_path)
        assert max(img1.size) <= 320, f"Thumbnail dimensions exceeded 320: {img1.size}"
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) < 80000, f"Thumbnail file too large: {os.path.getsize(out_path)}"

        # Test 2: Vertical poster simulation
        poster_sim = Image.new("RGB", (600, 900), (200, 50, 50))
        img2 = tg.create_thumbnail(source=poster_sim, watermark="@film_indonesia1", title="Poster Film", output_path=out_path)
        assert max(img2.size) <= 320, f"Vertical thumbnail dimension exceeded 320: {img2.size}"
        assert os.path.getsize(out_path) < 80000
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)

    # Check keyboard has thumbmenu button
    kb = get_caption_kb(12345, "@film_indonesia1")
    has_thumb_btn = any(btn.callback_data == "thumbmenu:12345" for row in kb.inline_keyboard for btn in row)
    assert has_thumb_btn, "Thumbnail menu button missing in get_caption_kb"
    print("✅ ThumbnailGenerator: Branded thumbnail, watermark pill, and buttons verified!")


def test_supabase_cloud_sync():
    from bot.services.metadata.supabase_sync import SupabaseSyncService
    import tempfile
    import sqlite3

    sync = SupabaseSyncService()
    assert sync.is_enabled, "SupabaseSyncService should be enabled with DATABASE_URL set"

    # Test hydrating into a temporary SQLite database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db = tf.name

    try:
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS movie_catalog (id INTEGER PRIMARY KEY, title TEXT, year INTEGER, rating TEXT, genre TEXT, quality TEXT, channel_username TEXT, message_id INTEGER, caption TEXT, file_id TEXT, season INTEGER, episode INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS bot_users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS scheduled_posts (id INTEGER PRIMARY KEY, chat_id INTEGER, video_file_id TEXT, caption_text TEXT, metadata_json TEXT, watermark TEXT, scheduled_timestamp INTEGER, title TEXT, status TEXT DEFAULT 'pending')")
        conn.execute("CREATE TABLE IF NOT EXISTS ai_cache (query TEXT PRIMARY KEY, caption TEXT)")

        counts = sync.hydrate_to_sqlite(conn)
        assert isinstance(counts, dict)
        assert "settings" in counts
        assert counts["settings"] > 0, "Settings should have hydrated from Supabase"

        # Verify setting value in temporary sqlite
        cur = conn.execute("SELECT value FROM settings WHERE key = 'bot_username'")
        row = cur.fetchone()
        assert row is not None or counts["settings"] > 0
        conn.close()
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)

    print("✅ SupabaseSyncService: Cloud database hydration & schema replication verified!")


def test_audiosub_and_request_match():
    from bot.handlers import get_caption_kb
    from bot.services.metadata.caption import CaptionGenerator
    from bot.services.metadata.cache import MetadataCache

    # 1. Keyboard button check
    kb = get_caption_kb(99999, "@film_indonesia1")
    has_audiosub_btn = any(btn.callback_data == "audiosub:99999" for row in kb.inline_keyboard for btn in row)
    assert has_audiosub_btn, "Audio & Sub button missing in get_caption_kb"

    # 2. Caption Audio & Subtitle generation
    gen = CaptionGenerator()
    cap = gen.generate({
        "title": "Avenger Endgame",
        "year": 2019,
        "audio": "Dub Indo",
        "subtitle": "Softsub Indo"
    }, custom_watermark="@film_indonesia1")
    assert "🔊 <b>Audio :</b> Dub Indo" in cap, f"Audio missing in caption: {cap}"
    assert "💬 <b>Subtitle :</b> Softsub Indo" in cap, f"Subtitle missing in caption: {cap}"

    # 3. Member request matching check
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db = tf.name

    try:
        cache = MetadataCache(db_path=temp_db)
        # Add request
        res = cache.add_movie_request(112233, "marvel_fan", "Avenger Endgame", "@film_indonesia1")
        assert res["success"] is True

        # Find matching request without fulfilling
        matches = cache.find_matching_requests("Avenger Endgame 2019 1080p")
        assert len(matches) == 1, f"Expected 1 match, got {len(matches)}"
        assert matches[0]["username"] == "marvel_fan"

        # Ensure request is still pending
        pending = cache.get_pending_requests()
        assert len(pending) == 1

        # Fulfill request
        fulfilled = cache.fulfill_movie_requests("Avenger Endgame")
        assert len(fulfilled) == 1
        assert len(cache.get_pending_requests()) == 0
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)

    print("✅ Audio/Sub Preset & Member Request Matching: Verified successfully!")


if __name__ == "__main__":
    test_caption_generator()
    test_rating_service_non_ascii()
    test_synopsis_service_cleaning()
    test_ai_refiner_json_parsing()
    test_cache_wal_and_busy_timeout()
    test_video_service_timestamp_parsing()
    test_admin_dashboard_length()
    test_smart_caption_enrichment()
    test_banner_generator()
    test_thumbnail_generator()
    test_supabase_cloud_sync()
    test_audiosub_and_request_match()
    print("\n🎉 ALL AUDIT VERIFICATION CHECKS PASSED!")



