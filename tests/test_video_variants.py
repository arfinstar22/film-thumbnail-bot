import os
import sys
import asyncio
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _import_handlers():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    import bot.handlers as handlers
    return handlers


class TestVideoVariants(unittest.TestCase):
    def test_detect_quality(self):
        handlers = _import_handlers()
        _detect_quality = handlers._detect_quality
        self.assertEqual(_detect_quality("Film.2024.1080p.WEB-DL.mkv"), "1080p")
        self.assertEqual(_detect_quality("Film 720p HD.mp4"), "720p")
        self.assertEqual(_detect_quality("Film.4K.2160p.x265.mkv"), "2160p")
        self.assertEqual(_detect_quality("random-name.mp4", "Original"), "Original")
        self.assertEqual(_detect_quality(""), "")

    def test_upsert_video_variant_orders_and_dedupes(self):
        handlers = _import_handlers()
        _upsert_video_variant = handlers._upsert_video_variant
        variants = _upsert_video_variant([], "fid_720", "720p")
        variants = _upsert_video_variant(variants, "fid_1080", "1080p")
        variants = _upsert_video_variant(variants, "fid_480", "480p")
        self.assertEqual([v["quality"] for v in variants], ["1080p", "720p", "480p"])

        # Multiple files with same quality (e.g. 1080p 1.75GB and 1080p 782MB) are preserved
        added_same_quality = _upsert_video_variant(variants, "fid_720_new", "720p")
        self.assertEqual([v["quality"] for v in added_same_quality], ["1080p", "720p", "720p", "480p"])
        self.assertEqual([v["file_id"] for v in added_same_quality], ["fid_1080", "fid_720", "fid_720_new", "fid_480"])

        # Identical file_id is deduplicated
        same_fid = _upsert_video_variant(added_same_quality, "fid_720_new", "720p")
        self.assertEqual(len(same_fid), 4)
        self.assertEqual([v["file_id"] for v in same_fid], ["fid_1080", "fid_720", "fid_720_new", "fid_480"])

    def test_caption_kb_has_add_quality_button(self):
        handlers = _import_handlers()
        kb = handlers.get_caption_kb(98765, "@testchannel")
        datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("addquality:98765", datas)

    def test_three_videos_two_same_quality_no_duplicate_primary(self):
        from bot.services.metadata.rich_post import build_rich_article_payload
        handlers = _import_handlers()
        _upsert_video_variant = handlers._upsert_video_variant

        # Simulate user flow:
        # 1. Primary video 1080p sent to bot
        primary_fid = "fid_1080_primary_sent"
        variants = [{"quality": "1080p", "file_id": primary_fid}]

        # 2. Add second video (1080p smaller size)
        variants = _upsert_video_variant(variants, "fid_1080_second", "1080p")

        # 3. Add third video (720p)
        variants = _upsert_video_variant(variants, "fid_720", "720p")

        self.assertEqual(len(variants), 3)

        # Build payload for channel
        meta = {"title": "Lavender Marriage", "year": 2025, "resolution": "1080p"}
        payload = build_rich_article_payload(
            chat_id="@film_indonesia1",
            metadata=meta,
            watermark="@film_indonesia1",
            video_file_id=primary_fid,
            video_variants=variants
        )

        media_videos = [m for m in payload["rich_message"]["media"] if m["media"]["type"] == "video"]
        # Exactly 3 videos in slideshow, NO duplicate of primary
        self.assertEqual(len(media_videos), 3)
        self.assertEqual([v["media"]["media"] for v in media_videos], [primary_fid, "fid_1080_second", "fid_720"])

        html = payload["rich_message"]["html"]
        self.assertIn("🎞️ <b>Kualitas Tersedia:</b> 1080p • 720p", html)
        self.assertNotIn("1080p • 1080p", html)


if __name__ == "__main__":
    unittest.main()
