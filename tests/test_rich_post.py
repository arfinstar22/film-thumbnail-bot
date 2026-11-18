import os
import sys
import unittest
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata.rich_post import build_rich_article_payload


class TestRichArticlePost(unittest.TestCase):
    def test_build_rich_article_payload_structure(self):
        meta = {
            "title": "Ipar Itu Benalu",
            "year": 2026,
            "rating": "7.0",
            "genre": "Drama, Keluarga",
            "resolution": "1080p",
            "duration": "1 jam 40 menit",
            "fileSize": "1.5 GB",
            "actors": "Rina, Dimas, Siti",
            "director": "Budi Santoso",
            "synopsis": "Kisah rumah tangga Rina dan Dimas yang mulai goyah akibat kehadiran ipar.",
            "audio": "Indonesian AAC 2.0"
        }

        payload = build_rich_article_payload(
            chat_id="@testchannel",
            metadata=meta,
            watermark="@testchannel",
            video_file_id="BAACAgQAAxUHats3y8OINTYx5bjgO4-qhP-K2QEAApsIAAJxITxT0AaS0ATlhPk9BA",
            banner_file_id_or_url="banner_file_123",
            poster_file_id_or_url="poster_file_456",
            reply_markup={"inline_keyboard": [[{"text": "Tonton", "url": "https://t.me"}]]}
        )

        self.assertEqual(payload["chat_id"], "@testchannel")
        self.assertIn("rich_message", payload)
        rich_msg = payload["rich_message"]
        self.assertIn("html", rich_msg)
        html_content = rich_msg["html"]

        # Check native tags
        self.assertIn("<h1>🎬 IPAR ITU BENALU (2026)</h1>", html_content)
        self.assertIn("<tg-slideshow>", html_content)
        self.assertIn('<video src="tg://video?id=film_video"></video>', html_content)
        self.assertIn("<details>", html_content)
        self.assertIn("<summary>📖 Sinopsis Lengkap</summary>", html_content)
        self.assertIn("<summary>ℹ️ Detail Spesifikasi &amp; Pemain</summary>", html_content)
        self.assertIn("<footer>🍿 Channel Resmi: @testchannel</footer>", html_content)

        # Ensure synopsis is NOT double outside details
        before_hr = html_content.split("<hr/>")[0]
        self.assertNotIn("Kisah rumah tangga Rina", before_hr)
        after_hr = html_content.split("<hr/>")[1]
        self.assertIn("Kisah rumah tangga Rina", after_hr)

        # Ensure detailed film info specifications
        self.assertIn("📌 <b>Informasi Film:</b>", html_content)
        self.assertIn("🗓️ <b>Tahun :</b> 2026", html_content)
        self.assertIn("🎭 <b>Genre :</b> Drama, Keluarga", html_content)
        self.assertIn("🎬 <b>Sutradara :</b> Budi Santoso", html_content)
        self.assertIn("👥 <b>Pemeran :</b> Rina, Dimas, Siti", html_content)
        self.assertIn("🎞️ <b>Kualitas :</b> 1080p • Full HD", html_content)
        self.assertIn("📦 <b>Ukuran :</b> 1.5 GB", html_content)
        self.assertIn("⏱️ <b>Durasi :</b> 1 jam 40 menit", html_content)

        # Check badges row: Rating bar and Genre only (no duplicate resolution/duration in badges)
        self.assertIn("<p>⭐ <b>7.0/10</b> ███████░░░ • 🎭 Drama, Keluarga</p>", html_content)
        badge_section = html_content.split("<details>")[0] if "<details>" in html_content else ""
        self.assertNotIn("1080p", badge_section)
        self.assertNotIn("1 jam 40 menit", badge_section)

        # Check media mapping
        self.assertIn("media", rich_msg)
        media_ids = [m["id"] for m in rich_msg["media"]]
        self.assertIn("film_video", media_ids)
        self.assertIn("banner_img", media_ids)
        self.assertIn("poster_img", media_ids)

        # Check smart hashtags
        self.assertIn("#IparItuBenalu", html_content)
        self.assertIn("#Film2026", html_content)
        self.assertIn("#Drama", html_content)

    def test_similar_movies_catalog(self):
        from bot.services.metadata.cache import MetadataCache
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            cache = MetadataCache(db_path=db_path)
            cache.save_movie_post(
                title="Pengabdi Setan",
                year=2017,
                rating="7.2",
                genre="Horor, Misteri",
                quality="1080p",
                channel_username="testchannel",
                message_id=101
            )
            cache.save_movie_post(
                title="Siksa Kubur",
                year=2024,
                rating="7.0",
                genre="Horor, Thriller",
                quality="1080p",
                channel_username="testchannel",
                message_id=102
            )
            cache.save_movie_post(
                title="Dilan 1990",
                year=2018,
                rating="7.5",
                genre="Romantis, Drama",
                quality="1080p",
                channel_username="testchannel",
                message_id=103
            )

            # Khadam is Horor, Thriller
            similar = cache.get_similar_movies("testchannel", genre="Horor, Thriller", exclude_title="Khadam", limit=2)
            self.assertEqual(len(similar), 2)
            titles = [s["title"] for s in similar]
            self.assertIn("Siksa Kubur", titles)
            self.assertIn("Pengabdi Setan", titles)
            self.assertNotIn("Dilan 1990", titles)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_franchise_collection_fold(self):
        meta = {
            "title": "Dilan 1991",
            "year": 2019,
            "rating": "7.0",
            "genre": "Drama, Romantis",
            "collection": {
                "name": "Seri Dilan",
                "parts": [
                    {"title": "Dilan 1990", "year": 2018},
                    {"title": "Dilan 1991", "year": 2019},
                    {"title": "Milea: Suara dari Dilan", "year": 2020}
                ]
            }
        }
        payload = build_rich_article_payload(
            chat_id="@testchannel",
            metadata=meta,
            watermark="@testchannel"
        )
        html_content = payload["rich_message"]["html"]
        self.assertIn("🗺️ Urutan Nonton: Seri Dilan", html_content)
        self.assertIn("1️⃣ Dilan 1990 (2018)", html_content)
        self.assertIn("2️⃣ <b>Dilan 1991 (2019)</b> 📍 <i>(Film Ini)</i>", html_content)
        self.assertIn("3️⃣ Milea: Suara dari Dilan (2020)", html_content)

    def test_delete_channel_post_logic(self):
        from unittest.mock import patch, AsyncMock
        from bot.services.metadata.rich_post import async_delete_telegram_message, async_delete_channel_post

        # Test empty token
        ok, err = asyncio.run(async_delete_telegram_message("", "@testchan", 123))
        self.assertFalse(ok)

        # Test successful Bot API delete
        with patch("bot.services.metadata.rich_post.async_delete_telegram_messages", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = (True, None)
            ok, err = asyncio.run(async_delete_channel_post(None, "dummy_token", "@testchan", 123))
            self.assertTrue(ok)
            self.assertIsNone(err)

        # Test Bot API fail then Pyrogram success
        with patch("bot.services.metadata.rich_post.async_delete_telegram_messages", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = (False, "Bot API error")
            mock_client = AsyncMock()
            mock_client.delete_messages = AsyncMock(return_value=1)
            ok, err = asyncio.run(async_delete_channel_post(mock_client, "dummy_token", "@testchan", 123))
            self.assertTrue(ok)
            self.assertIsNone(err)

        # Test both fail
        with patch("bot.services.metadata.rich_post.async_delete_telegram_messages", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = (False, "Bad Request: message can't be deleted")
            mock_client = AsyncMock()
            mock_client.delete_messages = AsyncMock(side_effect=Exception("CHAT_ADMIN_REQUIRED"))
            ok, err = asyncio.run(async_delete_channel_post(mock_client, "dummy_token", "@testchan", 123))
            self.assertFalse(ok)
            self.assertIn("CHAT_ADMIN_REQUIRED", err)

    def test_rich_post_enhancements(self):
        meta = {
            "title": "Pengabdi Setan 2: Communion",
            "original_title": "Satan's Slaves 2: Communion",
            "year": 2022,
            "rating": "7.4",
            "genre": "Horor, Misteri",
            "tagline": "Semua akan kembali ke asalnya.",
            "country_codes": ["ID"],
            "production_countries": "Indonesia",
            "spoken_languages": "Bahasa Indonesia",
            "runtime_minutes": 119,
            "budget": 20000000,
            "revenue": 100000000,
            "popularity": 85.0,
            "release_date": "2022-08-04",
            "certification": "13+",
            "director": "Joko Anwar",
            "writer": "Joko Anwar",
            "studio": "Rapi Films",
            "actors": "Tara Basro, Endy Arfian",
            "synopsis": "Keluarga Rini mencoba memulai hidup baru di rumah susun.",
            "rotten_tomatoes": "85%",
            "metascore": "72",
            "awards": "Pemenang Festival Film Indonesia 2025",
            "watch_providers": ["Netflix", "Disney+ Hotstar", "Vidio"],
            "gallery_images": [
                "https://image.tmdb.org/t/p/w1280/still1.jpg",
                "https://image.tmdb.org/t/p/w1280/still2.jpg"
            ]
        }

        payload = build_rich_article_payload(
            chat_id="@filmindochannel",
            metadata=meta,
            watermark="@filmindochannel",
            video_file_id="dummy_vid_123",
            banner_file_id_or_url="https://image.tmdb.org/t/p/w1280/banner.jpg",
            poster_file_id_or_url="https://image.tmdb.org/t/p/w780/poster.jpg"
        )
        html = payload["rich_message"]["html"]

        # Tagline
        self.assertIn("✨ <i>&ldquo;Semua akan kembali ke asalnya.&rdquo;</i>", html)

        # Rating bar & Genre emoji mapping & Badges
        self.assertIn("⭐ <b>7.4/10</b> ███████░░░", html)
        self.assertIn("😱 Horor, Misteri", html)
        self.assertIn("🇮🇩", html)
        self.assertIn("⏱️ 1j 59m", html)
        self.assertIn("🏷️ 13+", html)

        # Slideshow gallery count (max 3 distinct images: banner + poster + 1 still)
        self.assertIn("🖼️ Poster &amp; Banner HD (3 gambar)", html)

        # Trending badge because popularity > 50
        self.assertIn("🔥 <b>SEDANG TRENDING</b>", html)

        # Specs
        self.assertIn("🏷️ <b>Judul Asli :</b> Satan&#x27;s Slaves 2: Communion", html)
        self.assertIn("📅 <b>Rilis :</b> 4 Agustus 2022", html)
        self.assertIn("✍️ <b>Penulis :</b> Joko Anwar", html)
        self.assertIn("🌍 <b>Negara :</b> 🇮🇩 Indonesia", html)
        self.assertIn("🏢 <b>Studio :</b> Rapi Films", html)
        self.assertIn("🔞 <b>Rating Usia :</b> 13+", html)
        self.assertIn("💰 <b>Budget :</b> $20M", html)
        self.assertIn("💵 <b>Box Office :</b> $100M", html)
        self.assertIn("⏱️ <b>Durasi :</b> 1j 59m (119 menit)", html)

        # Awards & Ratings Fold
        self.assertIn("🏆 Penghargaan &amp; Rating Lain", html)
        self.assertIn("🍅 <b>Rotten Tomatoes :</b> 85%", html)
        self.assertIn("📊 <b>Metascore :</b> 72", html)
        self.assertIn("🏅 <b>Penghargaan :</b> Pemenang Festival Film Indonesia 2025", html)

        # Watch Providers / Streaming Fold
        self.assertIn("📺 Tersedia di Platform", html)
        self.assertIn("• <b>Netflix</b> 🟥", html)
        self.assertIn("• <b>Disney+ Hotstar</b> 🟦", html)
        self.assertIn("• <b>Vidio</b> 🟩", html)

    def test_slideshow_deduplication_and_cap(self):
        """Verify slideshow caps at 3 images and deduplicates banner/poster URLs."""
        meta = {
            "title": "Film Uji",
            "backdrop_url": "https://image.tmdb.org/t/p/w1280/banner_tmdb.jpg",
            "poster_url": "https://image.tmdb.org/t/p/w780/poster_tmdb.jpg",
            "gallery_images": [
                "https://image.tmdb.org/t/p/w1280/banner_tmdb.jpg",  # duplicate of backdrop
                "https://image.tmdb.org/t/p/w780/poster_tmdb.jpg",   # duplicate of poster
                "https://image.tmdb.org/t/p/w1280/still_unique1.jpg",
                "https://image.tmdb.org/t/p/w1280/still_unique2.jpg"
            ]
        }
        payload = build_rich_article_payload(
            chat_id="@testchan",
            metadata=meta,
            watermark="@testchan",
            banner_file_id_or_url="attach://banner_file",
            poster_file_id_or_url="attach://poster_file"
        )
        media_list = payload["rich_message"]["media"]
        photos = [m for m in media_list if m["media"]["type"] == "photo"]
        # Exactly 3 images: banner, poster, and still_unique1
        self.assertEqual(len(photos), 3)
        photo_targets = [p["media"]["media"] for p in photos]
        self.assertEqual(photo_targets, [
            "attach://banner_file",
            "attach://poster_file",
            "https://image.tmdb.org/t/p/w1280/still_unique1.jpg"
        ])
        html = payload["rich_message"]["html"]
        self.assertIn("🖼️ Poster &amp; Banner HD (3 gambar)", html)

    def test_slideshow_with_tmdb_still_url(self):
        """Verify still_url from TMDB is placed as 3rd image in slideshow."""
        meta = {
            "title": "Film Cuplikan",
            "backdrop_url": "https://image.tmdb.org/t/p/original/banner.jpg",
            "poster_url": "https://image.tmdb.org/t/p/original/poster.jpg",
            "still_url": "https://image.tmdb.org/t/p/w1280/cuplikan_adegan_tmdb.jpg"
        }
        payload = build_rich_article_payload(
            chat_id="@testchan",
            metadata=meta,
            watermark="@testchan",
            banner_file_id_or_url="attach://banner_file",
            poster_file_id_or_url="attach://poster_file"
        )
        media_list = payload["rich_message"]["media"]
        photos = [m for m in media_list if m["media"]["type"] == "photo"]
        self.assertEqual(len(photos), 3)
        self.assertEqual(photos[2]["media"]["media"], "https://image.tmdb.org/t/p/w1280/cuplikan_adegan_tmdb.jpg")


    def test_single_video_backward_compatible_with_explicit_variant(self):
        meta = {"title": "Film Satu", "year": 2024, "resolution": "1080p"}
        payload = build_rich_article_payload(
            chat_id="@testchan",
            metadata=meta,
            watermark="@testchan",
            video_file_id="vid_primary",
            video_variants=[{"quality": "1080p", "file_id": "vid_primary"}]
        )
        html = payload["rich_message"]["html"]
        self.assertIn('<video src="tg://video?id=film_video"></video>', html)
        self.assertNotIn("Kualitas Tersedia", html)
        videos = [m for m in payload["rich_message"]["media"] if m["media"]["type"] == "video"]
        self.assertEqual(len(videos), 1)

    def test_multi_video_slideshow_and_quality_line(self):
        meta = {"title": "Film Dua", "year": 2024, "resolution": "1080p"}
        payload = build_rich_article_payload(
            chat_id="@testchan",
            metadata=meta,
            watermark="@testchan",
            video_file_id="vid_1080",
            video_variants=[
                {"quality": "720p", "file_id": "vid_720"},
                {"quality": "1080p", "file_id": "vid_1080"},
                {"quality": "480p", "file_id": "vid_480"},
            ]
        )
        html = payload["rich_message"]["html"]
        self.assertIn("<tg-slideshow>", html)
        self.assertIn('<video src="tg://video?id=film_video"/>', html)
        self.assertIn('<video src="tg://video?id=film_video_2"/>', html)
        self.assertIn('<video src="tg://video?id=film_video_3"/>', html)
        self.assertIn("🎞️ <b>Kualitas Tersedia:</b> 1080p • 720p • 480p", html)
        videos = [m for m in payload["rich_message"]["media"] if m["media"]["type"] == "video"]
        self.assertEqual([v["media"]["media"] for v in videos], ["vid_1080", "vid_720", "vid_480"])
        self.assertIn("🎞️ <b>Kualitas :</b> 1080p • Full HD, 720p • HD, 480p", html)

    def test_video_variants_json_string_and_dedupe(self):
        meta = {"title": "Film Tiga", "year": 2024, "resolution": "1080p"}
        payload = build_rich_article_payload(
            chat_id="@testchan",
            metadata=meta,
            watermark="@testchan",
            video_file_id="vid_primary",
            video_variants='[{"quality":"720p","file_id":"vid_720"},'
                            '{"quality":"720p","file_id":"vid_720"},'
                            '{"quality":"1080p","file_id":"vid_other"}]'
        )
        videos = [m for m in payload["rich_message"]["media"] if m["media"]["type"] == "video"]
        # Both 1080p files are preserved (different file_id), vid_720 is deduplicated by file_id
        self.assertEqual([v["media"]["media"] for v in videos], ["vid_primary", "vid_other", "vid_720"])
        html = payload["rich_message"]["html"]
        # Ensure header labels deduplicate quality names so 1080p only appears once
        self.assertIn("🎞️ <b>Kualitas Tersedia:</b> 1080p • 720p", html)
        self.assertIn("🎞️ <b>Kualitas :</b> 1080p • Full HD, 720p • HD", html)

    def test_async_send_downloads_remote_still_to_attach(self):
        """External HTTP still_url must be downloaded and sent via attach:// (never raw HTTP URL)."""
        import json
        import tempfile
        from unittest.mock import patch, MagicMock
        from bot.services.metadata.rich_post import async_send_rich_article_post

        captured = {}

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"ok": True, "result": {"message_id": 999}}).encode()

        def _fake_urlopen(req, timeout=30):
            captured["body"] = req.data
            captured["content_type"] = req.get_header("Content-type")
            return _FakeResp()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as b_tmp, \
             tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as p_tmp:
            b_tmp.write(b"\xff\xd8\xff\xe0banner")
            p_tmp.write(b"\xff\xd8\xff\xe0poster")
            b_path, p_path = b_tmp.name, p_tmp.name

        try:
            meta = {
                "title": "Heart",
                "year": 2006,
                "still_url": "https://image.tmdb.org/t/p/w1280/9szww8nGR1ZCeYgqyoZSWqqVbhT.jpg",
            }
            with patch("bot.services.metadata.rich_post._download_photo_bytes",
                       return_value=(b"\xff\xd8\xff\xe0still", "image/jpeg", "jpg")), \
                 patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                res = asyncio.run(async_send_rich_article_post(
                    bot_token="123:ABC",
                    chat_id="@film_indonesia1",
                    metadata=meta,
                    watermark="@film_indonesia1",
                    video_file_id="vid_heart_2006",
                    banner_path=b_path,
                    poster_path=p_path,
                ))
            self.assertEqual(res, {"message_id": 999})
            body_text = captured["body"].decode("latin1")
            self.assertIn("attach://banner_file", body_text)
            self.assertIn("attach://poster_file", body_text)
            self.assertIn("attach://remote_img_1", body_text)
            self.assertNotIn("https://image.tmdb.org/t/p/w1280/9szww8nGR1ZCeYgqyoZSWqqVbhT.jpg", body_text)
        finally:
            for p in (b_path, p_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_async_send_drops_broken_still_url_and_still_sends_rich_post(self):
        """If downloading external still_url fails, skip it cleanly so Rich Post still succeeds."""
        import json
        import tempfile
        from unittest.mock import patch
        from bot.services.metadata.rich_post import async_send_rich_article_post

        captured = {}

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"ok": True, "result": {"message_id": 1000}}).encode()

        def _fake_urlopen(req, timeout=30):
            captured["body"] = req.data
            return _FakeResp()

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as b_tmp, \
             tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as p_tmp:
            b_tmp.write(b"\xff\xd8\xff\xe0banner")
            p_tmp.write(b"\xff\xd8\xff\xe0poster")
            b_path, p_path = b_tmp.name, p_tmp.name

        try:
            meta = {
                "title": "Heart",
                "year": 2006,
                "still_url": "https://image.tmdb.org/t/p/w1280/broken_404.jpg",
                "gallery_images": ["https://image.tmdb.org/t/p/w1280/also_unfetched.jpg"],
            }
            with patch("bot.services.metadata.rich_post._download_photo_bytes", return_value=None), \
                 patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                res = asyncio.run(async_send_rich_article_post(
                    bot_token="123:ABC",
                    chat_id="@film_indonesia1",
                    metadata=meta,
                    watermark="@film_indonesia1",
                    video_file_id="vid_heart_2006",
                    banner_path=b_path,
                    poster_path=p_path,
                ))
            self.assertEqual(res, {"message_id": 1000})
            body_text = captured["body"].decode("latin1")
            self.assertIn("Poster &amp; Banner HD (2 gambar)", body_text)
            self.assertNotIn("broken_404.jpg", body_text)
            self.assertNotIn("also_unfetched.jpg", body_text)
        finally:
            for p in (b_path, p_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_async_send_retries_without_http_on_http_400_url_error(self):
        """Safety net: if Telegram still responds HTTP 400 failed to get HTTP URL content, retry cleanly."""
        import json
        import urllib.error
        from io import BytesIO
        from unittest.mock import patch
        from bot.services.metadata.rich_post import async_send_rich_article_post

        calls = []

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"ok": True, "result": {"message_id": 1001}}).encode()

        def _fake_urlopen(req, timeout=30):
            calls.append(req.data)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 400, "Bad Request", {},
                    BytesIO(b'{"ok":false,"error_code":400,"description":"Bad Request: failed to get HTTP URL content"}')
                )
            return _FakeResp()

        meta = {"title": "Heart", "year": 2006}
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            res = asyncio.run(async_send_rich_article_post(
                bot_token="123:ABC",
                chat_id="@film_indonesia1",
                metadata=meta,
                watermark="@film_indonesia1",
                video_file_id="vid_heart_2006",
            ))
        self.assertEqual(res, {"message_id": 1001})
        self.assertEqual(len(calls), 2)

    def test_async_send_returns_timed_out_sentinel_and_uses_120s_timeout(self):
        """Read timeout must return _timed_out sentinel (not None) so caller never double-posts."""
        from unittest.mock import patch
        from bot.services.metadata.rich_post import async_send_rich_article_post

        seen_timeouts = []

        def _fake_urlopen(req, timeout=30):
            seen_timeouts.append(timeout)
            raise TimeoutError("The read operation timed out")

        meta = {"title": "Heart", "year": 2006}
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            res = asyncio.run(async_send_rich_article_post(
                bot_token="123:ABC",
                chat_id="@film_indonesia1",
                metadata=meta,
                watermark="@film_indonesia1",
                video_file_id="vid_heart_2006",
            ))
        self.assertEqual(seen_timeouts, [120])
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("_timed_out"))
        self.assertIsNone(res.get("message_id"))


if __name__ == "__main__":
    unittest.main()

