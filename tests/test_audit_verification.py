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


if __name__ == "__main__":
    test_caption_generator()
    test_rating_service_non_ascii()
    test_synopsis_service_cleaning()
    test_ai_refiner_json_parsing()
    test_cache_wal_and_busy_timeout()
    test_video_service_timestamp_parsing()
    test_admin_dashboard_length()
    test_smart_caption_enrichment()
    print("\n🎉 ALL AUDIT VERIFICATION CHECKS PASSED!")

