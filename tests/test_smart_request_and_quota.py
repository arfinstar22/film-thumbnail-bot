import os
import sys
import unittest
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/home/darfinstar/projectTumbnail/.env")

from bot.services.metadata.cache import MetadataCache
from bot.services.metadata.tmdb import TMDbService


class TestSmartRequestAndQuota(unittest.TestCase):
    def setUp(self):
        self.test_db = "/tmp/test_request_quota.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.cache = MetadataCache(self.test_db)
        self.tmdb = TMDbService(cache=self.cache)

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_daily_request_quota_limits(self):
        user_id = 12345
        username = "film_geek"
        channel_wm = "film_indonesia1"

        # Initially 0 requests
        allowed, count, remaining = self.cache.check_user_request_quota(user_id, max_limit=10)
        self.assertTrue(allowed)
        self.assertEqual(count, 0)
        self.assertEqual(remaining, 10)

        # Submit 10 requests
        for i in range(1, 11):
            res = self.cache.add_movie_request(user_id, username, f"Film Bagus {i}", channel_wm, max_limit=10)
            self.assertTrue(res.get("success"))
            self.assertTrue(res.get("is_new"))
            self.assertEqual(res.get("count_today"), i)
            self.assertEqual(res.get("remaining"), 10 - i)

        # 11th check should be disallowed
        allowed, count, remaining = self.cache.check_user_request_quota(user_id, max_limit=10)
        self.assertFalse(allowed)
        self.assertEqual(count, 10)
        self.assertEqual(remaining, 0)

        # Another user still has quota
        other_user = 99999
        allowed_other, count_other, remaining_other = self.cache.check_user_request_quota(other_user, max_limit=10)
        self.assertTrue(allowed_other)
        self.assertEqual(count_other, 0)
        self.assertEqual(remaining_other, 10)

    def test_smart_suggestion_rasik_2018(self):
        """User typos 'rasik 2018', bot must suggest 'Rasuk (2018)'."""
        suggestion = self.tmdb.suggest_movie_correction("rasik 2018")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.get("title"), "Rasuk")
        self.assertEqual(suggestion.get("year"), 2018)
        self.assertTrue(suggestion.get("is_typo"))

    def test_smart_suggestion_rasuk_2017(self):
        """User enters 'Rasuk 2017', bot must correct release year to 2018."""
        suggestion = self.tmdb.suggest_movie_correction("Rasuk 2017")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.get("title"), "Rasuk")
        self.assertEqual(suggestion.get("year"), 2018)
        self.assertTrue(suggestion.get("is_year_corrected"))

    def test_smart_suggestion_pengabdi_satan(self):
        """User typos 'Pengabdi Satan 2017', bot must suggest 'Pengabdi Setan (2017)'."""
        suggestion = self.tmdb.suggest_movie_correction("Pengabdi Satan 2017")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.get("title"), "Pengabdi Setan")
        self.assertEqual(suggestion.get("year"), 2017)
        self.assertTrue(suggestion.get("is_typo"))

    def test_smart_suggestion_exact_match_no_suggestion(self):
        """Exact matches shouldn't produce a typo suggestion."""
        suggestion = self.tmdb.suggest_movie_correction("Mencuri Raden Saleh 2022")
        self.assertIsNone(suggestion)

    def test_catalog_search_exact_and_typo_agak_laen(self):
        """Catalog search must match both 'agak laen' and typo 'agak lain'."""
        self.cache.save_movie_post(
            title="Agak Laen",
            year=2024,
            rating="7.5",
            genre="Comedy, Horror",
            quality="1080p",
            channel_username="film_indonesia1",
            message_id=75
        )

        # Exact match test
        res_exact = self.cache.search_catalog("agak laen")
        self.assertTrue(len(res_exact) >= 1)
        self.assertEqual(res_exact[0]["title"], "Agak Laen")
        self.assertEqual(res_exact[0]["message_id"], 75)

        # Typo match test (agak lain -> Agak Laen)
        res_typo = self.cache.search_catalog("agak lain")
        self.assertTrue(len(res_typo) >= 1)
        self.assertEqual(res_typo[0]["title"], "Agak Laen")
        self.assertTrue(res_typo[0]["_is_fuzzy"])

    def test_catalog_empty_query_returns_latest_movies(self):
        """When query is empty, catalog search must return all latest indexed movies."""
        self.cache.save_movie_post(title="Film A", year=2021, channel_username="film_indonesia1", message_id=10)
        self.cache.save_movie_post(title="Film B", year=2022, channel_username="film_indonesia1", message_id=20)
        res = self.cache.search_catalog("", limit=10)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["title"], "Film B")
        self.assertEqual(res[1]["title"], "Film A")

    def test_catalog_gibberish_query_returns_empty(self):
        """Gibberish query must not return unrelated movies."""
        self.cache.save_movie_post(title="Dilan 1990", year=2018, channel_username="film_indonesia1", message_id=10)
        res = self.cache.search_catalog("film yang tidak ada sama sekali xyz")
        self.assertEqual(len(res), 0)

    def test_supabase_hydrate_ensures_sqlite_tables(self):
        """Supabase hydration into completely empty database must create all tables and not crash."""
        import sqlite3
        from bot.services.metadata.supabase_sync import SupabaseSyncService
        sync = SupabaseSyncService()
        mem_conn = sqlite3.connect(":memory:")
        res = sync.hydrate_to_sqlite(mem_conn)
        self.assertIsInstance(res, dict)
        cur = mem_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cur.fetchall()]
        self.assertIn("movie_catalog", tables)
        self.assertIn("settings", tables)
        self.assertIn("bot_users", tables)


if __name__ == "__main__":
    unittest.main()
