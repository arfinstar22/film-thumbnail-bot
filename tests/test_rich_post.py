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


if __name__ == "__main__":
    unittest.main()

