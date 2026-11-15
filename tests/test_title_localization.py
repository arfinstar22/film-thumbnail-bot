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
            "original_language": "id",
            "year": 2017,
        }
        accepted, title, year = resolve_verified_identity(
            "Satan's Slaves", 2017, rate_res, 0.95
        )

        self.assertTrue(accepted)
        self.assertEqual(title, "Pengabdi Setan")
        self.assertEqual(year, 2017)

    def test_petak_umpet_stays_petak_umpet_not_hide_and_seek(self):
        rate_res = {
            "verified_title": "Hide and Seek",
            "localized_title": "Hide and Seek",
            "original_title": "Petak Umpet",
            "alternative_titles": ["Hide and Seek"],
            "original_language": "id",
            "year": 2024,
        }
        # User input Petak Umpet harus tetap Petak Umpet
        accepted, title, year = resolve_verified_identity(
            "Petak Umpet", 2024, rate_res, 1.0
        )
        self.assertTrue(accepted)
        self.assertEqual(title, "Petak Umpet")
        self.assertEqual(year, 2024)

    def test_hide_and_seek_alias_resolves_to_petak_umpet(self):
        rate_res = {
            "verified_title": "Hide and Seek",
            "localized_title": "Hide and Seek",
            "original_title": "Petak Umpet",
            "alternative_titles": ["Hide and Seek"],
            "original_language": "id",
            "year": 2024,
        }
        # File bertuliskan Hide and Seek harus berubah jadi Petak Umpet
        accepted, title, year = resolve_verified_identity(
            "Hide and Seek", 2024, rate_res, 1.0
        )
        self.assertTrue(accepted)
        self.assertEqual(title, "Petak Umpet")
        self.assertEqual(year, 2024)

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

    def test_extract_prioritizes_indonesian_original_title_over_english_tmdb_title(self):
        details = {
            "id": 1290547,
            "title": "Hide and Seek",
            "original_title": "Petak Umpet",
            "original_language": "id",
            "release_date": "2024-11-21",
            "alternative_titles": {
                "titles": [{"iso_3166_1": "ID", "title": "Petak Umpet: Wewe Gombel"}]
            },
        }
        with patch.object(self.tmdb, "_fetch_omdb_extra", return_value={}):
            result = self.tmdb._extract_metadata(details, {}, "movie")

        # Harus memprioritaskan Petak Umpet, bukan Hide and Seek
        self.assertEqual(result["verified_title"], "Petak Umpet")
        self.assertEqual(result["localized_title"], "Petak Umpet")
        self.assertEqual(result["original_title"], "Petak Umpet")
        # Hide and Seek harus masuk ke alternative_titles
        self.assertIn("Hide and Seek", result["alternative_titles"])
        self.assertTrue(result["title_localized_checked"])


if __name__ == "__main__":
    unittest.main()
