"""Judul file berbahasa Inggris memakai judul Indonesia resmi dari TMDb."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata.engine import resolve_verified_identity
from bot.services.metadata.tmdb import TMDbService


class TestLocalizedTitleSelection(unittest.TestCase):
    def test_english_alias_uses_indonesian_title(self):
        rate_res = {
            "verified_title": "Pengabdi Setan",
            "localized_title": "Pengabdi Setan",
            "original_title": "Pengabdi Setan",
            "alternative_titles": ["Satan's Slaves"],
            "year": 2017,
        }
        accepted, title, year = resolve_verified_identity(
            "Satan's Slaves", 2017, rate_res, 0.95
        )

        self.assertTrue(accepted)
        self.assertEqual(title, "Pengabdi Setan")
        self.assertEqual(year, 2017)

    def test_english_original_title_stays_english(self):
        rate_res = {
            "verified_title": "The Most Beautiful Girl in the World",
            "localized_title": "The Most Beautiful Girl in the World",
            "original_title": "The Most Beautiful Girl in the World",
            "alternative_titles": ["Wanita Tercantik di Dunia"],
            "year": 2025,
        }
        accepted, title, year = resolve_verified_identity(
            "The Most Beautiful Girl in the World", 2025, rate_res, 0.95
        )

        self.assertTrue(accepted)
        self.assertEqual(title, "The Most Beautiful Girl in the World")
        self.assertEqual(year, 2025)


class TestTMDbAlternativeTitles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = MetadataCache(db_path=os.path.join(self.tmp.name, "title.db"))
        self.tmdb = TMDbService(cache=self.cache, api_key="dummy")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_keeps_localized_and_alternative_titles(self):
        details = {
            "id": 467012,
            "title": "Pengabdi Setan",
            "original_title": "Pengabdi Setan",
            "release_date": "2017-09-28",
            "alternative_titles": {
                "titles": [{"iso_3166_1": "US", "title": "Satan's Slaves"}]
            },
        }
        with patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            result = self.tmdb._extract_metadata(details, {}, "movie")

        self.assertEqual(result["localized_title"], "Pengabdi Setan")
        self.assertIn("Satan's Slaves", result["alternative_titles"])
        self.assertTrue(result["title_localized_checked"])


if __name__ == "__main__":
    unittest.main()
