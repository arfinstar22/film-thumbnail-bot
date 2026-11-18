import io
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata import homepage as homepage_mod
from bot.services.metadata.homepage import (
    HomepageRenderer,
    build_homepage_caption,
    build_homepage_keyboard,
    homepage_signature,
    resolve_homepage_assets,
)


def _image_bytes(color=(40, 80, 120)):
    image = Image.new("RGB", (300, 450), color)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


MOVIES = [
    {"title": "Agak Laen", "year": 2024, "rating": "7.8 / 10", "quality": "1080p", "message_id": 2857},
    {"title": "Pengabdi Setan 2", "year": 2022, "rating": "7.4 / 10", "quality": "1080p", "message_id": 2856},
    {"title": "The Raid", "year": 2011, "rating": "7.9 / 10", "quality": "1080p", "message_id": 2855},
    {"title": "Laskar Pelangi", "year": 2008, "rating": "7.5 / 10", "quality": "720p", "message_id": 2854},
    {"title": "Dua Garis Biru", "year": 2019, "rating": "7.3 / 10", "quality": "1080p", "message_id": 2853},
]


class TestHomepageCaption(unittest.TestCase):
    def test_caption_has_five_numbered_links_without_top_rating(self):
        caption = build_homepage_caption(
            MOVIES, "film_indonesia1", 514,
            schedule=[("19:00", "Film A"), ("21:00", "Film B")]
        )
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("514 film", caption)
        self.assertNotIn("Top rating", caption)
        self.assertNotIn("⭐", caption)
        for index, movie in enumerate(MOVIES, 1):
            self.assertIn(f"{index}. ", caption)
            self.assertIn(
                f'https://t.me/film_indonesia1/{movie["message_id"]}', caption
            )
        self.assertIn("Hari ini", caption)

    def test_caption_escapes_html_and_drops_schedule_when_long(self):
        movies = [
            {"title": "<b>Judul & Aman</b>", "year": 2024, "rating": "7.0",
             "quality": "1080p", "message_id": 1}
        ]
        caption = build_homepage_caption(
            movies, "film_indonesia1", 1,
            schedule=[("19:00", "Film " + "X" * 400)]
        )
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("&lt;b&gt;Judul &amp; Aman&lt;/b&gt;", caption)
        self.assertNotIn("<b>Judul", caption)

    def test_caption_without_schedule_or_movies(self):
        caption = build_homepage_caption([], "film_indonesia1", 0)
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("0 film", caption)
        self.assertNotIn("Hari ini", caption)


class TestHomepageKeyboard(unittest.TestCase):
    def test_three_main_rows_and_colors(self):
        keyboard = build_homepage_keyboard(
            "film_indonesia1", 514, "https://telegra.ph/katalog",
            "film_bot", "https://t.me/film_bot?start=request",
            "https://t.me/film_bot?start=cari"
        )
        rows = keyboard.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0].text, "⚡ BUKA KATALOG A-Z (514 Film)")
        self.assertEqual(rows[0][0].style, "primary")
        self.assertEqual(rows[1][0].text, "🔍 Cari Film")
        self.assertEqual(rows[1][1].text, "💬 Request Film")
        self.assertEqual(rows[1][0].style, "success")
        self.assertEqual(rows[1][1].style, "danger")


class TestHomepageRenderer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assets(self, count):
        assets = []
        for index, movie in enumerate(MOVIES[:count]):
            assets.append({
                "title": movie["title"],
                "year": movie["year"],
                "rating": movie["rating"],
                "quality": movie["quality"],
                "poster_url": f"https://example.com/{index}.jpg",
                "poster": _image_bytes((30 + index * 25, 60, 110)),
                "backdrop": _image_bytes((10, 20, 40)) if index == 0 else None,
            })
        return assets

    def test_render_empty_one_and_five_posters(self):
        renderer = HomepageRenderer()
        for count in (0, 1, 5):
            output = os.path.join(self.tmpdir, f"homepage_{count}.jpg")
            renderer.render(self._assets(count), "film_indonesia1", 514, output)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1280, 720))

    def test_signature_changes_with_new_movie(self):
        assets = self._assets(5)
        base = homepage_signature("film_indonesia1", assets, 514)
        changed = [dict(asset) for asset in assets]
        changed[0]["poster_url"] = "https://example.com/new.jpg"
        self.assertNotEqual(base, homepage_signature("film_indonesia1", changed, 514))
        self.assertNotEqual(base, homepage_signature("film_indonesia1", assets, 515))

        # Replacing a movie (same total & poster_url, new message_id) or recovering a missing poster must refresh image
        replaced = [dict(asset) for asset in assets]
        replaced[0]["message_id"] = 9999
        self.assertNotEqual(base, homepage_signature("film_indonesia1", replaced, 514))

        missing_poster = [dict(asset) for asset in assets]
        missing_poster[0]["poster"] = None
        self.assertNotEqual(base, homepage_signature("film_indonesia1", missing_poster, 514))


class TestHomepageAssets(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = MetadataCache(os.path.join(self.tmpdir, "test.db"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resolver_prefers_homepage_then_rating_then_banner(self):
        movie = {"title": "The Raid", "year": 2011, "rating": "7.9"}
        self.cache.set_setting("homepage_poster_the raid_2011", "https://example.com/hero.jpg")
        self.cache.set_setting("rating_v2_the raid_2011", '{"poster_url": "https://example.com/rating.jpg"}')

        class FakeTMDb:
            def search_movie(self, *args, **kwargs):
                return {"poster_url": "https://example.com/tmdb.jpg"}

        with patch.object(homepage_mod, "_download_image_bytes", return_value=b"image"):
            assets = resolve_homepage_assets(self.cache, [movie], FakeTMDb())
        self.assertEqual(assets[0]["poster_url"], "https://example.com/hero.jpg")

        self.cache.set_setting("homepage_poster_the raid_2011", "")
        with patch.object(homepage_mod, "_download_image_bytes", return_value=b"image"):
            assets = resolve_homepage_assets(self.cache, [movie], FakeTMDb())
        self.assertEqual(assets[0]["poster_url"], "https://example.com/rating.jpg")

    def test_resolver_falls_back_to_tmdb_and_placeholder(self):
        movie = {"title": "Film Langka", "year": 1999, "rating": "6.0"}
        self.cache.set_setting("banner_fid_film langka_1999", "file-id-not-a-url")

        class FakeTMDb:
            def search_movie(self, *args, **kwargs):
                return {"poster_url": "https://example.com/tmdb.jpg"}

        with patch.object(homepage_mod, "_download_image_bytes", return_value=b"image"):
            assets = resolve_homepage_assets(self.cache, [movie], FakeTMDb())
        self.assertEqual(assets[0]["poster_url"], "https://example.com/tmdb.jpg")

        self.cache.set_setting("homepage_poster_film langka_1999", "")
        self.cache.set_setting("rating_v2_film langka_1999", "")
        with patch.object(homepage_mod, "_download_image_bytes", return_value=None):
            assets = resolve_homepage_assets(self.cache, [movie], None)
        self.assertIsNone(assets[0]["poster"])


class TestHomepageHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from bot import handlers

        self.handlers = handlers
        self.tmpdir = tempfile.mkdtemp()
        self.cache = MetadataCache(os.path.join(self.tmpdir, "test.db"), enable_cloud=False)
        self.previous_cache = handlers._engine.cache
        handlers._engine.cache = self.cache
        self.cache.save_movie_post(
            title="Film Uji Homepage", year=2024, rating="7.8", genre="Komedi",
            quality="1080p", channel_username="film_indonesia1",
            message_id=9999, caption="caption", file_id="file-id"
        )
        self.assets = [{
            "title": "Film Uji Homepage", "year": 2024, "rating": "7.8",
            "quality": "1080p", "poster_url": "https://example.com/p.jpg",
            "poster": _image_bytes(), "backdrop": _image_bytes((10, 20, 40)),
        }]

    async def asyncTearDown(self):
        self.handlers._engine.cache = self.previous_cache
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _client(self, pinned_message):
        async def history(*args, **kwargs):
            if False:
                yield None

        client = SimpleNamespace(
            get_chat=AsyncMock(return_value=SimpleNamespace(pinned_message=pinned_message)),
            get_messages=AsyncMock(return_value=pinned_message),
            send_photo=AsyncMock(return_value=SimpleNamespace(id=900)),
            edit_message_caption=AsyncMock(return_value=True),
            edit_message_media=AsyncMock(return_value=True),
            pin_chat_message=AsyncMock(return_value=None),
            unpin_all_chat_messages=AsyncMock(return_value=True),
            delete_messages=AsyncMock(return_value=True),
            get_chat_history=history,
        )
        return client

    async def test_migrates_text_pin_to_photo_and_reuses_it(self):
        old_text_pin = SimpleNamespace(id=500, photo=None, text="KATALOG FILM A-Z", caption=None)
        client = self._client(old_text_pin)

        with patch.object(self.handlers, "resolve_homepage_assets", return_value=self.assets), \
             patch.object(self.handlers, "_apply_channel_post_styling", new=AsyncMock()), \
             patch.object(self.handlers, "_homepage_today_schedule", return_value=[]):
            ok = await self.handlers.update_pinned_homepage(
                client, "@film_indonesia1", [dict(MOVIES[0])], "https://telegra.ph/x", "film_bot"
            )

        self.assertTrue(ok)
        client.send_photo.assert_awaited_once()
        client.delete_messages.assert_any_await("@film_indonesia1", [500])
        self.assertEqual(self.cache.get_setting("homepage_msg_film_indonesia1"), "900")

        photo_pin = SimpleNamespace(id=900, photo=object(), text=None, caption="homepage")
        client2 = self._client(photo_pin)
        with patch.object(self.handlers, "resolve_homepage_assets", return_value=self.assets), \
             patch.object(self.handlers, "_apply_channel_post_styling", new=AsyncMock()), \
             patch.object(self.handlers, "_homepage_today_schedule", return_value=[]):
            ok = await self.handlers.update_pinned_homepage(
                client2, "@film_indonesia1", [dict(MOVIES[0])], "https://telegra.ph/x", "film_bot"
            )

        self.assertTrue(ok)
        client2.edit_message_media.assert_not_awaited()
        client2.edit_message_caption.assert_not_awaited()

    async def test_total_change_updates_media_in_place(self):
        photo_pin = SimpleNamespace(id=900, photo=object(), text=None, caption="homepage")
        self.cache.set_setting("homepage_msg_film_indonesia1", "900")
        self.cache.set_setting("homepage_sig_film_indonesia1", "old-signature")
        client = self._client(photo_pin)

        with patch.object(self.handlers, "resolve_homepage_assets", return_value=self.assets), \
             patch.object(self.handlers, "_apply_channel_post_styling", new=AsyncMock()), \
             patch.object(self.handlers, "_homepage_today_schedule", return_value=[]):
            ok = await self.handlers.update_pinned_homepage(
                client, "@film_indonesia1", [dict(MOVIES[0]), dict(MOVIES[1])],
                "https://telegra.ph/x", "film_bot"
            )

        self.assertTrue(ok)
        client.edit_message_media.assert_awaited_once()
        client.send_photo.assert_not_awaited()
        self.assertEqual(self.cache.get_setting("homepage_msg_film_indonesia1"), "900")

    async def test_http_edit_media_fallback_when_pyrogram_times_out(self):
        """If Pyrogram edit_message_media fails/times out, HTTP Bot API editMessageMedia updates in-place."""
        photo_pin = SimpleNamespace(id=900, photo=object(), text=None, caption="homepage")
        self.cache.set_setting("homepage_msg_film_indonesia1", "900")
        self.cache.set_setting("homepage_sig_film_indonesia1", "old-signature")
        client = self._client(photo_pin)
        client.edit_message_media = AsyncMock(side_effect=TimeoutError("DC5 media timeout"))

        with patch.object(self.handlers, "BOT_TOKEN", "123:TEST"), \
             patch.object(self.handlers, "resolve_homepage_assets", return_value=self.assets), \
             patch.object(self.handlers, "_http_edit_homepage_media", new=AsyncMock(return_value=True)) as mock_http_edit, \
             patch.object(self.handlers, "_homepage_today_schedule", return_value=[]):
            ok = await self.handlers.update_pinned_homepage(
                client, "@film_indonesia1", [dict(MOVIES[0]), dict(MOVIES[1])],
                "https://telegra.ph/x", "film_bot"
            )

        self.assertTrue(ok)
        mock_http_edit.assert_awaited_once()
        client.send_photo.assert_not_awaited()
        self.assertEqual(self.cache.get_setting("homepage_msg_film_indonesia1"), "900")


class TestHomepagePermissions(unittest.IsolatedAsyncioTestCase):
    async def test_channel_admin_without_can_pin_messages_is_allowed(self):
        """In Telegram broadcast channels, can_pin_messages is False by spec and pinning is granted via can_edit_messages."""
        from bot.handlers import _homepage_missing_permissions
        mock_client = AsyncMock()
        mock_client.me = SimpleNamespace(id=123)

        # Telegram channel admin privilege structure (can_pin_messages is False by Telegram specification)
        privileges = SimpleNamespace(
            can_post_messages=True,
            can_edit_messages=True,
            can_pin_messages=False,
            can_delete_messages=True,
            can_manage_chat=True
        )
        member = SimpleNamespace(
            status=SimpleNamespace(name="ADMINISTRATOR"),
            privileges=privileges
        )
        mock_client.get_chat_member = AsyncMock(return_value=member)

        missing = await _homepage_missing_permissions(mock_client, "@film_indonesia1")
        self.assertEqual(missing, [], "Channel admin with can_edit_messages=True should have no missing permissions")

    async def test_missing_edit_messages_reports_both(self):
        """If can_edit_messages is False, bot cannot edit or pin in channel."""
        from bot.handlers import _homepage_missing_permissions
        mock_client = AsyncMock()
        mock_client.me = SimpleNamespace(id=123)

        privileges = SimpleNamespace(
            can_post_messages=True,
            can_edit_messages=False,
            can_pin_messages=False
        )
        member = SimpleNamespace(
            status=SimpleNamespace(name="ADMINISTRATOR"),
            privileges=privileges
        )
        mock_client.get_chat_member = AsyncMock(return_value=member)

        missing = await _homepage_missing_permissions(mock_client, "@film_indonesia1")
        self.assertIn("edit pesan", missing)
        self.assertIn("pin pesan", missing)


if __name__ == "__main__":
    unittest.main()
