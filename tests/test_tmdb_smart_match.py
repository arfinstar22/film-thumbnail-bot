"""Tes pencocokan TMDb cerdas: typo, judul alternatif, tahun di judul, sinopsis Indonesia."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata.engine import resolve_verified_identity
from bot.services.metadata.tmdb import TMDbService


def _movie(mid, title, year, **extra):
    item = {
        "id": mid,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01" if year else "",
        "original_language": "id",
        "popularity": 5.0,
    }
    item.update(extra)
    return item


def _details(mid, title, year, overview="", translations=None, imdb_id=None):
    return {
        "id": mid,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01" if year else "",
        "vote_average": 7.2,
        "vote_count": 100,
        "genres": [{"id": 27, "name": "Horror"}],
        "overview": overview,
        "poster_path": "/p.jpg",
        "translations": {"translations": translations or []},
        "external_ids": {"imdb_id": imdb_id} if imdb_id else {},
    }


PENGABDI = _movie(467012, "Pengabdi Setan", 2017)
PENGABDI_DETAILS = _details(
    467012, "Pengabdi Setan", 2017,
    overview="Setelah ibunya meninggal, sebuah keluarga diteror sosok misterius.",
    translations=[{"iso_639_1": "en", "data": {"title": "Satan's Slaves"}}],
    imdb_id="tt7076834",
)


class TestSmartTMDbMatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = MetadataCache(db_path=os.path.join(self.tmp.name, "t.db"))
        self.tmdb = TMDbService(cache=self.cache, api_key="dummy")

    def tearDown(self):
        self.tmp.cleanup()

    def test_typo_falls_back_to_keyword_search(self):
        def fake_get(endpoint, params):
            query = (params or {}).get("query", "").lower()
            if endpoint.startswith("search") and "pengadi" in query and "setan" in query:
                return {"results": []}
            if endpoint.startswith("search") and query == "setan":
                return {"results": [PENGABDI]}
            if endpoint.startswith("search"):
                return {"results": []}
            if endpoint == "movie/467012":
                return PENGABDI_DETAILS
            return {}

        with patch.object(self.tmdb, "_http_get", side_effect=fake_get), \
             patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            res = self.tmdb.search_movie("Pengadi Setan", 2017)

        self.assertEqual(res.get("verified_title"), "Pengabdi Setan")
        self.assertEqual(res.get("year"), 2017)
        self.assertIn("7.2 / 10 • TMDb", res.get("rating", ""))
        self.assertEqual(res.get("imdb_id"), "tt7076834")

    def test_international_title_matches_via_translation(self):
        slaves = _movie(1418377, "Slaves", 2025, original_language="en")

        def fake_get(endpoint, params):
            if endpoint.startswith("search"):
                return {"results": [slaves, PENGABDI]}
            if endpoint == "movie/1418377":
                return {"id": 1418377, "title": "Slaves", "translations": {"translations": []}}
            if endpoint == "movie/467012":
                return PENGABDI_DETAILS
            return {}

        with patch.object(self.tmdb, "_http_get", side_effect=fake_get), \
             patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            res = self.tmdb.search_movie("Satan's Slaves", 2017)

        self.assertEqual(res.get("verified_title"), "Pengabdi Setan")
        self.assertEqual(res.get("year"), 2017)

    def test_indonesian_overview_from_translations(self):
        overview_id = "Seorang wanita kembali ke desa keluarganya dan menemukan teror."
        details = _details(
            999, "Film Uji", 2020, overview="",
            translations=[{"iso_639_1": "id", "data": {"overview": overview_id}}],
        )

        with patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            res = self.tmdb._extract_metadata(details, {}, "movie")

        self.assertEqual(res.get("plot"), overview_id)

    def test_year_inside_title_is_not_a_mismatch(self):
        rate_res = {"verified_title": "Dilan 1990", "year": 2018, "rating": "7.3 / 10 • TMDb"}
        accepted, title, year = resolve_verified_identity("Dilan", 1990, rate_res, 0.95)
        self.assertTrue(accepted)
        self.assertEqual(title, "Dilan 1990")
        self.assertEqual(year, 2018)

    def test_wrong_film_still_rejected(self):
        rate_res = {"verified_title": "Rasuk", "year": 2018, "rating": "3.9 / 10 • TMDb"}
        accepted, title, year = resolve_verified_identity("Para Perasuk", 2026, rate_res, 0.95)
        self.assertFalse(accepted)
        self.assertEqual(title, "Para Perasuk")
        self.assertEqual(year, 2026)


class TestEngineYearCorrection(unittest.TestCase):
    def test_dilan_year_in_title_adopted(self):
        import asyncio
        from unittest.mock import AsyncMock
        from bot.services.metadata.engine import MetadataEngine

        tmp = tempfile.TemporaryDirectory()
        try:
            cache = MetadataCache(db_path=os.path.join(tmp.name, "e.db"))
            engine = MetadataEngine()
            engine.cache = cache
            engine.caption_gen.cache = cache
            fake = {
                "verified_title": "Dilan 1990",
                "year": 2018,
                "rating": "7.3 / 10 • TMDb (39 ulasan)",
                "genre": "Drama, Romantis",
                "poster_url": "https://image.tmdb.org/t/p/w500/p.jpg",
            }
            with patch.object(engine.rating_service, "get_rating_and_genre", new=AsyncMock(return_value=fake)), \
                 patch.object(engine.synopsis_service, "get_synopsis", new=AsyncMock(return_value="")):
                try:
                    res = asyncio.run(engine.process("Dilan.1990.1080p.WEB-DL.mkv"))
                finally:
                    # Pyrogram butuh event loop default setelah asyncio.run menutupnya.
                    asyncio.set_event_loop(asyncio.new_event_loop())
            self.assertEqual(res["metadata"]["title"], "Dilan 1990")
            self.assertEqual(res["metadata"]["year"], 2018)
            self.assertIn("7.3", res["metadata"]["rating"])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
