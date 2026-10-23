"""Tests for Feature 1 (Smart Search & Fuzzy Matching) and Feature 2 (TMDb API Integration)."""
import os
import sys
import tempfile
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata.cache import (
    MetadataCache,
    calculate_search_relevance,
    normalize_movie_title_and_year
)
from bot.services.metadata.tmdb import TMDbService
from bot.services.metadata.rating import MovieRatingService
from bot.services.metadata.engine import MetadataEngine
from bot.services.metadata.banner import BannerGenerator


class TestSmartSearchAndFuzzyMatching(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_films.db")
        self.cache = MetadataCache(db_path=self.db_path)

        # Populate sample movie catalog
        self.sample_movies = [
            {
                "title": "Pengabdi Setan",
                "year": 2017,
                "rating": "7.0 / 10 • IMDb",
                "genre": "Horor, Misteri",
                "quality": "1080p",
                "channel_username": "film_indonesia1",
                "message_id": 101,
                "caption": "🎬 Pengabdi Setan (2017)\n⭐ Rating: 7.0\n🎭 Genre: Horor\nSutradara: Joko Anwar\nPemeran: Tara Basro, Bront Palarae\nSinopsis: Sebuah keluarga diteror entitas misterius."
            },
            {
                "title": "Pengabdi Setan 2: Communion",
                "year": 2022,
                "rating": "6.8 / 10 • IMDb",
                "genre": "Horor",
                "quality": "1080p",
                "channel_username": "film_indonesia1",
                "message_id": 102,
                "caption": "🎬 Pengabdi Setan 2 (2022)\nSutradara: Joko Anwar\nPemeran: Tara Basro, Ratu Felisha"
            },
            {
                "title": "Agak Laen",
                "year": 2024,
                "rating": "7.6 / 10 • IMDb",
                "genre": "Komedi, Horor",
                "quality": "1080p",
                "channel_username": "film_indonesia1",
                "message_id": 103,
                "caption": "🎬 Agak Laen (2024)\n🎭 Genre: Komedi\nPemeran: Boris Bokir, Indra Jegel, Bene Dion, Oki Rengga"
            },
            {
                "title": "Dilan 1990",
                "year": 2018,
                "rating": "7.2 / 10 • IMDb",
                "genre": "Romantis, Drama",
                "quality": "1080p",
                "channel_username": "film_indonesia1",
                "message_id": 104,
                "caption": "🎬 Dilan 1990 (2018)\nPemeran: Iqbaal Ramadhan, Vanesha Prescilla"
            },
            {
                "title": "Habibie & Ainun",
                "year": 2012,
                "rating": "7.6 / 10 • IMDb",
                "genre": "Drama, Biografi",
                "quality": "1080p",
                "channel_username": "film_indonesia1",
                "message_id": 105,
                "caption": "🎬 Habibie & Ainun (2012)\nSutradara: Faozan Rizal\nPemeran: Reza Rahadian, Bunga Citra Lestari\nSinopsis: Kisah cinta BJ Habibie dan Ainun."
            }
        ]

        for m in self.sample_movies:
            self.cache.save_movie_post(
                title=m["title"],
                year=m["year"],
                rating=m["rating"],
                genre=m["genre"],
                quality=m["quality"],
                channel_username=m["channel_username"],
                message_id=m["message_id"],
                caption=m["caption"]
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_search(self):
        results = self.cache.search_catalog("Agak Laen", limit=5)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["title"], "Agak Laen")
        self.assertFalse(results[0]["_is_fuzzy"])

    def test_fuzzy_search_with_typo(self):
        # User misspells 'Pengabdi Setan' as 'pengadi setan'
        results, suggestion = self.cache.search_catalog_with_suggestion("pengadi setan", limit=5)
        self.assertTrue(len(results) >= 1)
        self.assertIn("Pengabdi Setan", results[0]["title"])
        self.assertTrue(results[0]["_is_fuzzy"])
        self.assertIsNotNone(suggestion)
        self.assertIn("Pengabdi Setan", suggestion)

    def test_fuzzy_search_vowel_swap(self):
        # User types 'agak lain' instead of 'Agak Laen'
        results, suggestion = self.cache.search_catalog_with_suggestion("agak lain", limit=5)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["title"], "Agak Laen")

    def test_search_by_actor_in_caption(self):
        # Search by actor 'Reza Rahadian' -> should match 'Habibie & Ainun'
        results = self.cache.search_catalog("Reza Rahadian", limit=5)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["title"], "Habibie & Ainun")

    def test_search_by_director_in_caption(self):
        # Search by director 'Joko Anwar' -> should return Pengabdi Setan
        results = self.cache.search_catalog("Joko Anwar", limit=5)
        self.assertTrue(len(results) >= 1)
        titles = [r["title"] for r in results]
        self.assertTrue(any("Pengabdi Setan" in t for t in titles))

    def test_find_existing_movie_typo_protection(self):
        # Check that typing with a typo still identifies the existing movie to prevent duplicates
        found = self.cache.find_existing_movie("Pengadi Setan", 2017, "film_indonesia1")
        self.assertIsNotNone(found)
        self.assertEqual(found["title"], "Pengabdi Setan")

    def test_rasuk_vs_para_perasuk_not_duplicate(self):
        # Catalog has Rasuk (2018)
        self.cache.save_movie_post(
            title="Rasuk",
            year=2018,
            rating="3.9",
            genre="Horor",
            quality="1080p",
            channel_username="film_indonesia1",
            message_id=999,
            caption="Rasuk (2018)"
        )

        # Checking Para Perasuk (2026) must NOT match Rasuk (2018)
        found1 = self.cache.find_existing_movie("Para.Perasuk.2026.WEB.DL.720p.mp4", 2026, "film_indonesia1")
        self.assertIsNone(found1)

        found2 = self.cache.find_existing_movie("Para Perasuk", 2026, "film_indonesia1")
        self.assertIsNone(found2)

        # Even without explicit year passed, filename contains 2026 and title is distinct
        found3 = self.cache.find_existing_movie("Para.Perasuk.2026.WEB.DL.720p.mp4", None, "film_indonesia1")
        self.assertIsNone(found3)

        # Sequel Rasuk 2 (2020) must NOT be flagged as duplicate of Rasuk (2018)
        found_sequel = self.cache.find_existing_movie("Rasuk 2", 2020, "film_indonesia1")
        self.assertIsNone(found_sequel)

        # True duplicate of Rasuk (2018) must still be found
        found_exact = self.cache.find_existing_movie("Rasuk", 2018, "film_indonesia1")
        self.assertIsNotNone(found_exact)
        self.assertEqual(found_exact["title"], "Rasuk")


class TestTMDbService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_films.db")
        self.cache = MetadataCache(db_path=self.db_path)
        self.tmdb = TMDbService(cache=self.cache, api_key="dummy_test_key")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_key_resolution_and_status(self):
        self.assertEqual(self.tmdb.get_api_key(), "dummy_test_key")
        self.assertTrue(self.tmdb.is_enabled())

        with unittest.mock.patch.dict(os.environ, {"TMDB_API_KEY": ""}):
            no_key_tmdb = TMDbService(cache=self.cache, api_key=None)
            # Should be disabled when neither arg, env, nor setting is set
            self.assertFalse(no_key_tmdb.is_enabled())

        no_key_tmdb = TMDbService(cache=self.cache, api_key=None)

        # Test setting via cache
        self.cache.set_setting("tmdb_api_key", "key_from_db_setting")
        self.assertEqual(no_key_tmdb.get_api_key(), "key_from_db_setting")
        self.assertTrue(no_key_tmdb.is_enabled())

    def test_mock_search_movie_extraction(self):
        mock_search_resp = {
            "results": [
                {
                    "id": 12345,
                    "title": "Pengabdi Setan",
                    "original_title": "Pengabdi Setan",
                    "release_date": "2017-09-28",
                    "popularity": 45.2,
                    "media_type": "movie"
                }
            ]
        }
        mock_details_id = {
            "id": 12345,
            "title": "Pengabdi Setan",
            "original_title": "Pengabdi Setan",
            "release_date": "2017-09-28",
            "vote_average": 7.4,
            "vote_count": 890,
            "genres": [{"id": 27, "name": "Horror"}, {"id": 9648, "name": "Mystery"}],
            "overview": "Setelah sakit aneh selama bertahun-tahun, sang ibu wafat dan teror dimulai.",
            "poster_path": "/abc_poster.jpg",
            "backdrop_path": "/xyz_backdrop.jpg",
            "credits": {
                "crew": [{"job": "Director", "name": "Joko Anwar"}],
                "cast": [{"name": "Tara Basro"}, {"name": "Bront Palarae"}]
            },
            "videos": {
                "results": [
                    {"site": "YouTube", "type": "Trailer", "key": "trailer123"}
                ]
            }
        }

        with patch.object(self.tmdb, "_http_get") as mock_get:
            def side_effect(endpoint, params=None):
                if "search" in endpoint:
                    return mock_search_resp
                return mock_details_id

            mock_get.side_effect = side_effect

            res = self.tmdb.search_movie("Pengabdi Setan", 2017)
            self.assertEqual(res["verified_title"], "Pengabdi Setan")
            self.assertEqual(res["year"], 2017)
            self.assertIn("7.4 / 10 • TMDb", res["rating"])
            self.assertIn("Horor", res["genre"])
            self.assertIn("Misteri", res["genre"])
            self.assertEqual(res["director"], "Joko Anwar")
            self.assertIn("Tara Basro", res["actors"])
            self.assertEqual(res["poster_url"], "https://image.tmdb.org/t/p/original/abc_poster.jpg")
            self.assertEqual(res["backdrop_url"], "https://image.tmdb.org/t/p/original/xyz_backdrop.jpg")
            self.assertEqual(res["trailer_url"], "https://www.youtube.com/watch?v=trailer123")
            self.assertEqual(res["source"], "tmdb")

    def test_movie_rating_service_tmdb_priority(self):
        svc = MovieRatingService(cache=self.cache, tmdb_service=self.tmdb)
        fake_tmdb_data = {
            "verified_title": "Agak Laen",
            "rating": "7.6 / 10 • TMDb",
            "genre": "Komedi, Horor",
            "director": "Muhadkly Acho",
            "actors": "Boris Bokir, Indra Jegel",
            "poster_url": "https://image.tmdb.org/t/p/original/poster.jpg",
            "backdrop_url": "https://image.tmdb.org/t/p/original/backdrop.jpg",
            "trailer_url": "https://www.youtube.com/watch?v=agak123",
            "plot": "Empat sahabat pengelola rumah hantu di pasar malam.",
            "source": "tmdb"
        }
        with patch.object(self.tmdb, "search_movie", return_value=fake_tmdb_data):
            res = svc._sync_fetch("Agak Laen", 2024)
            self.assertEqual(res["verified_title"], "Agak Laen")
            self.assertEqual(res["source"], "tmdb")
            self.assertEqual(res["trailer_url"], "https://www.youtube.com/watch?v=agak123")

    def test_banner_generator_with_backdrop(self):
        bg = BannerGenerator()
        meta = {
            "title": "PENGABDI SETAN",
            "year": 2017,
            "rating": "7.4 / 10 • TMDb",
            "genre": "Horor, Misteri",
            "backdrop_url": None,
            "poster_url": None
        }
        banner = bg.create_banner(meta)
        self.assertEqual(banner.size, (1280, 720))

    def test_pick_best_match_rejects_year_mismatch_and_partial_words(self):
        # When searching 'Para Perasuk' (2026), TMDb candidate 'Rasuk' (2018) must be rejected
        candidates = [
            {
                "id": 529123,
                "title": "Rasuk",
                "original_title": "Rasuk",
                "release_date": "2018-06-27",
                "popularity": 12.5
            }
        ]
        match = self.tmdb._pick_best_match(candidates, "Para Perasuk", 2026, False)
        self.assertIsNone(match)

    def test_engine_rejects_year_mismatched_title_hijacking(self):
        import asyncio
        from bot.services.metadata.engine import MetadataEngine
        engine = MetadataEngine()
        fake_mismatched_rate = {
            "verified_title": "Rasuk",
            "year": 2018,
            "rating": "3.9 / 10 • TMDb",
            "genre": "Horor",
            "director": "Ubay Fox",
            "actors": "Shandy Aulia",
            "plot": "Langgir Janaka..."
        }
        with patch.object(engine.rating_service, "get_rating_and_genre", return_value=fake_mismatched_rate):
            res = asyncio.run(engine.process(filename="Para.Perasuk.2026.WEB.DL.720p.mp4"))
            meta = res["metadata"]
            self.assertEqual(meta["title"], "Para Perasuk")
            self.assertEqual(meta["year"], 2026)
            self.assertNotEqual(meta.get("director"), "Ubay Fox")


if __name__ == "__main__":
    unittest.main()
