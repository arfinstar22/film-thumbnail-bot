"""Regression tests: cache metadata lama tidak boleh mematikan "Urutan Nonton"."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata.engine import rescue_poster_metadata
from bot.services.metadata.rating import MovieRatingService
from bot.services.metadata.tmdb import TMDbService, normalize_title_for_match


PERAHU_COLLECTION = {
    "id": 55,
    "name": "Seri Perahu Kertas",
    "parts": [
        {"id": 1, "title": "Perahu Kertas", "year": 2012, "release_date": "2012-08-01"},
        {"id": 2, "title": "Perahu Kertas 2", "year": 2012, "release_date": "2012-12-01"},
    ],
}


def _movie():
    return {
        "id": 123,
        "title": "Perahu Kertas",
        "original_title": "Perahu Kertas",
        "release_date": "2012-08-01",
        "original_language": "id",
        "popularity": 8.0,
    }


def _details():
    return {
        "id": 123,
        "title": "Perahu Kertas",
        "original_title": "Perahu Kertas",
        "release_date": "2012-08-01",
        "vote_average": 7.0,
        "vote_count": 50,
        "genres": [{"id": 18, "name": "Drama"}],
        "overview": "Kisah Kugy dan Keenan.",
        "poster_path": "/p.jpg",
        "belongs_to_collection": {"id": 55, "name": "Perahu Kertas Collection"},
    }


class TestStaleRatingCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = MetadataCache(db_path=os.path.join(self.tmp.name, "rating.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_cache_without_collection_refetches_tmdb(self):
        key = "rating_v2_perahu kertas_2012"
        self.cache.set_setting(key, json.dumps({"rating": "7.0 / 10", "genre": "Drama"}))

        fake_tmdb = MagicMock()
        fake_tmdb.is_enabled.return_value = True
        fake_tmdb.search_movie.return_value = {
            "title": "Perahu Kertas",
            "rating": "7.0 / 10",
            "collection": PERAHU_COLLECTION,
            "collection_checked": True,
            "title_localized_checked": True,
        }

        service = MovieRatingService(cache=self.cache, tmdb_service=fake_tmdb)
        result = service._sync_fetch("Perahu Kertas", 2012)

        self.assertEqual(result["collection"]["name"], "Seri Perahu Kertas")
        fake_tmdb.search_movie.assert_called_once_with("Perahu Kertas", 2012)
        cached = json.loads(self.cache.get_setting(key, "{}"))
        self.assertEqual(cached["collection"]["id"], 55)

    def test_checked_cache_is_not_refetched(self):
        key = "rating_v2_perahu kertas_2012"
        self.cache.set_setting(key, json.dumps({
            "rating": "7.0 / 10",
            "collection_checked": True,
            "title_localized_checked": True,
        }))

        fake_tmdb = MagicMock()
        fake_tmdb.is_enabled.return_value = True
        service = MovieRatingService(cache=self.cache, tmdb_service=fake_tmdb)
        result = service._sync_fetch("Perahu Kertas", 2012)

        self.assertEqual(result["rating"], "7.0 / 10")
        fake_tmdb.search_movie.assert_not_called()


class TestTMDbCollectionCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = MetadataCache(db_path=os.path.join(self.tmp.name, "tmdb.db"))
        self.tmdb = TMDbService(cache=self.cache, api_key="dummy")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tmdb_cache_without_marker_refreshes_collection(self):
        import re
        key = (
            f"tmdb_v3_{re.sub(r'[^a-z0-9]+', '_', normalize_title_for_match('Perahu Kertas'))}"
            f"_2012_0"
        )
        self.cache.set_setting(key, json.dumps({"title": "Perahu Kertas", "rating": "7.0"}))

        def fake_get(endpoint, params):
            if endpoint.startswith("search"):
                return {"results": [_movie()]}
            if endpoint == "movie/123":
                return _details()
            if endpoint == "collection/55":
                return {
                    "id": 55,
                    "name": "Perahu Kertas Collection",
                    "parts": PERAHU_COLLECTION["parts"],
                }
            return {}

        with patch.object(self.tmdb, "_http_get", side_effect=fake_get), \
             patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            result = self.tmdb.search_movie("Perahu Kertas", 2012)

        self.assertEqual(result["collection"]["name"], "Seri Perahu Kertas")
        self.assertTrue(result["collection_checked"])
        self.assertTrue(result["title_localized_checked"])
        cached = json.loads(self.cache.get_setting(key, "{}"))
        self.assertEqual(cached["collection_id"], 55)

    def test_details_failure_is_not_marked_checked(self):
        with patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            result = self.tmdb._extract_metadata(_movie(), {}, "movie", details_ok=False)
        self.assertFalse(result["collection_checked"])


class TestPosterRescueKeepsCollection(unittest.TestCase):
    def test_rescue_copies_collection(self):
        import asyncio
        from unittest.mock import AsyncMock

        tmdb = MagicMock()
        tmdb.async_search_movie = AsyncMock(return_value={
            "poster_url": "https://image.tmdb.org/t/p/w500/p.jpg",
            "collection": PERAHU_COLLECTION,
            "collection_checked": True,
        })
        try:
            result = asyncio.run(
                rescue_poster_metadata({}, "Perahu Kertas", 2012, tmdb)
            )
        finally:
            asyncio.set_event_loop(asyncio.new_event_loop())

        self.assertEqual(result["collection"]["name"], "Seri Perahu Kertas")


if __name__ == "__main__":
    unittest.main()
