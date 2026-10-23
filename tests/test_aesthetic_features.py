import os
import sys
import unittest
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/home/darfinstar/projectTumbnail/.env")

from bot.services.metadata.banner import BannerGenerator
from bot.services.metadata.caption import CaptionGenerator
from bot.services.metadata.catalog import format_pinned_catalog, publish_movie_instant_view
from bot.services.metadata.cache import MetadataCache


class TestAestheticFeatures(unittest.TestCase):
    def setUp(self):
        self.test_db = "/tmp/test_aesthetic.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.cache = MetadataCache(self.test_db)
        self.caption_gen = CaptionGenerator(cache=self.cache)
        self.banner_gen = BannerGenerator()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    # 1. BANNER GENERATOR 2.0
    def test_banner_generator_cinematic_2(self):
        """Should generate 1280x720 cinematic hero card with floating poster and modern badges."""
        meta = {
            "title": "Pengabdi Setan 2: Communion",
            "year": 2022,
            "rating": "7.4 / 10 • TMDb",
            "genre": "Horor, Misteri",
            "director": "Joko Anwar",
            "actors": "Tara Basro, Endy Arfian",
            "resolution": "1080p",
            "audio": "Dub Indo",
            "subtitle": "Softsub Indo",
            "source": "WEB-DL"
        }
        out_banner = "/tmp/test_banner_cinematic.jpg"
        if os.path.exists(out_banner):
            os.remove(out_banner)

        img = self.banner_gen.create_banner(meta, watermark="@film_indonesia1", output_path=out_banner)
        self.assertEqual(img.size, (1280, 720))
        self.assertTrue(os.path.exists(out_banner))
        if os.path.exists(out_banner):
            os.remove(out_banner)

    # 2. CAPTION PRESET STYLES
    def test_caption_styles(self):
        """Should support minimalist, streaming, and editorial styles strictly <= 1024 chars."""
        meta = {
            "title": "The Raid: Redemption <Special>",
            "year": 2011,
            "rating": "8.1 / 10 • TMDb",
            "genre": "Action, Crime",
            "director": "Gareth Evans",
            "actors": "Iko Uwais, Joe Taslim",
            "resolution": "1080p",
            "audio": "Dub Indo",
            "subtitle": "Softsub Indo",
            "fileSize": "1.8 GB",
            "duration": "101 Menit",
            "source": "WEB-DL",
            "synopsis": "Sebuah tim pasukan khusus terjebak di gedung apartemen 30 lantai milik gembong narkoba kejam. " * 15
        }

        # 1. Minimalist
        cap_min = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="minimalist")
        self.assertLessEqual(len(cap_min), 1024)
        self.assertIn("— • — • —", cap_min)
        self.assertIn("&lt;SPECIAL&gt;", cap_min)

        # 2. Streaming
        cap_stream = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="streaming")
        self.assertLessEqual(len(cap_stream), 1024)
        self.assertIn("━━━━━━━━━━━━━━━━━━", cap_stream)
        self.assertIn("📌 <b>Informasi Film:</b>", cap_stream)

        # 3. Editorial
        cap_edit = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="editorial")
        self.assertLessEqual(len(cap_edit), 1024)
        self.assertIn("Karya Sutradara Gareth Evans", cap_edit)

        # 4. Compact (One-Glance)
        cap_compact = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="compact")
        self.assertLessEqual(len(cap_compact), 1024)
        self.assertIn("⭐ <b>8.1 / 10</b>", cap_compact)
        self.assertIn("🎞️ <b>1080p FHD</b>", cap_compact)

        # 5. Cinema VIP Premiere
        cap_vip = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="cinema_vip")
        self.assertLessEqual(len(cap_vip), 1024)
        self.assertIn("🎟️ <b>PREMIERE EXCLUSIVE</b>", cap_vip)
        self.assertIn("⚜️ <b>SPESIFIKASI TAYANG:</b>", cap_vip)

        # 6. Monochrome / Swiss Apple TV
        cap_mono = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="monochrome")
        self.assertLessEqual(len(cap_mono), 1024)
        self.assertIn("★ <b>8.1 / 10</b> TMDb", cap_mono)
        self.assertNotIn("🎬", cap_mono)  # Zero emoji clutter

        # 7. Sinema Retro
        cap_retro = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="sinema_retro")
        self.assertLessEqual(len(cap_retro), 1024)
        self.assertIn("📽️ <b>SINEMA INDONESIA</b>", cap_retro)
        self.assertIn("Arsip Resmi", cap_retro)

        # 8. Article (Interactive Collapsible Cards)
        cap_article = self.caption_gen.generate(meta, custom_watermark="@film_indonesia1", style="article")
        self.assertLessEqual(len(cap_article), 1024)
        self.assertIn("POSTER RESMI FILM", cap_article)
        self.assertIn("SINOPSIS LENGKAP:", cap_article)
        self.assertIn("DETAIL SPESIFIKASI & PEMAIN:", cap_article)
        self.assertIn("<blockquote expandable>", cap_article)

    # 3. NETFLIX HOMEPAGE PINNED CATALOG
    def test_netflix_pinned_catalog(self):
        """Should format a Netflix-style streaming homepage with top rated, latest, and genre navigation."""
        movies = [
            {"title": "The Raid", "year": 2011, "rating": "8.1 / 10", "quality": "1080p", "message_id": 10},
            {"title": "Pengabdi Setan 2", "year": 2022, "rating": "7.4 / 10", "quality": "1080p", "message_id": 20},
            {"title": "Agak Laen", "year": 2024, "rating": "7.8 / 10", "quality": "1080p", "message_id": 30},
            {"title": "Laskar Pelangi", "year": 2008, "rating": "7.9 / 10", "quality": "720p", "message_id": 40},
            {"title": "Dua Garis Biru", "year": 2019, "rating": "7.6 / 10", "quality": "1080p", "message_id": 50},
            {"title": "Kuntilanak", "year": 2006, "rating": "5.5 / 10", "quality": "480p", "message_id": 60},
        ]
        cat = format_pinned_catalog(movies, "film_indonesia1", "film_bot")
        self.assertLessEqual(len(cat), 3800)
        self.assertIn("PUSAT FILM INDONESIA • KATALOG RESMI", cat)
        self.assertIn("TOP 5 FILM RATING TERTINGGI", cat)
        self.assertIn("UPDATE RILIS TERBARU", cat)
        self.assertIn("JELAJAHI GENRE POPULER", cat)
        # Top 1 should be The Raid (8.1)
        self.assertIn("1. ⭐ <b>8.1</b> • <a href=\"https://t.me/film_indonesia1/10\">The Raid (2011)</a>", cat)

    # 4. TELEGRAPH INSTANT VIEW BROCHURE
    def test_movie_instant_view_cached(self):
        """Should cache and return movie Instant View Telegraph page."""
        meta = {
            "title": "Gundala",
            "year": 2019,
            "rating": "6.3 / 10",
            "genre": "Action, Sci-Fi",
            "synopsis": "Sancaka hidup di jalanan sejak ditinggal orang tuanya. Menghadapi ketidakadilan, ia harus memutuskan untuk menolong atau tetap bertahan hidup sendiri."
        }
        # Pre-seed cache to test caching logic
        self.cache.set_setting("telegraph_movie_film_indonesia1_gundala_2019", "https://telegra.ph/Gundala-2019-Brochure")
        url = publish_movie_instant_view(meta, "film_indonesia1", self.cache)
        self.assertEqual(url, "https://telegra.ph/Gundala-2019-Brochure")


    # 5. VIBRANT COLORFUL CHANNEL BUTTONS (NATIVE TELEGRAM BOT API)
    def test_channel_post_colorful_buttons(self):
        """Should build clean button text with native styles: Blue (primary), Green (success), Red (danger)."""
        from bot.handlers import build_channel_post_keyboard, _build_bot_api_reply_markup

        kb = build_channel_post_keyboard(
            watermark="@film_indonesia1",
            title="Agak Laen",
            year=2024,
            trailer_url="https://youtube.com/watch?v=123",
            instant_view_url="https://telegra.ph/Agak-Laen-2024",
            request_link="https://t.me/filmin_bot?start=req"
        )
        texts = [[b.text for b in row] for row in kb.inline_keyboard]

        # Clean, emoji-box-free text
        self.assertEqual(texts[0], ["⚡ BUKA BROSUR FILM", "🎬 TRAILER"])
        self.assertEqual(texts[1], ["💬 REQUEST FILM", "📤 BAGIKAN"])

        # Native Bot API 9.4 styles
        bot_api_kb = _build_bot_api_reply_markup(kb)["inline_keyboard"]
        self.assertEqual(bot_api_kb[0][0]["style"], "primary")   # Brosur: Blue
        self.assertEqual(bot_api_kb[0][1]["style"], "success")   # Trailer: Green
        self.assertEqual(bot_api_kb[1][0]["style"], "danger")    # Request: Red
        self.assertEqual(bot_api_kb[1][1]["style"], "success")   # Bagikan: Green

    # 6. PINNED CATALOG STYLED BUTTONS
    def test_pinned_catalog_styled_buttons(self):
        """Should serialize pinned catalog buttons with Blue, Green, and Red styles."""
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from bot.handlers import _build_bot_api_reply_markup

        btn_cat = InlineKeyboardButton("⚡ BUKA KATALOG LENGKAP (50 Film)", url="https://telegra.ph/cat")
        btn_cat.style = "primary"
        btn_search = InlineKeyboardButton("🔍 Cari Koleksi Film", switch_inline_query_current_chat="")
        btn_search.style = "success"
        btn_req = InlineKeyboardButton("💬 Request Film", url="https://t.me/filmin_bot?start=req")
        btn_req.style = "danger"

        kb = InlineKeyboardMarkup([[btn_cat], [btn_search, btn_req]])
        res = _build_bot_api_reply_markup(kb)["inline_keyboard"]

        self.assertEqual(res[0][0]["style"], "primary")
        self.assertEqual(res[1][0]["style"], "success")
        self.assertEqual(res[1][1]["style"], "danger")
        self.assertEqual(res[1][0]["switch_inline_query_current_chat"], "")


if __name__ == "__main__":
    unittest.main()
